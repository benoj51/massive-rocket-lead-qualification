"""v0.5.3: partner sourcing fields (opportunity_source + sourced_for_partners)."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class PayloadDefaultsTests(unittest.TestCase):
    def setUp(self):
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        for mod in ("qualify_service", "apollo", "scope"):
            sys.modules.pop(mod, None)

    def test_qualify_payload_includes_sourcing_keys(self):
        from qualify_service import qualify
        r = qualify("Deliveroo", "deliveroo.co.uk")
        self.assertIn("opportunity_source", r)
        self.assertIn("sourced_for_partners", r)
        self.assertEqual(r["opportunity_source"], "")
        self.assertEqual(r["sourced_for_partners"], [])

    def test_partner_source_override_sets_opportunity_source(self):
        """Existing overrides.partner_source flows into the new field."""
        from qualify_service import qualify
        r = qualify("Deliveroo", "deliveroo.co.uk",
                    overrides={"partner_source": "Hightouch"})
        self.assertEqual(r["opportunity_source"], "Hightouch")


class NotionWriteTests(unittest.TestCase):
    """_payload_to_properties should encode Partner Source + Sourced For correctly."""

    def test_partner_source_writes_select(self):
        from notion_sync import _payload_to_properties
        props = _payload_to_properties({
            "company": {"name": "X", "url": "x.com"},
            "score": {"status": "qualify_in", "status_display": "QUALIFY IN",
                      "total_weighted": 0, "normalized_score": 0,
                      "opportunity_type": "retention", "breakdown": {}},
            "discovered": {}, "opportunity": {"type": "retention"}, "meddicc": {},
            "opportunity_source": "Braze",
        })
        self.assertEqual(props["Partner Source"]["select"]["name"], "Braze")

    def test_sourced_for_writes_multi_select(self):
        from notion_sync import _payload_to_properties
        props = _payload_to_properties({
            "company": {"name": "X", "url": "x.com"},
            "score": {"status": "qualify_in", "status_display": "QUALIFY IN",
                      "total_weighted": 0, "normalized_score": 0,
                      "opportunity_type": "retention", "breakdown": {}},
            "discovered": {}, "opportunity": {"type": "retention"}, "meddicc": {},
            "sourced_for_partners": ["Braze", "Snowflake", "Hightouch"],
        })
        names = [item["name"] for item in props["Sourced For"]["multi_select"]]
        self.assertEqual(set(names), {"Braze", "Snowflake", "Hightouch"})

    def test_empty_sourced_for_does_not_write_property(self):
        from notion_sync import _payload_to_properties
        props = _payload_to_properties({
            "company": {"name": "X", "url": "x.com"},
            "score": {"status": "qualify_in", "status_display": "QUALIFY IN",
                      "total_weighted": 0, "normalized_score": 0,
                      "opportunity_type": "retention", "breakdown": {}},
            "discovered": {}, "opportunity": {"type": "retention"}, "meddicc": {},
            "sourced_for_partners": [],
        })
        self.assertNotIn("Sourced For", props)


class NotionReadTests(unittest.TestCase):
    """_page_to_detail must surface both fields for the drawer."""

    def test_read_partner_source(self):
        from notion_sync import _page_to_detail
        page = {"id": "p", "url": "u", "properties": {
            "Company": {"type": "title", "title": [{"plain_text": "X"}]},
            "Partner Source": {"type": "select", "select": {"name": "Braze"}},
        }}
        d = _page_to_detail(page)
        self.assertEqual(d["opportunity_source"], "Braze")

    def test_read_sourced_for(self):
        from notion_sync import _page_to_detail
        page = {"id": "p", "url": "u", "properties": {
            "Company": {"type": "title", "title": [{"plain_text": "X"}]},
            "Sourced For": {"type": "multi_select", "multi_select": [
                {"name": "Braze"}, {"name": "Snowflake"},
            ]},
        }}
        d = _page_to_detail(page)
        self.assertEqual(set(d["sourced_for_partners"]), {"Braze", "Snowflake"})

    def test_missing_columns_default_safely(self):
        from notion_sync import _page_to_detail
        d = _page_to_detail({"id": "p", "url": "u", "properties": {}})
        self.assertEqual(d["opportunity_source"], "")
        self.assertEqual(d["sourced_for_partners"], [])


class UpdatePageTests(unittest.TestCase):
    """update_page should accept both fields and produce valid Notion payloads."""

    def test_update_partner_source(self):
        import notion_sync
        captured = {}

        class Fake(notion_sync.NotionSync):
            def __init__(self):
                self.api_key = "k"; self.data_source_id = "ds"
                self.database_id = ""; self.api_version = "2025-09-03"

            def _request(self, method, path, *, json_body=None):
                captured["body"] = json_body
                return {"id": "p", "properties": {}}

        Fake().update_page("p", {"opportunity_source": "Snowflake"})
        self.assertEqual(captured["body"]["properties"]["Partner Source"]["select"]["name"],
                         "Snowflake")

    def test_clear_partner_source_with_empty(self):
        import notion_sync
        captured = {}

        class Fake(notion_sync.NotionSync):
            def __init__(self):
                self.api_key = "k"; self.data_source_id = "ds"
                self.database_id = ""; self.api_version = "2025-09-03"

            def _request(self, method, path, *, json_body=None):
                captured["body"] = json_body
                return {"id": "p", "properties": {}}

        Fake().update_page("p", {"opportunity_source": ""})
        self.assertIsNone(captured["body"]["properties"]["Partner Source"]["select"])

    def test_update_sourced_for_list(self):
        import notion_sync
        captured = {}

        class Fake(notion_sync.NotionSync):
            def __init__(self):
                self.api_key = "k"; self.data_source_id = "ds"
                self.database_id = ""; self.api_version = "2025-09-03"

            def _request(self, method, path, *, json_body=None):
                captured["body"] = json_body
                return {"id": "p", "properties": {}}

        Fake().update_page("p", {"sourced_for_partners": ["Braze", "Hightouch"]})
        ms = captured["body"]["properties"]["Sourced For"]["multi_select"]
        self.assertEqual([m["name"] for m in ms], ["Braze", "Hightouch"])

    def test_update_sourced_for_empty_list_clears(self):
        import notion_sync
        captured = {}

        class Fake(notion_sync.NotionSync):
            def __init__(self):
                self.api_key = "k"; self.data_source_id = "ds"
                self.database_id = ""; self.api_version = "2025-09-03"

            def _request(self, method, path, *, json_body=None):
                captured["body"] = json_body
                return {"id": "p", "properties": {}}

        Fake().update_page("p", {"sourced_for_partners": []})
        # Empty list = clear; Notion accepts an empty multi_select array
        self.assertEqual(captured["body"]["properties"]["Sourced For"]["multi_select"], [])


if __name__ == "__main__":
    unittest.main()
