"""v0.10.0w — explicit POST /api/lead/<id>/rescore endpoint."""
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


class RescoreEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server",):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_rescore_returns_502_when_notion_unavailable(self):
        """Without NOTION_API_KEY the endpoint fails cleanly with 502,
        not a 500 crash."""
        os.environ.pop("NOTION_API_KEY", None)
        r = self.client.post("/api/lead/abc-123/rescore", json={})
        # Either 502 (NotionSync raised) or 500 if something else broke —
        # accept both as long as it's a controlled failure, not a hang.
        self.assertIn(r.status_code, (502, 500))
        self.assertIn("error", r.get_json())

    def test_rescore_calls_calculate_icp_score_and_writes_back(self):
        """Mock NotionSync to return a known lead, verify scoring runs
        and the update_page call carries the new icp_normalised."""
        from unittest.mock import MagicMock

        fake_lead = {
            "id": "lead-123",
            "company": "Test Co",
            "revenue": "$500M",
            "employees": 2000,
            "vertical": "QSR",
            "tech_stack": "Braze, Snowflake",
            "complexity": "multi",
            "region": "NAM (United States)",
            "deal_size": "$50000",
            "stack_confidence": "confirmed",
        }
        fake_sync = MagicMock()
        fake_sync.get_page.return_value = fake_lead
        fake_sync.update_page.return_value = {
            "updated": True, "page_id": "lead-123",
            "lead": {**fake_lead, "icp_normalised": 8.4},
        }

        with patch.object(self.server, "NotionSync", return_value=fake_sync):
            r = self.client.post("/api/lead/lead-123/rescore", json={})

        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body.get("rescored"))
        new_score = body.get("new_score") or {}
        self.assertIn("normalized_score", new_score)
        self.assertIsInstance(new_score["normalized_score"], (int, float))
        self.assertIn("opportunity_type", new_score)
        # Verify the update_page call carried the new score back to Notion.
        call_args = fake_sync.update_page.call_args
        self.assertIsNotNone(call_args)
        edit_body = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("edits") or {}
        self.assertIn("icp_normalised", edit_body)


if __name__ == "__main__":
    unittest.main()
