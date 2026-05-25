"""v1.0.0ca — lead lifecycle: stages, statuses, close-reason flow.

The frontend handles the actual stage-flip workflows (reason prompts,
Promote-to-Live trigger). These tests pin the BACKEND contract those
workflows depend on:

1. SALES_STAGES + LEAD_STATUSES constants include the new values
2. enum_config_store surfaces both as editable lists
3. /api/settings/enums returns sales_stages + lead_statuses
4. Notion sync accepts Nurture / Rejected as status values
5. close_reason field round-trips through update + read
6. Boot self-heal includes the Close Reason property
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# -----------------------------------------------------------------
# 1. Constants
# -----------------------------------------------------------------

class LifecycleConstantsTests(unittest.TestCase):
    def test_sales_stages_include_closed(self):
        sys.modules.pop("config", None)
        import config
        self.assertIn("Closed Won", config.SALES_STAGES)
        self.assertIn("Closed Lost", config.SALES_STAGES)
        # Existing stages still present.
        self.assertIn("Discovery", config.SALES_STAGES)
        self.assertIn("Signature", config.SALES_STAGES)

    def test_lead_statuses_include_new_values(self):
        sys.modules.pop("config", None)
        import config
        self.assertIn("Nurture", config.LEAD_STATUSES)
        self.assertIn("Rejected", config.LEAD_STATUSES)
        # Original lifecycle still present.
        self.assertIn("Qualified", config.LEAD_STATUSES)
        self.assertIn("Disqualified", config.LEAD_STATUSES)


# -----------------------------------------------------------------
# 2. enum_config_store — both lead-side enums surface
# -----------------------------------------------------------------

class EnumConfigStoreLeadSideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["ENUM_CONFIG_PATH"] = os.path.join(self.tmp, "enums.json")
        sys.modules.pop("enum_config_store", None)
        import enum_config_store
        self.store = enum_config_store

    def tearDown(self):
        os.environ.pop("ENUM_CONFIG_PATH", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load_returns_sales_stages_and_lead_statuses(self):
        cfg = self.store.load()
        self.assertIn("sales_stages", cfg)
        self.assertIn("lead_statuses", cfg)
        self.assertIn("Closed Won", cfg["sales_stages"])
        self.assertIn("Nurture", cfg["lead_statuses"])

    def test_partner_enums_still_present(self):
        """Refactor mustn't break the partner-side enums it
        previously served."""
        cfg = self.store.load()
        for key in ("industries", "territories", "regions",
                     "statuses", "partner_sentiments",
                     "tiers", "seniorities"):
            self.assertIn(key, cfg)

    def test_admin_can_save_custom_sales_stages(self):
        """Save a custom list, re-read, get the custom list back."""
        custom = ["Demo Booked", "Pricing Review", "Closed Won"]
        self.store.save({"sales_stages": custom})
        cfg = self.store.load()
        self.assertEqual(cfg["sales_stages"], custom)


# -----------------------------------------------------------------
# 3. /api/settings/enums returns the new keys
# -----------------------------------------------------------------

class SettingsEnumsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["ENUM_CONFIG_PATH"] = os.path.join(cls.tmp, "enums.json")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "enum_config_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("ENUM_CONFIG_PATH", "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_get_returns_sales_stages(self):
        r = self.client.get("/api/settings/enums")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn("sales_stages", body)
        self.assertIn("Closed Won", body["sales_stages"])
        self.assertIn("Closed Lost", body["sales_stages"])

    def test_get_returns_lead_statuses(self):
        r = self.client.get("/api/settings/enums")
        body = r.get_json()
        self.assertIn("lead_statuses", body)
        self.assertIn("Nurture", body["lead_statuses"])
        self.assertIn("Rejected", body["lead_statuses"])


# -----------------------------------------------------------------
# 4 + 5. Notion sync — status mapping + close_reason round-trip
# -----------------------------------------------------------------

class NotionSyncLifecycleTests(unittest.TestCase):
    """Verify the update_page select map accepts Nurture / Rejected
    and that close_reason rich-text writes alongside other text fields.
    Mocks the HTTP boundary so no Notion call leaks out."""

    def setUp(self):
        sys.modules.pop("notion_sync", None)
        from notion_sync import NotionSync
        self.sync = NotionSync.__new__(NotionSync)
        self.sync.database_id = "db"
        self.sync.data_source_id = ""
        self.sync.api_key = "k"

    def test_status_nurture_maps(self):
        captured = {}
        def fake_request(method, path, json_body=None):
            captured["props"] = json_body["properties"]
            return {"id": "p", "url": "u", "properties": {}}
        with patch.object(self.sync, "_request", side_effect=fake_request):
            self.sync.update_page("p", {"status": "Nurture"})
        self.assertEqual(captured["props"]["Status"],
                          {"select": {"name": "Nurture"}})

    def test_status_rejected_maps(self):
        captured = {}
        def fake_request(method, path, json_body=None):
            captured["props"] = json_body["properties"]
            return {"id": "p", "url": "u", "properties": {}}
        with patch.object(self.sync, "_request", side_effect=fake_request):
            self.sync.update_page("p", {"status": "Rejected"})
        self.assertEqual(captured["props"]["Status"],
                          {"select": {"name": "Rejected"}})

    def test_close_reason_written_as_rich_text(self):
        """The reason capture from the Closed Lost / Rejected prompts
        flows through edits.close_reason → Notion 'Close Reason' rich
        text."""
        captured = {}
        def fake_request(method, path, json_body=None):
            captured["props"] = json_body["properties"]
            return {"id": "p", "url": "u", "properties": {}}
        with patch.object(self.sync, "_request", side_effect=fake_request):
            self.sync.update_page("p", {
                "status":       "Nurture",
                "sales_stage":  "Closed Lost",
                "close_reason": "Budget pulled in Q4 reshuffle",
            })
        # Status + sales_stage selected, close_reason rich-text.
        self.assertIn("Close Reason", captured["props"])
        self.assertEqual(
            captured["props"]["Close Reason"]["rich_text"][0]["text"]["content"],
            "Budget pulled in Q4 reshuffle")

    def test_close_reason_round_trip_via_page_to_detail(self):
        """A Notion page with the Close Reason property should expose
        it under `close_reason` in the flattened detail dict."""
        from notion_sync import _page_to_detail
        page = {
            "id": "p", "url": "https://notion.so/p",
            "properties": {
                "Close Reason": {
                    "type": "rich_text",
                    "rich_text": [{"plain_text": "lost to incumbent",
                                    "text": {"content": "lost to incumbent"}}]
                },
            },
        }
        out = _page_to_detail(page)
        self.assertEqual(out["close_reason"], "lost to incumbent")


# -----------------------------------------------------------------
# 6. Boot self-heal includes Close Reason
# -----------------------------------------------------------------

class BootSelfHealTests(unittest.TestCase):
    def test_close_reason_in_self_heal_spec(self):
        """The boot ensure_properties call must include Close Reason
        so a freshly-cloned Notion DB gets the column automatically."""
        text = Path(ROOT / "server.py").read_text()
        # Both call sites (boot + lazy retry) include it.
        self.assertGreaterEqual(text.count('"Close Reason"'), 2,
            "Expected Close Reason in both boot + lazy-retry ensure_properties calls")


if __name__ == "__main__":
    unittest.main()
