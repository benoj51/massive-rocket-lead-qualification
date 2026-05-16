"""
Pricing calculator tests — anchored to the reference Summary Sheet ($1.11M
12-month CRM Build deal). The crm_build template + role rates here are
calibrated against that CSV; if anyone bumps a rate or an FTE without
intent, these tests catch it.

Tolerance: ±1% on totals. The CSV has a deal-specific mid-Execute ramp
for CRM Architect that we model as the phase average; that produces a
small discount drift (~$1.8k on a $1.1M deal) that's not worth uglifying
the data model to eliminate.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pricing import (  # noqa: E402
    QuoteInputs,
    ROLE_RATES_USD_PER_HOUR,
    compute_quote,
    role_catalogue,
    list_team_templates,
)


# Reference numbers come from
# "Pricing Calculator (New) - [External] Summary Sheet (1).csv"
REFERENCE_GROSS_USD = 1_191_360
REFERENCE_DISCOUNT_USD = 79_344
REFERENCE_NET_USD = 1_112_016
REFERENCE_HOURS = 5_957


class ReferenceDealTests(unittest.TestCase):
    """The 12-month CRM Build deal from the Summary Sheet."""

    @classmethod
    def setUpClass(cls):
        cls.quote = compute_quote(QuoteInputs(
            project_types=["crm_build"],
            months=12,
            discount_pct_first_half=0.15,
            discount_pct_second_half=0.0,
        ))

    def test_gross_total_matches_csv_exactly(self):
        self.assertEqual(self.quote["totals"]["gross_usd"], REFERENCE_GROSS_USD)

    def test_net_total_within_one_percent_of_csv(self):
        net = self.quote["totals"]["net_usd"]
        delta = abs(net - REFERENCE_NET_USD)
        self.assertLess(delta / REFERENCE_NET_USD, 0.01,
                        f"Net {net} drifted >1% from CSV {REFERENCE_NET_USD}")

    def test_hours_total_matches_csv(self):
        # CSV reports 5,957; our 160h/FTE-month assumption + the phase mix
        # produces the same hour count if templates are calibrated.
        self.assertAlmostEqual(self.quote["totals"]["hours"], REFERENCE_HOURS, delta=10)

    def test_understand_phase_monthly_gross(self):
        # CSV: $80,640 per Understand month
        understand_months = [m for m in self.quote["monthly"] if m["phase"] == "Understand"]
        self.assertEqual(len(understand_months), 3)
        for m in understand_months:
            self.assertEqual(m["gross_usd"], 80_640)

    def test_accelerate_phase_monthly_gross(self):
        # CSV: $117,120 per Accelerate month
        accelerate_months = [m for m in self.quote["monthly"] if m["phase"] == "Accelerate"]
        self.assertEqual(len(accelerate_months), 3)
        for m in accelerate_months:
            self.assertEqual(m["gross_usd"], 117_120)

    def test_blended_rate_close_to_csv(self):
        # CSV reports £187/USD as the blended rate; our net/hours derivation
        # should be in the same neighbourhood.
        blended = self.quote["totals"]["blended_rate_usd_per_hour"]
        self.assertAlmostEqual(blended, 187, delta=5)

    def test_discount_only_on_first_half(self):
        for m in self.quote["monthly"]:
            if m["month"] <= 6:
                self.assertEqual(m["discount_pct"], 0.15, f"Month {m['month']} should be discounted")
            else:
                self.assertEqual(m["discount_pct"], 0.0, f"Month {m['month']} should not be discounted")


class RoleCatalogueTests(unittest.TestCase):
    def test_single_blended_rate(self):
        # MR's client-facing model uses one blended USD/hour rate across all
        # roles. If a role's rate diverges, internal cost accounting moved.
        rates = set(ROLE_RATES_USD_PER_HOUR.values())
        self.assertEqual(len(rates), 1, f"Expected single blended rate; got {rates}")
        self.assertIn(200, rates)

    def test_catalogue_export_shape(self):
        cat = role_catalogue()
        for role, info in cat.items():
            self.assertIn("rate_usd_per_hour", info)
            self.assertIn(info["tier"], ("A", "B"))

    def test_templates_only_reference_known_roles(self):
        known = set(ROLE_RATES_USD_PER_HOUR.keys())
        for template_name, roles in list_team_templates().items():
            for role in roles:
                self.assertIn(role, known, f"Template {template_name} references unknown role {role}")


class MultiStreamTests(unittest.TestCase):
    """When a deal has CRM Build + Data Work, team templates merge by max FTE."""

    def test_multi_stream_merges_teams(self):
        single = compute_quote(QuoteInputs(project_types=["crm_build"], months=12))
        multi = compute_quote(QuoteInputs(project_types=["crm_build", "data_work"], months=12))
        # Multi-stream gross >= single-stream gross (added roles cost extra)
        self.assertGreater(multi["totals"]["gross_usd"], single["totals"]["gross_usd"])
        # And Data Architect appears in multi but not single
        self.assertIn("Data Architect", multi["team"])
        self.assertNotIn("Data Architect", single["team"])


class EffortMultiplierTests(unittest.TestCase):
    def test_multiplier_scales_role(self):
        base = compute_quote(QuoteInputs(project_types=["crm_build"], months=12))
        # 1.5x more CRM Developer effort (e.g. lots of HTML templates)
        scaled = compute_quote(QuoteInputs(
            project_types=["crm_build"], months=12,
            effort_multipliers={"CRM Developer": 1.5},
        ))
        # Net should be higher because CRM Developer is doing more work
        self.assertGreater(scaled["totals"]["gross_usd"], base["totals"]["gross_usd"])

    def test_unknown_role_multiplier_is_noop(self):
        base = compute_quote(QuoteInputs(project_types=["crm_build"], months=12))
        with_unknown = compute_quote(QuoteInputs(
            project_types=["crm_build"], months=12,
            effort_multipliers={"Made Up Role": 2.0},
        ))
        self.assertEqual(base["totals"]["gross_usd"], with_unknown["totals"]["gross_usd"])


class InputValidationTests(unittest.TestCase):
    def test_empty_project_types_raises(self):
        with self.assertRaises(ValueError):
            compute_quote(QuoteInputs(project_types=[]))


if __name__ == "__main__":
    unittest.main()
