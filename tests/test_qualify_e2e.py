"""End-to-end smoke test against the Apollo fixture.

Run with:
    APOLLO_USE_FIXTURES=1 python -m unittest tests.test_qualify_e2e
or:
    APOLLO_USE_FIXTURES=1 python -m pytest tests/test_qualify_e2e.py
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

# Make repo root importable when run from a checkout
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("APOLLO_USE_FIXTURES", "1")

from qualify_service import qualify  # noqa: E402
from notion_sync import _payload_to_properties  # noqa: E402


class DeliverooFixtureTests(unittest.TestCase):
    """The brief's end-to-end test: Deliveroo lands as a high-scoring retention lead."""

    @classmethod
    def setUpClass(cls):
        cls.result = qualify("Deliveroo", "deliveroo.co.uk")

    def test_discovery_populated_from_apollo(self):
        d = self.result["discovered"]
        self.assertEqual(d["revenue"], "$2.4B")
        self.assertEqual(d["employees"], 4200)
        self.assertEqual(d["region"], "EMEA (United Kingdom)")
        self.assertIn("Braze", d["tech_stack"])
        self.assertIn("Snowflake", d["tech_stack"])

    def test_score_qualifies_in(self):
        s = self.result["score"]
        self.assertGreaterEqual(s["normalized_score"], 7.0, "Should clear qualify-in threshold")
        self.assertEqual(s["status"], "qualify_in")
        self.assertEqual(s["opportunity_type"], "retention")

    def test_signals_capture_braze_snowflake(self):
        signals = self.result["signals"]
        self.assertTrue(
            any("Braze + Snowflake" in s for s in signals),
            f"Expected Braze + Snowflake signal; got {signals}",
        )

    def test_no_hard_disqualifiers(self):
        self.assertEqual(self.result["disqualifiers"], [])

    def test_discovered_carries_stack_confidence(self):
        """v1.0.0dv: stack_confidence must flow into the discovered payload
        so Notion records the real confidence instead of defaulting to
        'Confirmed'."""
        self.assertIn("stack_confidence", self.result["discovered"])

    def test_hard_disqualifier_forces_qualify_out(self):
        """v1.0.0dv: a hard disqualifier is an automatic Qualify Out, even
        when the numeric score would otherwise qualify the lead. Without
        this the lead synced to Notion as 'Qualified'."""
        r = qualify("Deliveroo", "deliveroo.co.uk", overrides={"employees": "100"})
        self.assertTrue(r["disqualifiers"], "expected an employee-count disqualifier")
        self.assertEqual(r["score"]["status"], "qualify_out")
        self.assertTrue(r["score"].get("status_forced_by_disqualifier"))

    def test_stakeholders_returned(self):
        self.assertGreaterEqual(len(self.result["stakeholders"]), 1)
        first = self.result["stakeholders"][0]
        for key in ("name", "title", "priority", "why"):
            self.assertIn(key, first)

    def test_overrides_take_precedence(self):
        overridden = qualify("Deliveroo", "deliveroo.co.uk", overrides={
            "tech_stack": "Salesforce Marketing Cloud, Databricks",
            "stack_confidence": "confirmed",
        })
        self.assertEqual(overridden["score"]["opportunity_type"], "migration")

    def test_fit_summary_source_is_heuristic_without_ai(self):
        original = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            r = qualify("Deliveroo", "deliveroo.co.uk")
            self.assertEqual(r["fit_summary_source"], "heuristic")
            self.assertTrue(r["fit_summary"])
        finally:
            if original is not None:
                os.environ["ANTHROPIC_API_KEY"] = original

    def test_ai_summary_module_handles_missing_key(self):
        import ai_summary
        original = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            self.assertFalse(ai_summary.is_configured())
            self.assertIsNone(ai_summary.generate_fit_summary(self.result))
        finally:
            if original is not None:
                os.environ["ANTHROPIC_API_KEY"] = original

    def test_notion_property_mapping_runs(self):
        """The Notion adapter should produce a properties dict without crashing."""
        props = _payload_to_properties(self.result)
        self.assertEqual(props["Company"]["title"][0]["text"]["content"], "Deliveroo")
        self.assertIn("ICP Normalised", props)
        self.assertIn("Status", props)
        self.assertIn("Tech Stack", props)
        # Don't assume a specific status text — assert it's a select with a name.
        self.assertIn("name", props["Status"]["select"])


class StubModeTests(unittest.TestCase):
    """When fixtures mode is on and no fixture exists for a domain, qualify still returns."""

    def test_unknown_domain_returns_stub(self):
        result = qualify("Nowhere Co", "no-such-company-domain-xyz.example")
        self.assertTrue(result["discovered"]["stub"])
        # Still produces a score (the scoring engine handles missing data).
        self.assertIn("normalized_score", result["score"])


if __name__ == "__main__":
    unittest.main()
