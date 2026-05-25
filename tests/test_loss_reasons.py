"""v1.0.0cc — /api/dashboard/loss-reasons aggregation tests.

After v1.0.0ca added close_reason capture on Closed Lost / Rejected
leads, this endpoint buckets them so the team can see recurring
loss patterns over time.
"""
from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class LossReasonsEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        sys.modules.pop("server", None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("SKIP_COMMAND_CENTRE_SEED", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _fetch(self, rows, limit=None):
        with patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.list_pipeline.return_value = rows
            qs = f"?limit={limit}" if limit else ""
            r = self.client.get(f"/api/dashboard/loss-reasons{qs}")
        self.assertEqual(r.status_code, 200)
        return r.get_json()

    def test_empty_pipeline(self):
        body = self._fetch([])
        self.assertEqual(body["reasons"], [])
        self.assertEqual(body["totals"]["closed_count"], 0)

    def test_only_closed_leads_count(self):
        """Active leads (not Nurture / Rejected) shouldn't enter the
        aggregation at all."""
        body = self._fetch([
            {"id": "1", "company": "Active Co", "status": "Qualified",
              "close_reason": "should be ignored"},
            {"id": "2", "company": "Nurture Co", "status": "Nurture",
              "close_reason": "Budget pulled"},
            {"id": "3", "company": "Rejected Co", "status": "Rejected",
              "close_reason": "Not a fit"},
        ])
        self.assertEqual(body["totals"]["closed_count"], 2)
        # Only nurture + rejected reasons buckets.
        self.assertEqual(body["totals"]["with_reason"], 2)
        self.assertEqual(len(body["reasons"]), 2)

    def test_buckets_by_reason_case_insensitive(self):
        """Same reason in different casing should collapse to one
        bucket. Display preserves the first-seen casing."""
        body = self._fetch([
            {"id": "1", "company": "A", "status": "Nurture",
              "close_reason": "Budget pulled"},
            {"id": "2", "company": "B", "status": "Nurture",
              "close_reason": "budget pulled"},  # lowercased
            {"id": "3", "company": "C", "status": "Nurture",
              "close_reason": " BUDGET   PULLED "},  # whitespace + caps
            {"id": "4", "company": "D", "status": "Nurture",
              "close_reason": "Picked competitor"},
        ])
        self.assertEqual(body["totals"]["closed_count"], 4)
        # Two buckets: Budget pulled (3) + Picked competitor (1).
        self.assertEqual(len(body["reasons"]), 2)
        top = body["reasons"][0]
        self.assertEqual(top["count"], 3)

    def test_reasons_sorted_by_count_desc(self):
        body = self._fetch([
            {"id": "1", "company": "X", "status": "Nurture",
              "close_reason": "Single"},
            {"id": "2", "company": "Y1", "status": "Nurture",
              "close_reason": "Triple"},
            {"id": "3", "company": "Y2", "status": "Nurture",
              "close_reason": "Triple"},
            {"id": "4", "company": "Y3", "status": "Nurture",
              "close_reason": "Triple"},
            {"id": "5", "company": "Z1", "status": "Nurture",
              "close_reason": "Double"},
            {"id": "6", "company": "Z2", "status": "Nurture",
              "close_reason": "Double"},
        ])
        counts = [r["count"] for r in body["reasons"]]
        self.assertEqual(counts, [3, 2, 1])

    def test_missing_reason_counted_separately(self):
        body = self._fetch([
            {"id": "1", "company": "WithReason", "status": "Nurture",
              "close_reason": "Cited"},
            {"id": "2", "company": "Blank", "status": "Nurture",
              "close_reason": ""},
            {"id": "3", "company": "Null", "status": "Nurture",
              "close_reason": None},
        ])
        self.assertEqual(body["totals"]["closed_count"], 3)
        self.assertEqual(body["totals"]["with_reason"], 1)
        self.assertEqual(body["totals"]["without_reason"], 2)
        self.assertEqual(len(body["reasons"]), 1)

    def test_limit_caps_reasons(self):
        """Endpoint accepts ?limit=N and clamps to 1..50."""
        rows = []
        for i in range(20):
            rows.append({"id": str(i), "company": f"Co {i}",
                          "status": "Nurture",
                          "close_reason": f"Reason {i}"})
        body = self._fetch(rows, limit=5)
        self.assertEqual(len(body["reasons"]), 5)

    def test_lead_preview_capped_at_5(self):
        """Each reason bucket exposes at most 5 leads in the preview."""
        rows = []
        for i in range(8):
            rows.append({"id": str(i), "company": f"Co {i}",
                          "status": "Nurture",
                          "close_reason": "Same Reason"})
        body = self._fetch(rows)
        self.assertEqual(body["reasons"][0]["count"], 8)
        self.assertEqual(len(body["reasons"][0]["leads"]), 5)

    def test_notion_outage_returns_empty(self):
        """If Notion fails, the endpoint returns an empty result
        rather than 500."""
        with patch.object(self.server, "NotionSync",
                            side_effect=RuntimeError("Notion down")):
            r = self.client.get("/api/dashboard/loss-reasons")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["reasons"], [])
        self.assertEqual(body["totals"]["closed_count"], 0)


if __name__ == "__main__":
    unittest.main()
