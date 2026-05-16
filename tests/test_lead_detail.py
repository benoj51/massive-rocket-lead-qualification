"""v0.5.2: lead detail (get_page + update_page) tests."""
from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class PageToDetailTests(unittest.TestCase):
    """Notion's page shape is verbose; our flattener must extract every editable field."""

    def test_flat_dict_has_all_keys(self):
        from notion_sync import _page_to_detail
        page = {
            "id": "page-1",
            "url": "https://notion.so/page-1",
            "last_edited_time": "2026-05-15T10:00:00Z",
            "created_time": "2026-05-13T00:00:00Z",
            "properties": {
                "Company": {"type": "title",
                            "title": [{"plain_text": "Yum! Brands"}]},
                "URL": {"type": "url", "url": "https://yum.com"},
                "ICP Score": {"type": "number", "number": 48},
                "ICP Normalised": {"type": "number", "number": 9.4},
                "Status": {"type": "select", "select": {"name": "Qualified"}},
                "Sales Stage": {"type": "select", "select": {"name": "Discovery"}},
                "Vertical": {"type": "select", "select": {"name": "QSR"}},
                "Opportunity Type": {"type": "select", "select": {"name": "Retention"}},
                "Stack Confidence": {"type": "select", "select": {"name": "Confirmed"}},
                "Owner": {"type": "select", "select": {"name": "Ben Ojuolape"}},
                "Revenue": {"type": "rich_text",
                            "rich_text": [{"plain_text": "$7B"}]},
                "Employees": {"type": "rich_text",
                              "rich_text": [{"plain_text": "40,000"}]},
                "Tech Stack": {"type": "rich_text",
                               "rich_text": [{"plain_text": "Braze, Snowflake"}]},
                "Region": {"type": "rich_text",
                           "rich_text": [{"plain_text": "Global"}]},
                "Deal Size": {"type": "rich_text",
                              "rich_text": [{"plain_text": ">£50k/mo"}]},
                "Complexity": {"type": "rich_text",
                               "rich_text": [{"plain_text": "multi-brand"}]},
                "Fit Summary": {"type": "rich_text",
                                "rich_text": [{"plain_text": "Top tier QSR"}]},
                "Next Steps": {"type": "rich_text",
                               "rich_text": [{"plain_text": "Book intro"}]},
                "Positive Signals": {"type": "rich_text",
                                     "rich_text": [{"plain_text": "Braze + Snowflake"}]},
                "Disqualifiers": {"type": "rich_text", "rich_text": []},
                "Qualified Date": {"type": "date", "date": {"start": "2026-05-15"}},
            },
        }
        out = _page_to_detail(page)
        self.assertEqual(out["company"], "Yum! Brands")
        self.assertEqual(out["company_url"], "https://yum.com")
        self.assertEqual(out["status"], "Qualified")
        self.assertEqual(out["sales_stage"], "Discovery")
        self.assertEqual(out["vertical"], "QSR")
        self.assertEqual(out["opportunity_type"], "Retention")
        self.assertEqual(out["owner"], "Ben Ojuolape")
        self.assertEqual(out["revenue"], "$7B")
        self.assertEqual(out["employees"], "40,000")
        self.assertEqual(out["icp_normalised"], 9.4)
        self.assertEqual(out["icp_score"], 48)
        self.assertEqual(out["fit_summary"], "Top tier QSR")
        self.assertEqual(out["next_steps"], "Book intro")
        # Missing/empty fields shouldn't crash
        self.assertEqual(out["disqualifiers"], "")


class UpdatePagePayloadShapeTests(unittest.TestCase):
    """update_page builds the right Notion property payload from a flat dict."""

    def test_build_minimal_status_change(self):
        # Verify the property shape by patching out the HTTP call
        import notion_sync
        captured = {}

        class FakeSync(notion_sync.NotionSync):
            def __init__(self):
                self.api_key = "fake"
                self.data_source_id = "ds"
                self.database_id = ""
                self.api_version = "2025-09-03"

            def _request(self, method, path, *, json_body=None):
                captured["method"] = method
                captured["path"] = path
                captured["body"] = json_body
                return {"id": "page-1", "url": "https://notion.so/page-1",
                        "properties": {}}

        sync = FakeSync()
        sync.update_page("page-1", {"status": "qualify_in",
                                    "sales_stage": "Discovery"})
        self.assertEqual(captured["method"], "PATCH")
        self.assertEqual(captured["path"], "/pages/page-1")
        props = captured["body"]["properties"]
        self.assertEqual(props["Status"]["select"]["name"], "Qualified")
        self.assertEqual(props["Sales Stage"]["select"]["name"], "Discovery")

    def test_clearing_a_select_with_empty_string(self):
        import notion_sync
        captured = {}

        class FakeSync(notion_sync.NotionSync):
            def __init__(self):
                self.api_key = "fake"
                self.data_source_id = ""
                self.database_id = "db"
                self.api_version = "2025-09-03"

            def _request(self, method, path, *, json_body=None):
                captured["body"] = json_body
                return {"id": "p", "properties": {}}

        sync = FakeSync()
        sync.update_page("p", {"status": ""})
        self.assertIsNone(captured["body"]["properties"]["Status"]["select"])

    def test_no_edits_returns_noop(self):
        import notion_sync

        class FakeSync(notion_sync.NotionSync):
            def __init__(self):
                self.api_key = "fake"
                self.data_source_id = "ds"
                self.database_id = ""
                self.api_version = "2025-09-03"

            def _request(self, *a, **kw):
                self.fail("Should not call Notion when there are no edits")

        sync = FakeSync()
        result = sync.update_page("p", {})
        self.assertFalse(result["updated"])

    def test_rich_text_clearable(self):
        import notion_sync
        captured = {}

        class FakeSync(notion_sync.NotionSync):
            def __init__(self):
                self.api_key = "fake"
                self.data_source_id = ""
                self.database_id = "db"
                self.api_version = "2025-09-03"

            def _request(self, method, path, *, json_body=None):
                captured["body"] = json_body
                return {"id": "p", "properties": {}}

        sync = FakeSync()
        sync.update_page("p", {"next_steps": ""})
        rich = captured["body"]["properties"]["Next Steps"]["rich_text"]
        # Empty rich_text is how Notion expects "cleared"
        self.assertEqual(rich, [])


class LeadEndpointsTests(unittest.TestCase):
    """The /api/lead/<page_id> endpoints behave under no-Notion-configured."""

    @classmethod
    def setUpClass(cls):
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        os.environ.pop("NOTION_API_KEY", None)
        os.environ.pop("NOTION_DATA_SOURCE_ID", None)
        os.environ.pop("NOTION_DATABASE_ID", None)
        for mod in ("server", "notion_sync"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    def test_get_lead_without_notion_returns_502(self):
        r = self.client.get("/api/lead/some-page-id")
        self.assertEqual(r.status_code, 502)

    def test_patch_lead_without_body_returns_400(self):
        r = self.client.patch("/api/lead/some-page-id", json={})
        self.assertEqual(r.status_code, 400)

    def test_patch_lead_without_notion_returns_502(self):
        r = self.client.patch("/api/lead/some-page-id", json={"status": "Qualified"})
        self.assertEqual(r.status_code, 502)


if __name__ == "__main__":
    unittest.main()
