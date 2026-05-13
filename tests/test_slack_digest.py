"""Slack digest builder tests. No network calls."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import slack_digest  # noqa: E402


PIPELINE_FIXTURE = [
    {"company": "Yum! Brands", "icp_normalised": 9.2, "status": "Qualified", "sales_stage": "Proposal"},
    {"company": "RBI", "icp_normalised": 8.8, "status": "Qualified", "sales_stage": "Discovery"},
    {"company": "IHG", "icp_normalised": 8.6, "status": "Qualified", "sales_stage": "Intro Call"},
    {"company": "Just Eat", "icp_normalised": 8.4, "status": "Qualified", "sales_stage": "Discovery"},
    {"company": "Monzo", "icp_normalised": 7.1, "status": "Qualified", "sales_stage": "Intro Call"},
    {"company": "GoPuff", "icp_normalised": 6.5, "status": "Researching", "sales_stage": None},
    {"company": "Murphy", "icp_normalised": 5.9, "status": "Researching", "sales_stage": None},
]

AUDIT_FIXTURE = [
    {"ts": "2026-05-13T10:00:00Z", "type": "qualified", "company": "Yum! Brands", "status": "qualify_in", "score": 9.2},
    {"ts": "2026-05-13T11:00:00Z", "type": "qualified", "company": "Murphy", "status": "borderline", "score": 5.9},
    {"ts": "2026-05-13T11:30:00Z", "type": "notion_sync", "company": "Yum! Brands", "action": "created"},
    {"ts": "2026-05-13T12:00:00Z", "type": "qualified", "company": "GoPuff", "status": "borderline", "score": 6.5},
    {"ts": "2026-05-13T13:00:00Z", "type": "notion_sync", "company": "GoPuff", "action": "created"},
]


class BuildDigestTests(unittest.TestCase):
    def test_payload_has_blocks(self):
        p = slack_digest.build_digest(
            pipeline_rows=PIPELINE_FIXTURE,
            audit_events=AUDIT_FIXTURE,
        )
        self.assertIn("blocks", p)
        self.assertGreater(len(p["blocks"]), 0)
        self.assertEqual(p["blocks"][0]["type"], "header")

    def test_summary_counts(self):
        p = slack_digest.build_digest(
            pipeline_rows=PIPELINE_FIXTURE,
            audit_events=AUDIT_FIXTURE,
        )
        # Flatten all text to a single string for assertion convenience.
        flat = ""
        for b in p["blocks"]:
            if b.get("type") == "section":
                if "text" in b:
                    flat += b["text"].get("text", "") + "\n"
                for f in b.get("fields", []):
                    flat += f.get("text", "") + "\n"
        self.assertIn("Pipeline size:* 7", flat)
        self.assertIn("Qualified In:* 1", flat)
        self.assertIn("Borderline:* 2", flat)
        self.assertIn("Notion syncs:* 2", flat)

    def test_top_5_in_score_order(self):
        p = slack_digest.build_digest(
            pipeline_rows=PIPELINE_FIXTURE,
            audit_events=AUDIT_FIXTURE,
        )
        section = next(b for b in p["blocks"]
                       if b.get("type") == "section"
                       and "text" in b
                       and "Top 5 by ICP" in (b["text"].get("text") or ""))
        text = section["text"]["text"]
        # Yum first, RBI second, IHG third by score
        self.assertLess(text.index("Yum"), text.index("RBI"))
        self.assertLess(text.index("RBI"), text.index("IHG"))

    def test_send_without_webhook_returns_unsent(self):
        original = os.environ.pop("SLACK_WEBHOOK_URL", None)
        try:
            r = slack_digest.send_digest({"blocks": []})
            self.assertFalse(r["sent"])
            self.assertIn("SLACK_WEBHOOK_URL", r["reason"])
        finally:
            if original is not None:
                os.environ["SLACK_WEBHOOK_URL"] = original

    def test_is_configured(self):
        original = os.environ.pop("SLACK_WEBHOOK_URL", None)
        try:
            self.assertFalse(slack_digest.is_configured())
            os.environ["SLACK_WEBHOOK_URL"] = "https://hooks.slack.com/services/AAA/BBB/CCC"
            self.assertTrue(slack_digest.is_configured())
        finally:
            os.environ.pop("SLACK_WEBHOOK_URL", None)
            if original is not None:
                os.environ["SLACK_WEBHOOK_URL"] = original


if __name__ == "__main__":
    unittest.main()
