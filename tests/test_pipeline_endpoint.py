"""v1.0.0dq — /api/pipeline endpoint behaviour.

Focus: the Notion-failure path. Previously /api/pipeline hard-502'd on a
NotionSyncError while /api/dashboard degraded gracefully to 200. v1.0.0dq
unifies them — the pipeline now returns 200 with an empty list plus an
explicit notion_unavailable flag + warning so the SPA can show a banner
instead of blacking out the view (and an empty pipeline is never silently
mistaken for "no leads").
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class PipelineEndpointTests(unittest.TestCase):
    def setUp(self):
        self._env_set: dict[str, str | None] = {}
        for k, v in {
            "SKIP_NOTION_BOOT": "1",
            "SKIP_COMMAND_CENTRE_SEED": "1",
        }.items():
            self._env_set[k] = os.environ.get(k)
            os.environ[k] = v
        sys.modules.pop("server", None)
        import server
        self.server = server
        self.client = server.app.test_client()

    def tearDown(self):
        for k, original in self._env_set.items():
            if original is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = original

    def _mock_notion_sync(self, *, list_pipeline_return=None,
                          list_pipeline_side_effect=None):
        fake_instance = mock.MagicMock()
        if list_pipeline_side_effect is not None:
            fake_instance.list_pipeline.side_effect = list_pipeline_side_effect
        else:
            fake_instance.list_pipeline.return_value = list_pipeline_return or []
        return mock.patch.object(self.server, "NotionSync",
                                 return_value=fake_instance)

    def test_pipeline_returns_rows_on_success(self):
        rows = [{"id": "acme", "company": "Acme", "status": "Qualified"}]
        with self._mock_notion_sync(list_pipeline_return=rows):
            r = self.client.get("/api/pipeline?limit=10")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["rows"][0]["company"], "Acme")
        # Healthy responses carry no outage flag.
        self.assertNotIn("notion_unavailable", data)

    def test_pipeline_degrades_gracefully_on_notion_error(self):
        from notion_sync import NotionSyncError
        with self._mock_notion_sync(
            list_pipeline_side_effect=NotionSyncError("502 from Notion")
        ):
            r = self.client.get("/api/pipeline")
        # 200 (not 502): view stays renderable, mirroring /api/dashboard.
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["rows"], [])
        self.assertEqual(data["count"], 0)
        self.assertTrue(data["notion_unavailable"])
        self.assertIn("Live pipeline data unavailable", data["warning"])

    def test_pipeline_csv_export_fails_loudly_on_notion_error(self):
        # Deliberate exception: a download must NOT hand back an empty CSV
        # dressed up as success, so the CSV route keeps its honest 502.
        from notion_sync import NotionSyncError
        with self._mock_notion_sync(
            list_pipeline_side_effect=NotionSyncError("502 from Notion")
        ):
            r = self.client.get("/api/pipeline/export.csv")
        self.assertEqual(r.status_code, 502)


if __name__ == "__main__":
    unittest.main()
