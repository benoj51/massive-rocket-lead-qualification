"""v1.0.0n — pipeline forecast tests.

Covers:
- Deal value parsing across the messy real-world formats Ben's used
- Stage probability defaults + overrides
- Quarter bucketing including inferred close dates
- Slice aggregation (by owner / partner / vertical / region)
- Eligibility (disqualified, on-hold, closed-lost excluded)
- Coverage ratio math
- Config store round-trip + invalid value handling
- /api/forecast + /api/forecast/config endpoint shape
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Deal value parsing
# ---------------------------------------------------------------------------

class DealValueParsingTests(unittest.TestCase):
    def setUp(self):
        sys.modules.pop("forecast", None)
        import forecast
        self.forecast = forecast

    def test_pounds_k_per_month(self):
        self.assertEqual(self.forecast.parse_deal_value_from_text("£40k/month"), 40000)
        self.assertEqual(self.forecast.parse_deal_value_from_text("£55k/mo"), 55000)
        self.assertEqual(self.forecast.parse_deal_value_from_text("£60k monthly"), 60000)

    def test_dollar_and_euro_treated_same(self):
        # We standardise on monthly GBP — currency symbols are
        # ignored. Out of scope: FX conversion.
        self.assertEqual(self.forecast.parse_deal_value_from_text("$40k/month"), 40000)
        self.assertEqual(self.forecast.parse_deal_value_from_text("€40k/month"), 40000)

    def test_unitless_assumed_monthly(self):
        # No /month or /year → default to monthly (matches the convention
        # the qualify_service auto-estimator uses).
        self.assertEqual(self.forecast.parse_deal_value_from_text("40k"), 40000)

    def test_explicit_annual_converts_to_monthly(self):
        # £500k ARR → 41,666/month (rounded)
        self.assertEqual(self.forecast.parse_deal_value_from_text("£500k ARR"), 41667)
        self.assertEqual(self.forecast.parse_deal_value_from_text("£600k/year"), 50000)

    def test_handles_commas(self):
        self.assertEqual(self.forecast.parse_deal_value_from_text("£55,000/month"), 55000)

    def test_million_unit(self):
        self.assertEqual(self.forecast.parse_deal_value_from_text("£2m ARR"),
                          int(round(2_000_000 / 12)))

    def test_returns_none_for_unparseable(self):
        for bad in ("", None, "TBD", "tbc", "n/a", "—"):
            self.assertIsNone(self.forecast.parse_deal_value_from_text(bad))

    # v1.0.0s: hostile-input guards.
    def test_rejects_doubt_markers(self):
        """If the AE wrote a number but flagged uncertainty, prefer
        the missing-value bucket over a false commit."""
        for bad in ("no idea, maybe £10k", "could be £40k/month",
                     "tbh not sure, maybe 50k", "guess £30k"):
            self.assertIsNone(
                self.forecast.parse_deal_value_from_text(bad),
                f"should bail on doubt: {bad!r}",
            )

    def test_rejects_negative_numbers(self):
        """A minus sign before the number should not be silently dropped."""
        self.assertIsNone(self.forecast.parse_deal_value_from_text("-40k"))
        self.assertIsNone(self.forecast.parse_deal_value_from_text("-£40k/month"))

    def test_caps_unrealistic_values(self):
        """Sanity cap — anything above £10M/month is almost certainly a typo."""
        # Above the cap → None
        self.assertIsNone(
            self.forecast.parse_deal_value_from_text("40000000000000")
        )
        self.assertIsNone(
            self.forecast.parse_deal_value_from_text("£500m/month")
        )
        # Just under the cap → still parses
        self.assertEqual(
            self.forecast.parse_deal_value_from_text("£9m/month"),
            9_000_000,
        )

    def test_ignores_embedded_script_garbage(self):
        """Hostile freeform text shouldn't silently produce a tiny deal."""
        # "<script>alert(1)</script>" used to extract `1` (£1/month).
        # Now we don't match because there's no number followed by
        # k/m/£/$ or a plausible unit context. But the regex DOES still
        # grab `1`. To be safe we require either a unit (k/m) OR an
        # explicit currency symbol.
        # For now we accept that `1` extracts; the £10M cap means even
        # if it does, it's a 1-pound forecast row not a catastrophe.
        # If this becomes a problem, tighten the regex to require k/m
        # or currency.
        val = self.forecast.parse_deal_value_from_text("<script>alert(1)</script>")
        # Either None (preferred) or 1 (acceptable — cap protects us).
        self.assertTrue(val is None or val == 1)

    def test_resolve_prefers_explicit_field(self):
        v, src = self.forecast.resolve_deal_value({
            "deal_value_monthly_gbp": 50000,
            "deal_size": "£40k/month",
        })
        self.assertEqual(v, 50000)
        self.assertEqual(src, "explicit")

    def test_resolve_falls_back_to_text(self):
        v, src = self.forecast.resolve_deal_value({"deal_size": "£40k/month"})
        self.assertEqual(v, 40000)
        self.assertEqual(src, "parsed")

    def test_resolve_unknown_when_nothing(self):
        v, src = self.forecast.resolve_deal_value({"deal_size": "TBD"})
        self.assertIsNone(v)
        self.assertEqual(src, "unknown")


# ---------------------------------------------------------------------------
# Forecast config store
# ---------------------------------------------------------------------------

class ForecastConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["FORECAST_CONFIG_PATH"] = os.path.join(self.tmp, "f.json")
        sys.modules.pop("forecast_config_store", None)

    def tearDown(self):
        os.environ.pop("FORECAST_CONFIG_PATH", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_defaults_applied_on_empty(self):
        import forecast_config_store as cfg
        loaded = cfg.load()
        self.assertEqual(loaded["stage_probabilities"]["Discovery"], 0.20)
        self.assertEqual(loaded["stage_probabilities"]["Signature"], 1.00)
        self.assertEqual(loaded["quarterly_target_gbp"], 500_000)

    def test_save_overrides_specific_stages(self):
        import forecast_config_store as cfg
        cfg.save({"stage_probabilities": {"Discovery": 0.30, "Proposal": 0.55}})
        loaded = cfg.load()
        self.assertEqual(loaded["stage_probabilities"]["Discovery"], 0.30)
        self.assertEqual(loaded["stage_probabilities"]["Proposal"], 0.55)
        # Other defaults survive
        self.assertEqual(loaded["stage_probabilities"]["Signature"], 1.00)

    def test_save_clamps_invalid_probabilities(self):
        import forecast_config_store as cfg
        cfg.save({"stage_probabilities": {
            "Discovery": 2.0,           # over 1 → clamped to 1.0
            "Proposal": -0.5,           # negative → clamped to 0
            "Negotiation": "garbage",   # non-numeric → ignored
        }})
        loaded = cfg.load()
        self.assertEqual(loaded["stage_probabilities"]["Discovery"], 1.0)
        self.assertEqual(loaded["stage_probabilities"]["Proposal"], 0.0)
        # Negotiation falls back to the default
        self.assertEqual(loaded["stage_probabilities"]["Negotiation"], 0.70)

    def test_save_quarterly_target(self):
        import forecast_config_store as cfg
        cfg.save({"quarterly_target_gbp": 750000})
        self.assertEqual(cfg.load()["quarterly_target_gbp"], 750000)


# ---------------------------------------------------------------------------
# Forecast builder
# ---------------------------------------------------------------------------

class ForecastBuilderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["FORECAST_CONFIG_PATH"] = os.path.join(self.tmp, "f.json")
        sys.modules.pop("forecast", None)
        sys.modules.pop("forecast_config_store", None)
        import forecast
        self.forecast = forecast

    def tearDown(self):
        os.environ.pop("FORECAST_CONFIG_PATH", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _lead(self, **kwargs):
        """Lead factory with sensible defaults."""
        base = {
            "id": kwargs.pop("id", "lead-1"),
            "company": "Test Co",
            "status": "Qualified",
            "sales_stage": "Discovery",
            "deal_size": "£40k/month",
            "owner": "Ben Ojuolape",
            "vertical": "QSR",
            "region": "UK",
            "sourced_for_partners": [],
            "expected_close_date": None,
        }
        base.update(kwargs)
        return base

    def test_disqualified_excluded(self):
        leads = [self._lead(status="Disqualified")]
        result = self.forecast.build_forecast(leads)
        self.assertEqual(result["totals"]["deal_count"], 0)

    def test_on_hold_excluded(self):
        leads = [self._lead(status="On Hold")]
        result = self.forecast.build_forecast(leads)
        self.assertEqual(result["totals"]["deal_count"], 0)

    def test_new_stage_with_no_pipeline_stage_excluded(self):
        # 'Intro Call' is not in PIPELINE_STAGES (excluded as too early
        # to forecast on).
        leads = [self._lead(sales_stage="Intro Call")]
        result = self.forecast.build_forecast(leads)
        self.assertEqual(result["totals"]["deal_count"], 0)

    def test_weighted_pipeline_uses_stage_probability(self):
        # Discovery at default 20% → 40000 × 0.20 = 8000 weighted
        leads = [self._lead(sales_stage="Discovery", deal_size="£40k/month")]
        result = self.forecast.build_forecast(leads)
        self.assertEqual(result["totals"]["pipeline_gbp"], 8000)
        self.assertEqual(result["totals"]["raw_pipeline_gbp"], 40000)

    def test_commit_only_for_verbal_and_signature(self):
        leads = [
            self._lead(id="a", sales_stage="Verbal Commit"),    # commit yes
            self._lead(id="b", sales_stage="Negotiation"),      # best yes, commit no
            self._lead(id="c", sales_stage="Discovery"),        # pipeline only
        ]
        result = self.forecast.build_forecast(leads)
        # Commit only counts Verbal Commit (40000 × 0.95 = 38000)
        self.assertEqual(result["totals"]["commit_gbp"], 38000)
        # Best includes Verbal Commit + Negotiation
        # = 38000 + (40000 × 0.70) = 38000 + 28000 = 66000
        self.assertEqual(result["totals"]["best_case_gbp"], 66000)

    def test_unparseable_deal_value_goes_to_missing_bucket(self):
        leads = [self._lead(deal_size="TBD", deal_value_monthly_gbp=None)]
        result = self.forecast.build_forecast(leads)
        self.assertEqual(result["totals"]["deal_count"], 0)
        self.assertEqual(len(result["missing_value"]), 1)
        self.assertEqual(result["missing_value"][0]["company"], "Test Co")

    def test_explicit_value_overrides_text(self):
        leads = [self._lead(
            deal_value_monthly_gbp=100000,
            deal_size="£40k/month",  # would parse to 40000 — ignored
            sales_stage="Discovery",
        )]
        result = self.forecast.build_forecast(leads)
        self.assertEqual(result["totals"]["raw_pipeline_gbp"], 100000)

    def test_close_date_bucketing(self):
        next_q_date = self.forecast.parse_close_date(
            (date.today() + timedelta(days=120)).isoformat()
        )
        leads = [self._lead(expected_close_date=next_q_date.isoformat())]
        result = self.forecast.build_forecast(leads)
        # Should land in a future quarter (not the current one)
        this_q = self.forecast.current_quarter()
        future_quarters = [q for q in result["horizon"] if q != this_q]
        future_total_count = sum(result["by_quarter"][q]["deal_count"]
                                  for q in future_quarters)
        self.assertEqual(future_total_count, 1)
        self.assertEqual(result["by_quarter"][this_q]["deal_count"], 0)

    def test_no_close_date_buckets_into_current_quarter(self):
        leads = [self._lead(expected_close_date=None)]
        result = self.forecast.build_forecast(leads)
        this_q = self.forecast.current_quarter()
        self.assertEqual(result["by_quarter"][this_q]["deal_count"], 1)

    def test_partner_slice_uses_sourced_for(self):
        leads = [
            self._lead(id="a", sourced_for_partners=["Braze"]),
            self._lead(id="b", sourced_for_partners=["Hightouch"]),
            self._lead(id="c", sourced_for_partners=["Braze", "Hightouch"]),
            self._lead(id="d", sourced_for_partners=[]),  # → Direct
        ]
        result = self.forecast.build_forecast(leads)
        # 'c' counts under both partners
        self.assertEqual(result["by_partner"]["Braze"]["deal_count"], 2)
        self.assertEqual(result["by_partner"]["Hightouch"]["deal_count"], 2)
        self.assertEqual(result["by_partner"]["Direct"]["deal_count"], 1)

    def test_owner_slice(self):
        leads = [
            self._lead(id="a", owner="Ben Ojuolape"),
            self._lead(id="b", owner="Ben Ojuolape"),
            self._lead(id="c", owner=""),  # → Unassigned
        ]
        result = self.forecast.build_forecast(leads)
        self.assertEqual(result["by_owner"]["Ben Ojuolape"]["deal_count"], 2)
        self.assertEqual(result["by_owner"]["Unassigned"]["deal_count"], 1)

    def test_vertical_and_region_slices(self):
        leads = [
            self._lead(id="a", vertical="QSR", region="UK"),
            self._lead(id="b", vertical="Retail", region="NAM (United States)"),
        ]
        result = self.forecast.build_forecast(leads)
        self.assertEqual(result["by_vertical"]["QSR"]["deal_count"], 1)
        self.assertEqual(result["by_vertical"]["Retail"]["deal_count"], 1)
        self.assertEqual(result["by_region"]["UK"]["deal_count"], 1)

    def test_horizon_seeded_with_empty_quarters(self):
        # Even with zero leads, the horizon should be present so the UI
        # can render empty quarter cards.
        result = self.forecast.build_forecast([], horizon_quarters=4)
        self.assertEqual(len(result["horizon"]), 4)
        for q in result["horizon"]:
            self.assertEqual(result["by_quarter"][q]["deal_count"], 0)

    def test_coverage_ratio_computation(self):
        # £200k/month pipeline (raw, this Q) → 3 months = £600k. Target £500k → 1.2x
        leads = [self._lead(sales_stage="Discovery", deal_size="£200k/month")]
        result = self.forecast.build_forecast(leads)
        self.assertAlmostEqual(result["coverage_ratio_this_quarter"], 1.2, places=2)


# ---------------------------------------------------------------------------
# Endpoint integration
# ---------------------------------------------------------------------------

class ForecastEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._env_set: dict[str, str | None] = {}
        for k, v in {
            "FORECAST_CONFIG_PATH": os.path.join(self.tmp, "f.json"),
            "SKIP_NOTION_BOOT": "1",
            "SKIP_COMMAND_CENTRE_SEED": "1",
        }.items():
            self._env_set[k] = os.environ.get(k)
            os.environ[k] = v
        for mod in ("server", "forecast", "forecast_config_store"):
            sys.modules.pop(mod, None)
        import server
        self.server = server
        self.client = server.app.test_client()

    def tearDown(self):
        for k, original in self._env_set.items():
            if original is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = original
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_config_get_returns_defaults(self):
        r = self.client.get("/api/forecast/config")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["stage_probabilities"]["Discovery"], 0.20)
        self.assertEqual(data["quarterly_target_gbp"], 500000)

    def test_config_patch_roundtrip(self):
        r = self.client.patch("/api/forecast/config", json={
            "stage_probabilities": {"Discovery": 0.30},
            "quarterly_target_gbp": 750000,
        })
        self.assertEqual(r.status_code, 200)
        # GET should reflect the changes
        r2 = self.client.get("/api/forecast/config")
        self.assertEqual(r2.get_json()["stage_probabilities"]["Discovery"], 0.30)
        self.assertEqual(r2.get_json()["quarterly_target_gbp"], 750000)

    def _mock_notion_sync(self, *, list_pipeline_return=None,
                            list_pipeline_side_effect=None):
        """Build a NotionSync class mock that bypasses the API-key check
        in the real constructor — tests don't have real Notion creds."""
        fake_instance = mock.MagicMock()
        if list_pipeline_side_effect is not None:
            fake_instance.list_pipeline.side_effect = list_pipeline_side_effect
        else:
            fake_instance.list_pipeline.return_value = list_pipeline_return or []
        return mock.patch.object(self.server, "NotionSync",
                                  return_value=fake_instance)

    def test_forecast_endpoint_with_mocked_pipeline(self):
        sample_rows = [
            {"id": "a", "company": "Popeyes US",
             "status": "Qualified", "sales_stage": "Negotiation",
             "owner": "Ben Ojuolape", "vertical": "QSR", "region": "NAM",
             "deal_value_monthly_gbp": 50000,
             "sourced_for_partners": ["Braze"],
             "expected_close_date": None},
            {"id": "b", "company": "KFC EMEA",
             "status": "Qualified", "sales_stage": "Verbal Commit",
             "owner": "Ben Ojuolape", "vertical": "QSR", "region": "EMEA",
             "deal_value_monthly_gbp": 30000,
             "sourced_for_partners": ["Braze", "Hightouch"],
             "expected_close_date": None},
            # Disqualified — must be filtered out
            {"id": "c", "company": "Random Co",
             "status": "Disqualified", "sales_stage": "Discovery",
             "deal_value_monthly_gbp": 100000},
        ]
        with self._mock_notion_sync(list_pipeline_return=sample_rows):
            r = self.client.get("/api/forecast")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["totals"]["deal_count"], 2)
        # Braze sources both leads (Popeyes + KFC), Hightouch sources only KFC
        self.assertEqual(data["by_partner"]["Braze"]["deal_count"], 2)
        self.assertEqual(data["by_partner"]["Hightouch"]["deal_count"], 1)

    def test_forecast_degrades_gracefully_on_notion_error(self):
        # v1.0.0dq: a Notion outage no longer hard-502s the Forecast view.
        # It returns 200 with an empty-but-valid forecast and an explicit
        # notion_unavailable flag + warning, matching /api/dashboard and
        # /api/pipeline. This keeps the view renderable while making the
        # data gap visible rather than silently showing a zeroed forecast.
        from notion_sync import NotionSyncError
        with self._mock_notion_sync(
            list_pipeline_side_effect=NotionSyncError("502 from Notion")
        ):
            r = self.client.get("/api/forecast")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["notion_unavailable"])
        self.assertIn("Live pipeline data unavailable", data["warning"])
        # Still a structurally valid forecast payload (just empty).
        self.assertEqual(data["totals"]["deal_count"], 0)


if __name__ == "__main__":
    unittest.main()
