"""v1.0.0p — incumbent + previous agencies per lead.

Covers:
- Store round-trips
- Normalisation (required name, valid type, optional fields)
- Sort order (incumbents-first then alpha)
- AI summary serialisation
- Endpoint integration: GET / POST / PATCH / DELETE
- state_backup integration (gather + restore round-trip)
"""
from __future__ import annotations

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


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["LEAD_AGENCIES_STORE_DIR"] = os.path.join(self.tmp, "la")
        for mod in ("lead_agencies_store", "project_store"):
            sys.modules.pop(mod, None)

    def tearDown(self):
        os.environ.pop("LEAD_AGENCIES_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_requires_name(self):
        import lead_agencies_store as s
        with self.assertRaises(s.LeadAgenciesStoreError):
            s.save_agency("lead-1", {"type": "incumbent"})

    def test_rejects_unknown_type(self):
        import lead_agencies_store as s
        with self.assertRaises(s.LeadAgenciesStoreError):
            s.save_agency("lead-1", {"name": "VML", "type": "current"})

    def test_save_then_list_roundtrip(self):
        import lead_agencies_store as s
        saved = s.save_agency("lead-1", {
            "name": "VML", "type": "incumbent",
            "scope": "Braze ops", "notes": "Mediocre — opportunity",
        })
        self.assertIn("id", saved)
        self.assertEqual(saved["name"], "VML")
        self.assertEqual(saved["type"], "incumbent")
        self.assertEqual(saved["scope"], "Braze ops")
        rows = s.list_agencies("lead-1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], saved["id"])

    def test_upsert_by_id(self):
        import lead_agencies_store as s
        saved = s.save_agency("lead-1", {"name": "VML", "type": "incumbent"})
        updated = s.save_agency("lead-1", {
            "id": saved["id"], "name": "VML", "type": "incumbent",
            "notes": "Updated context.",
        })
        self.assertEqual(updated["id"], saved["id"])
        self.assertEqual(updated["notes"], "Updated context.")
        # Still one row — upsert, not duplicate.
        self.assertEqual(len(s.list_agencies("lead-1")), 1)

    def test_sort_incumbents_first(self):
        import lead_agencies_store as s
        s.save_agency("lead-1", {"name": "Zeta", "type": "previous"})
        s.save_agency("lead-1", {"name": "Bravo", "type": "previous"})
        s.save_agency("lead-1", {"name": "Alpha", "type": "incumbent"})
        rows = s.list_agencies("lead-1")
        names = [r["name"] for r in rows]
        # Incumbent first
        self.assertEqual(names[0], "Alpha")
        # Previous in alpha order
        self.assertEqual(names[1:], ["Bravo", "Zeta"])

    def test_delete(self):
        import lead_agencies_store as s
        a = s.save_agency("lead-1", {"name": "VML", "type": "incumbent"})
        self.assertTrue(s.delete_agency("lead-1", a["id"]))
        self.assertEqual(s.list_agencies("lead-1"), [])
        # Second delete is a no-op
        self.assertFalse(s.delete_agency("lead-1", a["id"]))

    def test_summarise_for_ai_includes_type_and_scope(self):
        import lead_agencies_store as s
        s.save_agency("lead-1", {
            "name": "VML", "type": "incumbent", "scope": "Braze ops",
        })
        s.save_agency("lead-1", {
            "name": "Razorfish", "type": "previous",
            "since": "2019", "until": "2022",
        })
        summary = s.summarise_for_ai("lead-1")
        joined = " ".join(summary)
        self.assertIn("VML", joined)
        self.assertIn("incumbent", joined)
        self.assertIn("Braze ops", joined)
        self.assertIn("Razorfish", joined)
        self.assertIn("2019", joined)


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._env_set: dict[str, str | None] = {}
        for k, v in {
            "LEAD_AGENCIES_STORE_DIR": os.path.join(self.tmp, "la"),
            "SKIP_NOTION_BOOT": "1",
            "SKIP_COMMAND_CENTRE_SEED": "1",
        }.items():
            self._env_set[k] = os.environ.get(k)
            os.environ[k] = v
        for mod in ("server", "lead_agencies_store", "project_store"):
            sys.modules.pop(mod, None)
        import server
        self.server = server
        self.client = server.app.test_client()

    def tearDown(self):
        for k, original in self._env_set.items():
            if original is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = original
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_get_empty_list(self):
        r = self.client.get("/api/leads/lead-1/agencies")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["agencies"], [])
        self.assertIn("incumbent", r.get_json()["types"])

    def test_post_creates_entry(self):
        r = self.client.post("/api/leads/lead-1/agencies",
                              json={"name": "VML", "type": "incumbent",
                                    "scope": "Braze ops"})
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["agency"]["name"], "VML")
        self.assertEqual(len(data["agencies"]), 1)

    def test_post_400_when_name_missing(self):
        r = self.client.post("/api/leads/lead-1/agencies",
                              json={"type": "incumbent"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("name", r.get_json()["error"].lower())

    def test_patch_updates(self):
        r = self.client.post("/api/leads/lead-1/agencies",
                              json={"name": "VML", "type": "incumbent"})
        aid = r.get_json()["agency"]["id"]
        r2 = self.client.patch(f"/api/leads/lead-1/agencies/{aid}",
                                json={"notes": "Updated context."})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.get_json()["agency"]["notes"], "Updated context.")
        # Still one row
        self.assertEqual(len(r2.get_json()["agencies"]), 1)

    def test_patch_404_when_unknown(self):
        r = self.client.patch("/api/leads/lead-1/agencies/no-such-id",
                               json={"name": "x"})
        self.assertEqual(r.status_code, 404)

    def test_delete_removes(self):
        r = self.client.post("/api/leads/lead-1/agencies",
                              json={"name": "VML", "type": "incumbent"})
        aid = r.get_json()["agency"]["id"]
        r2 = self.client.delete(f"/api/leads/lead-1/agencies/{aid}")
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.get_json()["deleted"])
        # Re-deleting is a 404
        r3 = self.client.delete(f"/api/leads/lead-1/agencies/{aid}")
        self.assertEqual(r3.status_code, 404)


class StateBackupTests(unittest.TestCase):
    """Agencies must survive cache wipes via the v1.0.0g Notion mirror."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        for k, v in {
            "LEAD_AGENCIES_STORE_DIR": os.path.join(self.tmp, "la"),
            "CALLS_STORE_DIR":         os.path.join(self.tmp, "calls"),
            "CONTACTS_STORE_DIR":      os.path.join(self.tmp, "contacts"),
            "LEAD_CONTACT_NOTES_STORE_DIR": os.path.join(self.tmp, "ln"),
            "LEAD_SUMMARY_STORE_DIR":  os.path.join(self.tmp, "ls"),
            "PROJECT_STORE_DIR":       os.path.join(self.tmp, "ps"),
            "PRICING_STORE_DIR":       os.path.join(self.tmp, "pr"),
            "ROADMAP_STORE_DIR":       os.path.join(self.tmp, "rm"),
        }.items():
            os.environ[k] = v
        for mod in ("state_backup", "lead_agencies_store", "project_store"):
            sys.modules.pop(mod, None)

    def tearDown(self):
        for k in ("LEAD_AGENCIES_STORE_DIR", "CALLS_STORE_DIR",
                   "CONTACTS_STORE_DIR", "LEAD_CONTACT_NOTES_STORE_DIR",
                   "LEAD_SUMMARY_STORE_DIR", "PROJECT_STORE_DIR",
                   "PRICING_STORE_DIR", "ROADMAP_STORE_DIR"):
            os.environ.pop(k, None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_gather_includes_agencies(self):
        import lead_agencies_store, state_backup
        lead_agencies_store.save_agency("lead-1", {"name": "VML", "type": "incumbent"})
        payload = state_backup.gather("lead-1")
        self.assertIn("agencies", payload)
        self.assertEqual(len(payload["agencies"]), 1)
        self.assertEqual(payload["agencies"][0]["name"], "VML")

    def test_apply_restores_agencies(self):
        import lead_agencies_store, state_backup
        # Snapshot a payload with agencies
        lead_agencies_store.save_agency("lead-1", {"name": "VML", "type": "incumbent"})
        lead_agencies_store.save_agency("lead-1", {"name": "Razorfish", "type": "previous"})
        payload = state_backup.gather("lead-1")
        # Wipe the local store
        lead_agencies_store._write_raw("lead-1", [])
        self.assertEqual(lead_agencies_store.list_agencies("lead-1"), [])
        # Restore
        summary = state_backup.apply_backup("lead-1", payload)
        self.assertEqual(summary["agencies"], 2)
        self.assertEqual(len(lead_agencies_store.list_agencies("lead-1")), 2)


if __name__ == "__main__":
    unittest.main()
