"""v1.0.0dv - code-review hardening of the scoring / opportunity path.

Covers two findings from the platform code review:
1. classify_opportunity_type can return "retention_light", but that type
   had no entry in OPPORTUNITY_TYPES, so its "play" came back blank.
2. A hard disqualifier did not override the numeric status, so a
   high-scoring but disqualified lead synced to Notion as "Qualified".
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import scoring  # noqa: E402
import qualify_service  # noqa: E402


class OpportunityMetadataTests(unittest.TestCase):
    def test_retention_light_has_metadata(self):
        self.assertIn("retention_light", config.OPPORTUNITY_TYPES)
        meta = config.OPPORTUNITY_TYPES["retention_light"]
        self.assertTrue(meta["label"])
        self.assertTrue(meta["play"])
        self.assertTrue(meta["description"])

    def test_opportunity_play_nonempty_for_every_type(self):
        """Every opportunity type defined in config must resolve to a
        non-empty play, so the UI / Notion never show a blank play."""
        for opp_type in config.OPPORTUNITY_TYPES:
            self.assertTrue(
                qualify_service._opportunity_play(opp_type),
                f"{opp_type} resolved to a blank play",
            )

    def test_retention_light_play_resolves(self):
        self.assertTrue(qualify_service._opportunity_play("retention_light"))


class HardDisqualifierStatusTests(unittest.TestCase):
    def test_forces_qualify_out_over_high_score(self):
        score = {"status": "qualify_in", "status_display": "QUALIFY IN"}
        scoring.apply_hard_disqualifier_status(score, ["Revenue under $50M"])
        self.assertEqual(score["status"], "qualify_out")
        self.assertEqual(score["status_display"],
                          config.QUALIFICATION_STATUS["qualify_out"])
        self.assertTrue(score["status_forced_by_disqualifier"])

    def test_noop_without_disqualifiers(self):
        score = {"status": "qualify_in", "status_display": "QUALIFY IN"}
        scoring.apply_hard_disqualifier_status(score, [])
        self.assertEqual(score["status"], "qualify_in")
        self.assertNotIn("status_forced_by_disqualifier", score)

    def test_noop_when_already_qualify_out(self):
        score = {"status": "qualify_out", "status_display": "QUALIFY OUT"}
        scoring.apply_hard_disqualifier_status(score, ["Revenue under $50M"])
        # No spurious "forced" flag when the score already disqualified.
        self.assertNotIn("status_forced_by_disqualifier", score)


if __name__ == "__main__":
    unittest.main()
