"""v0.10.0j — BANT-S health rollup from MEDDPICC + scope."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bant_health


class WorstHelperTests(unittest.TestCase):
    def test_red_beats_amber_beats_green(self):
        self.assertEqual(bant_health._worst("green", "amber", "red"), "red")
        self.assertEqual(bant_health._worst("green", "amber"), "amber")
        self.assertEqual(bant_health._worst("green", "green"), "green")

    def test_none_is_lowest(self):
        self.assertIsNone(bant_health._worst(None, None))
        self.assertEqual(bant_health._worst(None, "green"), "green")
        self.assertEqual(bant_health._worst(None, "red"), "red")

    def test_invalid_values_ignored(self):
        self.assertIsNone(bant_health._worst("blue", "purple"))
        self.assertEqual(bant_health._worst("blue", "amber"), "amber")


class ScopeHealthTests(unittest.TestCase):
    def test_empty_scope_is_red(self):
        h, c = bant_health._scope_health({})
        self.assertEqual(h, "red")
        self.assertIn("Not defined", c)

    def test_no_scope_state_returns_none(self):
        h, c = bant_health._scope_health(None)
        self.assertIsNone(h)

    def test_free_text_only_is_amber(self):
        h, c = bant_health._scope_health({"project_scope": "Build CDP + 25 campaigns"})
        self.assertEqual(h, "amber")
        self.assertIn("free text", c.lower())

    def test_drafted_streams_no_validation_is_amber(self):
        h, c = bant_health._scope_health({
            "streams": [{"project_type": "crm_build", "validation_status": "draft"}],
        })
        self.assertEqual(h, "amber")
        self.assertIn("1 stream", c)

    def test_validated_stream_is_green(self):
        h, c = bant_health._scope_health({
            "streams": [
                {"project_type": "crm_build", "validation_status": "validated"},
                {"project_type": "data_work", "validation_status": "draft"},
            ],
        })
        self.assertEqual(h, "green")
        self.assertIn("1/2", c)


class DeriveBantHealthTests(unittest.TestCase):
    def test_empty_meddpicc_returns_all_none(self):
        out = bant_health.derive_bant_health({})
        for tile in ("budget", "authority", "need", "timeline"):
            self.assertIsNone(out[tile]["health"])

    def test_authority_pulls_from_economic_buyer(self):
        out = bant_health.derive_bant_health({
            "economic_buyer": {"value": "Jane Doe, CFO", "health": "green"},
        })
        self.assertEqual(out["authority"]["health"], "green")
        self.assertEqual(out["authority"]["caption"], "Jane Doe, CFO")

    def test_budget_pulls_from_budget_confirmed(self):
        out = bant_health.derive_bant_health({
            "budget_confirmed": {"value": "£500k approved FY26", "health": "green"},
        })
        self.assertEqual(out["budget"]["health"], "green")
        self.assertIn("500k", out["budget"]["caption"])

    def test_need_is_worst_of_pain_and_metrics(self):
        # pain red, metrics green → need red
        out = bant_health.derive_bant_health({
            "identify_pain": {"value": "vague", "health": "red"},
            "metrics":       {"value": "5pp uplift", "health": "green"},
        })
        self.assertEqual(out["need"]["health"], "red")

    def test_need_amber_when_pain_amber_metrics_none(self):
        out = bant_health.derive_bant_health({
            "identify_pain": {"value": "loose pain", "health": "amber"},
        })
        self.assertEqual(out["need"]["health"], "amber")

    def test_timeline_from_decision_process(self):
        out = bant_health.derive_bant_health({
            "decision_process": {"value": "Q3 board sign-off", "health": "amber"},
        })
        self.assertEqual(out["timeline"]["health"], "amber")
        self.assertIn("Q3", out["timeline"]["caption"])

    def test_scope_derived_from_scope_state_not_meddpicc(self):
        out = bant_health.derive_bant_health(
            {"economic_buyer": {"value": "CFO", "health": "green"}},
            scope_state={"streams": [{"validation_status": "validated"}]},
        )
        self.assertEqual(out["scope"]["health"], "green")

    def test_default_caption_when_no_value(self):
        out = bant_health.derive_bant_health({
            "economic_buyer": {"health": "amber"},  # no value
        })
        self.assertEqual(out["authority"]["caption"], "Needs work")

    def test_captions_truncated_to_60_chars(self):
        long_val = "x" * 200
        out = bant_health.derive_bant_health({
            "identify_pain": {"value": long_val, "health": "green"},
        })
        self.assertEqual(len(out["need"]["caption"]), 60)


class OverallScoreTests(unittest.TestCase):
    def test_all_green_overall_green(self):
        bant = bant_health.derive_bant_health({
            "budget_confirmed":  {"health": "green"},
            "economic_buyer":    {"health": "green"},
            "identify_pain":     {"health": "green"},
            "decision_process":  {"health": "green"},
        }, scope_state={"streams": [{"validation_status": "validated"}]})
        agg = bant_health.overall_score(bant)
        self.assertEqual(agg["worst"], "green")
        self.assertEqual(agg["counts"]["green"], 5)

    def test_one_red_drags_overall_to_red(self):
        bant = bant_health.derive_bant_health({
            "budget_confirmed":  {"health": "green"},
            "economic_buyer":    {"health": "green"},
            "identify_pain":     {"health": "red"},
            "decision_process":  {"health": "green"},
        }, scope_state={"streams": [{"validation_status": "validated"}]})
        agg = bant_health.overall_score(bant)
        self.assertEqual(agg["worst"], "red")

    def test_all_unassessed_returns_none(self):
        bant = bant_health.derive_bant_health({})
        agg = bant_health.overall_score(bant)
        self.assertIsNone(agg["worst"])


if __name__ == "__main__":
    unittest.main()
