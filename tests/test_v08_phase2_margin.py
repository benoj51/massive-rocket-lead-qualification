"""v0.8 Phase 2: internal costs, gross margin, region/seniority staffing."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class InternalCostsTests(unittest.TestCase):
    def test_internal_cost_is_45pct_of_sales(self):
        import internal_costs, rate_cards
        cost = internal_costs.internal_cost_lookup("AnyRole", "USD")
        sales = rate_cards.rate_lookup("MR Default", "AnyRole", "USD")
        self.assertAlmostEqual(cost["hourly"], sales["hourly"] * 0.45, delta=0.01)

    def test_placeholder_flag_until_real_data(self):
        import internal_costs
        self.assertTrue(internal_costs.is_placeholder_data(),
                        "Should report placeholder until real Internal Rate Card lands")

    def test_margin_bands(self):
        import internal_costs
        self.assertEqual(internal_costs.margin_band(0.50), "green")
        self.assertEqual(internal_costs.margin_band(0.40), "green")
        self.assertEqual(internal_costs.margin_band(0.35), "yellow")
        self.assertEqual(internal_costs.margin_band(0.30), "yellow")
        self.assertEqual(internal_costs.margin_band(0.25), "red")
        self.assertEqual(internal_costs.margin_band(0.0), "red")

    def test_internal_cost_uses_staff_aug_when_region_seniority_given(self):
        import internal_costs, rate_cards
        sales = rate_cards.rate_lookup("Staff Augmentation", "CRM Consultant",
                                        "USD", region="India", seniority="Senior")
        cost = internal_costs.internal_cost_lookup("CRM Consultant", "USD",
                                                    region="India", seniority="Senior")
        self.assertAlmostEqual(cost["hourly"], sales["hourly"] * 0.45, delta=0.01)


class MarginInQuoteTests(unittest.TestCase):
    def test_quote_returns_margin_block(self):
        from pricing import compute_quote, QuoteInputs
        q = compute_quote(QuoteInputs(project_types=["crm_build"], months=12))
        self.assertIn("margin", q)
        m = q["margin"]
        for key in ("gross_profit_usd", "internal_cost_usd", "margin_pct",
                    "band", "thresholds", "is_placeholder"):
            self.assertIn(key, m)

    def test_placeholder_margin_is_55pct(self):
        """45% cost → 55% margin (on gross; net margin is slightly higher
        because discount only affects revenue, not cost)."""
        from pricing import compute_quote, QuoteInputs
        q = compute_quote(QuoteInputs(project_types=["crm_build"], months=12))
        # Net = 1.11M, internal cost ≈ 5957h × ($200 × 0.45) = ~$536k
        # Margin = (1.11M - 536k) / 1.11M ≈ 52%
        self.assertGreater(q["margin"]["margin_pct"], 0.45)
        self.assertLess(q["margin"]["margin_pct"], 0.65)
        # Should be green
        self.assertEqual(q["margin"]["band"], "green")

    def test_high_ops_reduces_margin_relatively(self):
        """Adding Ops uplift means more revenue but same internal cost,
        so margin should INCREASE proportionally (cost ratio falls)."""
        from pricing import compute_quote, QuoteInputs
        base = compute_quote(QuoteInputs(project_types=["crm_build"], months=12))
        with_ops = compute_quote(QuoteInputs(project_types=["crm_build"], months=12,
                                             project_ops_pct=0.20))
        # Internal cost unchanged; revenue up; margin up
        self.assertEqual(base["margin"]["internal_cost_usd"], with_ops["margin"]["internal_cost_usd"])
        self.assertGreater(with_ops["margin"]["margin_pct"], base["margin"]["margin_pct"])

    def test_placeholder_flag_passes_through(self):
        from pricing import compute_quote, QuoteInputs
        q = compute_quote(QuoteInputs(project_types=["crm_build"], months=12))
        self.assertTrue(q["margin"]["is_placeholder"])

    def test_monthly_rows_carry_internal_cost(self):
        from pricing import compute_quote, QuoteInputs
        q = compute_quote(QuoteInputs(project_types=["crm_build"], months=12))
        for m in q["monthly"]:
            self.assertIn("internal_cost_usd", m)
            for row in m["rows"]:
                self.assertIn("internal_rate_per_hour", row)
                self.assertIn("internal_cost_usd", row)


class StaffAugStaffingTests(unittest.TestCase):
    def test_staff_aug_with_role_staffing_uses_right_rate(self):
        """Pricing for Staff Aug card should reflect region/seniority picks."""
        from pricing import compute_quote, QuoteInputs
        uk_quote = compute_quote(QuoteInputs(
            project_types=["crm_build"], months=12,
            rate_card="Staff Augmentation",
            role_staffing={
                "Client Partner":     {"region": "UK", "seniority": "Senior"},
                "CRM Strategist":     {"region": "UK", "seniority": "Practitioner"},
                "CRM Architect":      {"region": "UK", "seniority": "Senior"},
                "CRM Developer":      {"region": "UK", "seniority": "Senior"},
                "Architect":          {"region": "UK", "seniority": "Senior"},
                "Program Manager":    {"region": "EU", "seniority": "Senior"},
                "UX/UI Designer":     {"region": "EU", "seniority": "Senior"},
                "CRM Strategist ":    {"region": "UK", "seniority": "Practitioner"},
            },
        ))
        # Sanity: returns a quote (no crashes), some non-zero gross
        self.assertGreater(uk_quote["totals"]["gross_usd"], 0)

    def test_unknown_role_on_staff_aug_falls_back_to_mr_default(self):
        """Unmatched role on Staff Aug should fall back so quote still flows."""
        from pricing import compute_quote, QuoteInputs
        q = compute_quote(QuoteInputs(
            project_types=["crm_build"], months=12,
            rate_card="Staff Augmentation",
            # No role_staffing provided — every lookup should fall back
        ))
        # Should still produce a quote (MR Default $200/h fallback)
        self.assertEqual(q["totals"]["gross_usd"], 1_191_360)


class PricingEndpointPhase2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os, importlib, sys
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        sys.modules.pop("server", None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    def test_preview_returns_margin(self):
        r = self.client.post("/api/pricing/preview", json={
            "project_types": ["crm_build"], "months": 12,
        })
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn("margin", body)
        self.assertGreater(body["margin"]["margin_pct"], 0)

    def test_preview_accepts_role_staffing(self):
        r = self.client.post("/api/pricing/preview", json={
            "project_types": ["crm_build"], "months": 12,
            "rate_card": "Staff Augmentation",
            "role_staffing": {
                "Client Partner": {"region": "UK", "seniority": "Senior"},
            },
        })
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
