"""v1.0.0ap — activity formatter + endpoint tests."""
from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ActivityFormatterTests(unittest.TestCase):
    """Pure unit tests against activity.format_events — no Flask, no
    audit log writes. Each test stages a list of raw events and checks
    the resulting display rows."""

    def setUp(self):
        sys.modules.pop("activity", None)
        import activity
        self.act = activity

    def test_empty_input_returns_empty(self):
        self.assertEqual(self.act.format_events([]), [])

    def test_uninteresting_types_dropped(self):
        rows = self.act.format_events([
            {"ts": "2026-05-23T10:00:00Z", "type": "pricing_preview",
             "actor": "Ben"},
            {"ts": "2026-05-23T10:01:00Z", "type": "state_backup_mirrored",
             "actor": "Ben"},
        ])
        self.assertEqual(rows, [])

    def test_qualified_event_shape(self):
        rows = self.act.format_events([{
            "ts": "2026-05-23T10:00:00Z", "type": "qualified",
            "actor": "Ben Ojuolape", "company": "Deliveroo",
            "score": 9.4, "status": "qualify_in",
        }])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["actor"], "Ben Ojuolape")
        self.assertEqual(r["type"], "qualified")
        self.assertIn("Deliveroo", r["summary"])
        self.assertIn("9.4", r["summary"])

    def test_lead_updated_with_company_rename(self):
        """`company` in the fields list reads as a rename."""
        rows = self.act.format_events([{
            "ts": "2026-05-23T10:00:00Z", "type": "lead_updated",
            "actor": "Ben", "page_id": "page-abc",
            "fields": ["company"],
        }], lead_names={"page-abc": "Acme Corp"})
        self.assertIn("renamed lead", rows[0]["summary"])
        self.assertIn("Acme Corp", rows[0]["summary"])

    def test_lead_updated_with_owner_reads_as_reassignment(self):
        rows = self.act.format_events([{
            "ts": "2026-05-23T10:00:00Z", "type": "lead_updated",
            "actor": "Ben", "page_id": "page-abc",
            "fields": ["owner"],
        }], lead_names={"page-abc": "Acme"})
        self.assertEqual(rows[0]["summary"], "reassigned Acme")

    def test_partner_updated_with_name_in_fields_reads_as_rename(self):
        rows = self.act.format_events([{
            "ts": "2026-05-23T10:00:00Z", "type": "partner_updated",
            "actor": "Ben", "partner_id": "braze",
            "fields": ["name", "type"],
        }], partner_names={"braze": "BRAZE Inc"})
        self.assertIn("renamed partner", rows[0]["summary"])
        self.assertIn("BRAZE Inc", rows[0]["summary"])

    def test_partner_saved_uses_name_from_event(self):
        rows = self.act.format_events([{
            "ts": "2026-05-23T10:00:00Z", "type": "partner_saved",
            "actor": "Ben", "partner_id": "snowflake",
            "name": "Snowflake",
        }])
        self.assertIn("added partner Snowflake", rows[0]["summary"])

    def test_partner_contact_link_includes_contact_id(self):
        rows = self.act.format_events([{
            "ts": "2026-05-23T10:00:00Z", "type": "partner_contact_saved",
            "actor": "Ben", "partner_id": "braze",
            "contact_id": "marina-id", "name": "Marina Klusas",
        }], partner_names={"braze": "Braze"})
        self.assertEqual(rows[0]["link"], {
            "kind": "partner_contact",
            "partner_id": "braze",
            "contact_id": "marina-id",
        })

    def test_lead_event_link_routes_to_lead(self):
        rows = self.act.format_events([{
            "ts": "2026-05-23T10:00:00Z", "type": "sow_drafted",
            "actor": "Ben", "lead_id": "page-xyz", "version": 3,
        }], lead_names={"page-xyz": "Yum Brands"})
        self.assertEqual(rows[0]["link"],
                         {"kind": "lead", "lead_id": "page-xyz"})
        self.assertIn("SOW v3", rows[0]["summary"])
        self.assertIn("Yum Brands", rows[0]["summary"])

    def test_actor_defaults_when_missing(self):
        rows = self.act.format_events([{
            "ts": "2026-05-23T10:00:00Z", "type": "qualified",
            "company": "X", "score": 5,
        }])
        self.assertEqual(rows[0]["actor"], "(unknown)")

    def test_lead_name_falls_back_to_company_then_short_id(self):
        # No lead_names lookup; event carries `company` — use it.
        rows = self.act.format_events([{
            "ts": "2026-05-23T10:00:00Z", "type": "lead_updated",
            "actor": "Ben", "page_id": "abcdef12345",
            "company": "Captured Co", "fields": ["status"],
        }])
        self.assertIn("Captured Co", rows[0]["summary"])

        # No company, no lookup — short id (first 8 chars).
        rows = self.act.format_events([{
            "ts": "2026-05-23T10:00:00Z", "type": "lead_updated",
            "actor": "Ben", "page_id": "abcdef12345",
            "fields": ["status"],
        }])
        self.assertIn("abcdef12", rows[0]["summary"])

    def test_input_order_preserved(self):
        """format_events doesn't sort — caller is responsible. We just
        keep insertion order so the audit log's reverse-chrono order
        passes through unchanged."""
        events = [
            {"ts": "2026-05-23T10:02:00Z", "type": "qualified",
             "actor": "Ben", "company": "A", "score": 5, "status": "borderline"},
            {"ts": "2026-05-23T10:01:00Z", "type": "qualified",
             "actor": "Glenn", "company": "B", "score": 7, "status": "qualify_in"},
        ]
        rows = self.act.format_events(events)
        self.assertEqual([r["actor"] for r in rows], ["Ben", "Glenn"])

    def test_allowlisted_but_unhandled_type_falls_back(self):
        """If we add a type to INTERESTING_EVENT_TYPES but forget the
        summary branch, the row should still render — with the raw
        type in parentheses so we know to fix it."""
        # Stub a type into the allowlist for this test only.
        import activity as act_mod
        original = act_mod.INTERESTING_EVENT_TYPES
        try:
            act_mod.INTERESTING_EVENT_TYPES = frozenset(
                list(original) + ["future_thing"])
            rows = act_mod.format_events([{
                "ts": "2026-05-23T10:00:00Z", "type": "future_thing",
                "actor": "Ben",
            }])
            self.assertEqual(rows[0]["summary"], "(future_thing)")
        finally:
            act_mod.INTERESTING_EVENT_TYPES = original


class ActivityEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["AUDIT_LOG_PATH"] = os.path.join(cls.tmp, "audit.jsonl")
        os.environ["PARTNERS_STORE_PATH"] = os.path.join(cls.tmp, "p.json")
        os.environ["PARTNER_CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "pc")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "activity", "audit",
                    "partners_store", "partner_contacts_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("AUDIT_LOG_PATH", "PARTNERS_STORE_PATH",
                  "PARTNER_CONTACTS_STORE_DIR",
                  "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        # Fresh audit log per test.
        p = Path(os.environ["AUDIT_LOG_PATH"])
        if p.exists():
            p.unlink()

    def _write_events(self, *events):
        p = Path(os.environ["AUDIT_LOG_PATH"])
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

    def test_endpoint_returns_empty_when_no_log(self):
        r = self.client.get("/api/activity")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {"items": []})

    def test_endpoint_filters_to_interesting(self):
        self._write_events(
            {"ts": "2026-05-23T10:00:00Z", "type": "pricing_preview",
             "actor": "Ben"},
            {"ts": "2026-05-23T10:01:00Z", "type": "qualified",
             "actor": "Ben", "company": "Acme", "score": 8,
             "status": "qualify_in"},
        )
        items = self.client.get("/api/activity").get_json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["type"], "qualified")

    def test_endpoint_limit_clamping(self):
        # Write 15 qualified events, ask for limit=5
        for i in range(15):
            self._write_events({
                "ts": f"2026-05-23T10:{i:02d}:00Z", "type": "qualified",
                "actor": "Ben", "company": f"Co{i}", "score": 5,
                "status": "qualify_in",
            })
        items = self.client.get("/api/activity?limit=5").get_json()["items"]
        self.assertEqual(len(items), 5)

    def test_endpoint_limit_default(self):
        for i in range(30):
            self._write_events({
                "ts": f"2026-05-23T10:{i:02d}:00Z", "type": "qualified",
                "actor": "Ben", "company": f"Co{i}", "score": 5,
                "status": "qualify_in",
            })
        items = self.client.get("/api/activity").get_json()["items"]
        self.assertEqual(len(items), 20)

    def test_endpoint_bad_limit_falls_back(self):
        self._write_events({
            "ts": "2026-05-23T10:00:00Z", "type": "qualified",
            "actor": "Ben", "company": "X", "score": 5, "status": "qualify_in",
        })
        r = self.client.get("/api/activity?limit=not-a-number")
        # Should default to 20 not 500
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.get_json()["items"]), 1)

    def test_endpoint_enriches_with_partner_names(self):
        # Add a partner, then write a partner_updated event by id only.
        self.client.post("/api/partners", json={"name": "Braze"})
        self._write_events({
            "ts": "2026-05-23T10:00:00Z", "type": "partner_updated",
            "actor": "Ben", "partner_id": "braze",
            "fields": ["name"],
        })
        items = self.client.get("/api/activity").get_json()["items"]
        # The summary should include "Braze", not "braze-uuid"
        self.assertIn("Braze", items[0]["summary"])


if __name__ == "__main__":
    unittest.main()
