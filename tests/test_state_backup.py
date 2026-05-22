"""v1.0.0g — durable state backup + restore.

Protects against Railway's ephemeral filesystem wiping notes,
projects, contacts on every redeploy. Backups go to a chunked
rich-text property on the lead's Notion page; restore reads them
back and re-hydrates the local stores.
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class EncodeChunkDecodeTests(unittest.TestCase):
    def setUp(self):
        for mod in ("state_backup",):
            sys.modules.pop(mod, None)

    def test_round_trip_small_payload(self):
        import state_backup
        payload = {"schema_version": 1, "lead_id": "x", "calls": [{"id": "c1"}]}
        blob = state_backup.encode(payload)
        decoded = state_backup.decode(blob)
        self.assertEqual(decoded, payload)

    def test_round_trip_large_payload(self):
        """A realistic lead with many calls compresses + decodes cleanly."""
        import state_backup
        payload = {
            "schema_version": 1,
            "lead_id": "huge",
            "calls": [{"id": f"call-{i}", "content": "long transcript " * 200,
                       "extracted": {"meddpicc": {"metrics": {"value": "5pp uplift"}}}}
                       for i in range(20)],
            "contacts": [{"id": f"c{i}", "name": f"Person {i}"} for i in range(15)],
        }
        blob = state_backup.encode(payload)
        # The compressed blob should be a small fraction of the raw JSON
        raw_size = len(json.dumps(payload))
        self.assertLess(len(blob), raw_size)
        decoded = state_backup.decode(blob)
        self.assertEqual(len(decoded["calls"]), 20)
        self.assertEqual(len(decoded["contacts"]), 15)

    def test_chunk_and_rejoin(self):
        import state_backup
        blob = "a" * 5000
        chunks = state_backup.chunk_for_notion(blob, chunk_size=1900)
        self.assertEqual(len(chunks), 3)  # 1900 + 1900 + 1200
        self.assertEqual(state_backup.join_chunks(chunks), blob)

    def test_decode_rejects_malformed(self):
        import state_backup
        with self.assertRaises(ValueError):
            state_backup.decode("not-base64-and-not-gzip")

    def test_decode_rejects_empty(self):
        import state_backup
        with self.assertRaises(ValueError):
            state_backup.decode("")


class GatherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["CALLS_STORE_DIR"] = os.path.join(self.tmp, "calls")
        os.environ["CONTACTS_STORE_DIR"] = os.path.join(self.tmp, "contacts")
        os.environ["LEAD_CONTACT_NOTES_STORE_DIR"] = os.path.join(self.tmp, "lcn")
        os.environ["PROJECT_STORE_DIR"] = os.path.join(self.tmp, "projects")
        os.environ["PRICING_STORE_DIR"] = os.path.join(self.tmp, "pricing")
        os.environ["LEAD_SUMMARY_STORE_DIR"] = os.path.join(self.tmp, "ls")
        os.environ["CRITERIA_STORE_PATH"] = os.path.join(self.tmp, "criteria.json")
        for mod in ("state_backup", "calls_store", "contacts_store",
                    "lead_contact_notes_store", "project_store",
                    "pricing_store", "lead_summary_store", "scope",
                    "criteria_store"):
            sys.modules.pop(mod, None)

    def tearDown(self):
        for k in ("CALLS_STORE_DIR", "CONTACTS_STORE_DIR",
                  "LEAD_CONTACT_NOTES_STORE_DIR", "PROJECT_STORE_DIR",
                  "PRICING_STORE_DIR", "LEAD_SUMMARY_STORE_DIR",
                  "CRITERIA_STORE_PATH"):
            os.environ.pop(k, None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_gather_empty_lead_returns_empty_arrays(self):
        import state_backup
        payload = state_backup.gather("empty-lead")
        self.assertEqual(payload["calls"], [])
        self.assertEqual(payload["contacts"], [])
        self.assertEqual(payload["contact_notes"], {})
        self.assertIsNone(payload["project"])
        self.assertEqual(payload["schema_version"], 1)
        self.assertIn("captured_at", payload)

    def test_gather_includes_calls_and_contacts(self):
        import state_backup, calls_store, contacts_store
        calls_store.add_call("acme", {"type": "call", "content": "intro chat"})
        contacts_store.save_contact("acme", {"name": "Jane Doe"})
        payload = state_backup.gather("acme")
        self.assertEqual(len(payload["calls"]), 1)
        self.assertEqual(len(payload["contacts"]), 1)


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["CALLS_STORE_DIR"] = os.path.join(self.tmp, "calls")
        os.environ["CONTACTS_STORE_DIR"] = os.path.join(self.tmp, "contacts")
        os.environ["LEAD_CONTACT_NOTES_STORE_DIR"] = os.path.join(self.tmp, "lcn")
        os.environ["PROJECT_STORE_DIR"] = os.path.join(self.tmp, "projects")
        os.environ["PRICING_STORE_DIR"] = os.path.join(self.tmp, "pricing")
        os.environ["LEAD_SUMMARY_STORE_DIR"] = os.path.join(self.tmp, "ls")
        os.environ["CRITERIA_STORE_PATH"] = os.path.join(self.tmp, "criteria.json")
        for mod in ("state_backup", "calls_store", "contacts_store",
                    "lead_contact_notes_store", "project_store",
                    "pricing_store", "lead_summary_store", "scope",
                    "criteria_store"):
            sys.modules.pop(mod, None)

    def tearDown(self):
        for k in ("CALLS_STORE_DIR", "CONTACTS_STORE_DIR",
                  "LEAD_CONTACT_NOTES_STORE_DIR", "PROJECT_STORE_DIR",
                  "PRICING_STORE_DIR", "LEAD_SUMMARY_STORE_DIR",
                  "CRITERIA_STORE_PATH"):
            os.environ.pop(k, None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_restore_round_trip(self):
        """Seed data → gather → wipe cache → apply_backup → original
        state matches."""
        import state_backup, calls_store, contacts_store
        # Seed
        calls_store.add_call("rt-lead", {"type": "call",
                                          "content": "transcript text",
                                          "extracted": None})
        contacts_store.save_contact("rt-lead", {"name": "Restore Me"})
        original = state_backup.gather("rt-lead")
        # Simulate Railway wipe
        shutil.rmtree(self.tmp)
        os.makedirs(self.tmp)
        # Lead should now have no data
        self.assertEqual(calls_store.list_calls("rt-lead"), [])
        self.assertEqual(contacts_store.list_contacts("rt-lead"), [])
        # Restore
        summary = state_backup.apply_backup("rt-lead", original)
        self.assertEqual(summary["calls"], 1)
        self.assertEqual(summary["contacts"], 1)
        # Confirm
        restored_calls = calls_store.list_calls("rt-lead")
        restored_contacts = contacts_store.list_contacts("rt-lead")
        self.assertEqual(len(restored_calls), 1)
        self.assertEqual(restored_contacts[0]["name"], "Restore Me")

    def test_restore_idempotent(self):
        """Applying the same backup twice ends in the same state."""
        import state_backup, calls_store
        calls_store.add_call("idem", {"type": "call", "content": "x"})
        payload = state_backup.gather("idem")
        # Wipe
        shutil.rmtree(self.tmp); os.makedirs(self.tmp)
        state_backup.apply_backup("idem", payload)
        state_backup.apply_backup("idem", payload)  # twice
        self.assertEqual(len(calls_store.list_calls("idem")), 1)

    def test_is_empty_cache_for(self):
        import state_backup, calls_store
        self.assertTrue(state_backup.is_empty_cache_for("nothing"))
        calls_store.add_call("something", {"type": "call", "content": "x"})
        self.assertFalse(state_backup.is_empty_cache_for("something"))


class BackupRestoreEndpointTests(unittest.TestCase):
    """End-to-end: /backup/mirror writes chunked blob to Notion,
    /restore reads it back and re-hydrates."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        for k, v in (
            ("CALLS_STORE_DIR", os.path.join(cls.tmp, "calls")),
            ("CONTACTS_STORE_DIR", os.path.join(cls.tmp, "contacts")),
            ("LEAD_CONTACT_NOTES_STORE_DIR", os.path.join(cls.tmp, "lcn")),
            ("PROJECT_STORE_DIR", os.path.join(cls.tmp, "projects")),
            ("PRICING_STORE_DIR", os.path.join(cls.tmp, "pricing")),
            ("LEAD_SUMMARY_STORE_DIR", os.path.join(cls.tmp, "ls")),
            ("CRITERIA_STORE_PATH", os.path.join(cls.tmp, "criteria.json")),
            ("APOLLO_USE_FIXTURES", "1"),
        ):
            os.environ[k] = v
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "state_backup", "calls_store",
                    "contacts_store", "lead_contact_notes_store",
                    "project_store", "pricing_store",
                    "lead_summary_store", "notion_sync"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("CALLS_STORE_DIR", "CONTACTS_STORE_DIR",
                  "LEAD_CONTACT_NOTES_STORE_DIR", "PROJECT_STORE_DIR",
                  "PRICING_STORE_DIR", "LEAD_SUMMARY_STORE_DIR",
                  "CRITERIA_STORE_PATH"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_backup_endpoint_returns_payload(self):
        import calls_store
        calls_store.add_call("endpoint-lead", {"type": "call", "content": "x"})
        r = self.client.get("/api/lead/endpoint-lead/backup")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn("payload", body)
        self.assertIn("encoded", body)
        self.assertEqual(len(body["payload"]["calls"]), 1)

    def test_restore_404_when_no_backup(self):
        """If Notion's State Backup property is empty, /restore 404s
        with a helpful hint."""
        fake_sync = MagicMock()
        fake_sync.get_page.return_value = {"id": "x", "state_backup": ""}
        with patch.object(self.server, "NotionSync", return_value=fake_sync):
            r = self.client.post("/api/lead/x/restore")
        self.assertEqual(r.status_code, 404)
        self.assertIn("no backup", r.get_json()["error"].lower())

    def test_restore_applies_backup_from_notion(self):
        """The full pipeline: encode a payload, hand it to fake Notion,
        call /restore, verify the stores re-hydrate."""
        import state_backup
        payload = {
            "schema_version": 1, "lead_id": "rest-lead",
            "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "calls": [{"id": "c1", "type": "call", "content": "saved transcript",
                        "created_at": "2026-05-21T10:00:00.000000Z", "extracted": None}],
            "contacts": [{"id": "p1", "name": "Restored Person"}],
            "contact_notes": {}, "project": None, "pricing": None,
            "roadmap": None, "summary": None,
        }
        blob = state_backup.encode(payload)
        fake_sync = MagicMock()
        fake_sync.get_page.return_value = {"id": "rest-lead", "state_backup": blob}
        with patch.object(self.server, "NotionSync", return_value=fake_sync):
            r = self.client.post("/api/lead/rest-lead/restore")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["restored"])
        # Verify the local stores now have the restored data
        import calls_store, contacts_store
        self.assertEqual(len(calls_store.list_calls("rest-lead")), 1)
        contacts = contacts_store.list_contacts("rest-lead")
        self.assertEqual(contacts[0]["name"], "Restored Person")


class BackupHealthRingBufferTests(unittest.TestCase):
    """v1.0.0s: the _BACKUP_HEALTH deque caps at 20 entries. Verify
    that the cap actually evicts and that /api/diagnostics/health
    returns the latest entries, not the earliest."""

    def setUp(self):
        os.environ["SKIP_NOTION_BOOT"] = "1"
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        for mod in ("server",):
            sys.modules.pop(mod, None)
        import server
        self.server = server
        self.client = server.app.test_client()
        # Reset the ring buffer to a known state.
        self.server._BACKUP_HEALTH.clear()

    def tearDown(self):
        for k in ("SKIP_NOTION_BOOT", "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)

    def test_ring_buffer_caps_at_20(self):
        """Append 25 fake attempts; deque should hold only the latest 20."""
        from datetime import datetime, timezone
        for i in range(25):
            self.server._BACKUP_HEALTH.append({
                "lead_id": f"lead-{i}",
                "at": datetime.now(timezone.utc).isoformat(),
                "ok": (i % 2 == 0),
                "error": None if (i % 2 == 0) else f"err-{i}",
                "bytes": i * 100,
                "chunks": 1,
            })
        self.assertEqual(len(self.server._BACKUP_HEALTH), 20)
        # Oldest 5 evicted: leads 0..4 gone, 5..24 remain.
        lead_ids = [a["lead_id"] for a in self.server._BACKUP_HEALTH]
        self.assertNotIn("lead-0", lead_ids)
        self.assertNotIn("lead-4", lead_ids)
        self.assertIn("lead-5", lead_ids)
        self.assertIn("lead-24", lead_ids)

    def test_diagnostics_surfaces_latest_attempts(self):
        """The /api/diagnostics/health endpoint returns recent[-5:],
        i.e. the 5 most-recent attempts. After 25 fakes, those should
        be leads 20..24."""
        from datetime import datetime, timezone
        for i in range(25):
            self.server._BACKUP_HEALTH.append({
                "lead_id": f"lead-{i}",
                "at": datetime.now(timezone.utc).isoformat(),
                "ok": True, "error": None, "bytes": 0, "chunks": 0,
            })
        r = self.client.get("/api/diagnostics/health")
        self.assertEqual(r.status_code, 200)
        recent = r.get_json()["mirror_health"]["recent"]
        self.assertEqual(len(recent), 5)
        recent_ids = [a["lead_id"] for a in recent]
        # The deque holds 5..24; the last 5 are 20..24.
        self.assertEqual(recent_ids, [f"lead-{i}" for i in range(20, 25)])

    def test_failure_count_accurate_under_cap(self):
        """The successes/failures tally should reflect only the
        in-buffer attempts, not the total historical."""
        from datetime import datetime, timezone
        # Append 30 — first 10 fail, next 20 succeed. After cap,
        # only the latest 20 (all successes) remain.
        for i in range(30):
            self.server._BACKUP_HEALTH.append({
                "lead_id": f"lead-{i}",
                "at": datetime.now(timezone.utc).isoformat(),
                "ok": (i >= 10),
                "error": None if i >= 10 else "old failure",
                "bytes": 0, "chunks": 0,
            })
        r = self.client.get("/api/diagnostics/health")
        body = r.get_json()["mirror_health"]
        self.assertEqual(body["attempts_tracked"], 20)
        self.assertEqual(body["successes"], 20)
        self.assertEqual(body["failures"], 0)


if __name__ == "__main__":
    unittest.main()
