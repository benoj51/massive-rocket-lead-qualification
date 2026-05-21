"""v1.0.0b (Tier 1d) — engagement timeline per lead contact."""
from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class LeadContactNotesStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["LEAD_CONTACT_NOTES_STORE_DIR"] = self.tmp
        for mod in ("lead_contact_notes_store", "project_store"):
            sys.modules.pop(mod, None)

    def tearDown(self):
        os.environ.pop("LEAD_CONTACT_NOTES_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_add_requires_content(self):
        import lead_contact_notes_store as s
        with self.assertRaises(s.LeadContactNotesStoreError):
            s.add_note("yum", "c1", {"type": "call"})

    def test_notes_listed_newest_first(self):
        import lead_contact_notes_store as s
        s.add_note("yum", "c1", {"content": "First"})
        time.sleep(0.001)
        s.add_note("yum", "c1", {"content": "Second"})
        notes = s.list_notes("yum", "c1")
        self.assertEqual(notes[0]["content"], "Second")
        self.assertEqual(notes[1]["content"], "First")

    def test_unknown_type_falls_back_to_other(self):
        import lead_contact_notes_store as s
        n = s.add_note("yum", "c1", {"content": "x", "type": "bogus"})
        self.assertEqual(n["type"], "other")

    def test_scoped_per_lead_and_contact(self):
        """Notes on (yum, c1) don't bleed into (yum, c2) or (kfc, c1)."""
        import lead_contact_notes_store as s
        s.add_note("yum", "c1", {"content": "yum-c1"})
        s.add_note("yum", "c2", {"content": "yum-c2"})
        s.add_note("kfc", "c1", {"content": "kfc-c1"})
        self.assertEqual(len(s.list_notes("yum", "c1")), 1)
        self.assertEqual(len(s.list_notes("yum", "c2")), 1)
        self.assertEqual(len(s.list_notes("kfc", "c1")), 1)
        self.assertEqual(s.list_notes("yum", "c1")[0]["content"], "yum-c1")

    def test_cascade_delete_for_contact(self):
        import lead_contact_notes_store as s
        s.add_note("yum", "c1", {"content": "hi"})
        self.assertTrue(s.delete_all_for_contact("yum", "c1"))
        self.assertEqual(s.list_notes("yum", "c1"), [])

    def test_delete_single_note(self):
        import lead_contact_notes_store as s
        n = s.add_note("yum", "c1", {"content": "x"})
        self.assertTrue(s.delete_note("yum", "c1", n["id"]))
        self.assertEqual(s.list_notes("yum", "c1"), [])
        self.assertFalse(s.delete_note("yum", "c1", n["id"]))


class LeadContactNotesEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["LEAD_CONTACT_NOTES_STORE_DIR"] = os.path.join(cls.tmp, "lcn")
        os.environ["CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "contacts")
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "contacts_store", "lead_contact_notes_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("LEAD_CONTACT_NOTES_STORE_DIR", None)
        os.environ.pop("CONTACTS_STORE_DIR", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _seed_contact(self, lead="ep-yum", name="Jane"):
        import contacts_store
        c = contacts_store.save_contact(lead, {"name": name})
        return c["id"]

    def test_list_empty(self):
        cid = self._seed_contact()
        r = self.client.get(f"/api/contacts/ep-yum/{cid}/notes")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["notes"], [])

    def test_add_note_bumps_contact_touch(self):
        cid = self._seed_contact("bump-lead")
        r = self.client.post(
            f"/api/contacts/bump-lead/{cid}/notes",
            json={"content": "Talked at the conference", "type": "intro"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(len(body["notes"]), 1)
        # Contact returned with bumped last_touched_at
        self.assertIsNotNone(body["contact"])
        self.assertIsNotNone(body["contact"]["last_touched_at"])
        self.assertFalse(body["contact"]["overdue"])

    def test_delete_note(self):
        cid = self._seed_contact("del-lead")
        r = self.client.post(
            f"/api/contacts/del-lead/{cid}/notes",
            json={"content": "x"},
        )
        note_id = r.get_json()["note"]["id"]
        d = self.client.delete(f"/api/contacts/del-lead/{cid}/notes/{note_id}")
        self.assertEqual(d.status_code, 200)
        self.assertTrue(d.get_json()["deleted"])

    def test_delete_contact_cascades_notes(self):
        cid = self._seed_contact("cascade-lead")
        self.client.post(
            f"/api/contacts/cascade-lead/{cid}/notes",
            json={"content": "to-be-orphaned"},
        )
        # Delete the contact
        d = self.client.delete(f"/api/contacts/cascade-lead/{cid}")
        self.assertEqual(d.status_code, 200)
        # Notes should be gone too
        nr = self.client.get(f"/api/contacts/cascade-lead/{cid}/notes")
        self.assertEqual(nr.get_json()["notes"], [])

    def test_add_note_requires_content(self):
        cid = self._seed_contact("nocon-lead")
        r = self.client.post(
            f"/api/contacts/nocon-lead/{cid}/notes",
            json={"type": "call"},
        )
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
