"""v0.8 — rate cards, packages, multi-currency pricing."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class RateCardLookupTests(unittest.TestCase):
    def test_mr_default_three_currencies(self):
        import rate_cards
        self.assertEqual(rate_cards.rate_lookup("MR Default", "AnyRole", "USD"),
                         {"hourly": 200, "daily": 1600})
        self.assertEqual(rate_cards.rate_lookup("MR Default", "AnyRole", "GBP"),
                         {"hourly": 150, "daily": 1200})
        self.assertEqual(rate_cards.rate_lookup("MR Default", "AnyRole", "EUR"),
                         {"hourly": 175, "daily": 1400})

    def test_yum_thailand_blended(self):
        import rate_cards
        # Yum Thailand applies to all roles, much lower than default
        r = rate_cards.rate_lookup("Yum Thailand!", "CRM Consultant", "USD")
        self.assertEqual(r["hourly"], 105)

    def test_yum_small_markets_applies_only_to_listed_roles(self):
        import rate_cards
        # Onboarding Consultant gets the discounted rate
        r = rate_cards.rate_lookup("Yum! Small Markets", "Onboarding Consultant", "USD")
        self.assertEqual(r["hourly"], 42)
        # Other roles fall back to MR Default
        r2 = rate_cards.rate_lookup("Yum! Small Markets", "CRM Architect", "USD")
        self.assertEqual(r2["hourly"], 200)

    def test_staff_aug_needs_region_and_seniority(self):
        import rate_cards
        # Without region/seniority: returns None
        self.assertIsNone(
            rate_cards.rate_lookup("Staff Augmentation", "CRM Consultant", "USD"))
        # With them: returns the specific rate
        r = rate_cards.rate_lookup("Staff Augmentation", "CRM Consultant",
                                    "USD", region="UK", seniority="Senior")
        self.assertEqual(r["hourly"], 130)

    def test_staff_aug_india_discount(self):
        import rate_cards
        r = rate_cards.rate_lookup("Staff Augmentation", "Data Engineer (Snowflake)",
                                    "USD", region="India", seniority="Senior")
        self.assertEqual(r["hourly"], 91)
        r_uk = rate_cards.rate_lookup("Staff Augmentation", "Data Engineer (Snowflake)",
                                       "USD", region="UK", seniority="Senior")
        self.assertGreater(r_uk["hourly"], r["hourly"], "UK should cost more than India")

    def test_blended_rate_helper(self):
        import rate_cards
        self.assertEqual(rate_cards.blended_rate("MR Default", "USD"), 200)
        self.assertEqual(rate_cards.blended_rate("MR Default", "GBP"), 150)
        self.assertEqual(rate_cards.blended_rate("Yum Thailand!", "USD"), 105)

    def test_list_cards_includes_all(self):
        import rate_cards
        cards = rate_cards.all_cards()
        self.assertIn("MR Default", cards)
        self.assertIn("Staff Augmentation", cards)
        self.assertIn("Yum! Small Markets", cards)
        self.assertIn("Yum Thailand!", cards)

    def test_unknown_currency_returns_none(self):
        import rate_cards
        self.assertIsNone(rate_cards.rate_lookup("MR Default", "X", "JPY"))


class PackagesTests(unittest.TestCase):
    def test_30_plus_packages_defined(self):
        import packages
        rows = packages.list_packages()
        self.assertGreaterEqual(len(rows), 30)

    def test_known_packages_have_expected_hours(self):
        import packages
        # From the source spreadsheet
        self.assertEqual(packages.get_package("Light Audit")["total_hours"], 43)
        self.assertEqual(packages.get_package("Audit/Inception")["total_hours"], 86)
        self.assertEqual(packages.get_package("Customer 360")["total_hours"], 230)
        self.assertEqual(packages.get_package("CDP Setup")["total_hours"], 276)
        self.assertEqual(packages.get_package("[Large] Braze Operations")["total_hours"], 169)

    def test_package_components_have_role_and_hours(self):
        import packages
        for key, pkg in packages.PACKAGES.items():
            for c in pkg["components"]:
                self.assertIn("role", c, f"{key} component missing role")
                self.assertIn("hours", c, f"{key} component missing hours")
                self.assertGreaterEqual(c["hours"], 0)

    def test_unknown_package_returns_none(self):
        import packages
        self.assertIsNone(packages.get_package("Not a real package"))


class PricingV08Tests(unittest.TestCase):
    """v0.8 additions: currency, rate card, project ops, contingency."""

    def test_default_quote_unchanged_from_v04(self):
        """Backward-compat: ref deal still produces $1.19M / $1.11M."""
        from pricing import compute_quote, QuoteInputs
        q = compute_quote(QuoteInputs(project_types=["crm_build"], months=12))
        self.assertEqual(q["totals"]["gross_usd"], 1_191_360)
        self.assertEqual(q["inputs"]["currency"], "USD")
        self.assertEqual(q["inputs"]["rate_card"], "MR Default")

    def test_gbp_currency_uses_gbp_rates(self):
        """Switching to GBP returns figures at £150/h."""
        from pricing import compute_quote, QuoteInputs
        q = compute_quote(QuoteInputs(project_types=["crm_build"], months=12,
                                       currency="GBP"))
        # GBP rate is £150 vs $200 — gross should be 150/200 = 75% of USD
        usd_q = compute_quote(QuoteInputs(project_types=["crm_build"], months=12))
        self.assertAlmostEqual(
            q["totals"]["gross_usd"] / usd_q["totals"]["gross_usd"],
            150 / 200, places=4,
        )

    def test_project_ops_uplift_applied(self):
        from pricing import compute_quote, QuoteInputs
        base = compute_quote(QuoteInputs(project_types=["crm_build"], months=12))
        with_ops = compute_quote(QuoteInputs(project_types=["crm_build"], months=12,
                                             project_ops_pct=0.10))
        # 10% ops uplift adds ~$119k to a $1.19M gross
        self.assertAlmostEqual(with_ops["totals"]["ops_usd"],
                                base["totals"]["gross_usd"] * 0.10, delta=1)
        self.assertGreater(with_ops["totals"]["net_usd"], base["totals"]["net_usd"])

    def test_contingency_applies_on_gross_plus_ops(self):
        from pricing import compute_quote, QuoteInputs
        q = compute_quote(QuoteInputs(
            project_types=["crm_build"], months=12,
            project_ops_pct=0.10,
            contingency_pct=0.05,
        ))
        # contingency = (gross + ops) × 0.05
        expected = (q["totals"]["gross_usd"] + q["totals"]["ops_usd"]) * 0.05
        self.assertAlmostEqual(q["totals"]["contingency_usd"], expected, delta=1)

    def test_yum_thailand_rate_card_produces_lower_price(self):
        from pricing import compute_quote, QuoteInputs
        default_q = compute_quote(QuoteInputs(project_types=["crm_build"], months=12))
        thailand_q = compute_quote(QuoteInputs(project_types=["crm_build"], months=12,
                                                rate_card="Yum Thailand!"))
        self.assertLess(thailand_q["totals"]["net_usd"], default_q["totals"]["net_usd"])

    def test_no_ops_no_contingency_no_change_to_net(self):
        from pricing import compute_quote, QuoteInputs
        base = compute_quote(QuoteInputs(project_types=["crm_build"], months=12))
        explicit_zero = compute_quote(QuoteInputs(
            project_types=["crm_build"], months=12,
            project_ops_pct=0.0, contingency_pct=0.0,
        ))
        self.assertEqual(base["totals"]["net_usd"], explicit_zero["totals"]["net_usd"])


if __name__ == "__main__":
    unittest.main()
