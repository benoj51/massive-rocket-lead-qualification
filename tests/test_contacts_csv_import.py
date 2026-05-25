"""v1.0.0cf — CSV import for lead contacts + expansion target contacts.

The partner CSV import (test_partner_contacts_csv_import.py) covers the
shared helper's logic. These tests pin the two new endpoints'
store-specific adapters:

- Lead contacts: contacts_store → /api/contacts/<lead_id>/import-csv
- Expansion target contacts: expansion_targets_store → embedded
  contacts array; only name/title/email allowed (narrower schema).
"""
from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# -----------------------------------------------------------------
# Lead contacts CSV import
# -----------------------------------------------------------------

class LeadContactsCsvImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "contacts")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "contacts_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("CONTACTS_STORE_DIR", "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        import contacts_store
        d = contacts_store._store_dir()
        if d.exists():
            for f in d.glob("*.json"):
                f.unlink()

    def _post(self, lead_id, csv, dry_run=True):
        return self.client.post(
            f"/api/contacts/{lead_id}/import-csv",
            json={"csv": csv, "dry_run": dry_run})

    def _list(self, lead_id):
        import contacts_store
        return contacts_store.list_contacts(lead_id)

    def test_dry_run_doesnt_write(self):
        csv = "name,title\nJane,VP\nJohn,AE"
        r = self._post("lead-abc", csv, dry_run=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["summary"]["would_add"], 2)
        self.assertEqual(len(self._list("lead-abc")), 0)

    def test_commit_writes(self):
        csv = "name,title,email\nJane Doe,VP,jane@x.com\nJohn Roe,AE,"
        r = self._post("lead-abc", csv, dry_run=False)
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["summary"]["would_add"], 2)
        self.assertTrue(body["summary"]["committed"])
        contacts = self._list("lead-abc")
        names = {c["name"] for c in contacts}
        self.assertEqual(names, {"Jane Doe", "John Roe"})

    def test_update_by_name(self):
        import contacts_store
        contacts_store.save_contact("lead-abc", {
            "name": "Existing", "title": "Old"})
        csv = "name,title\nExisting,New Title"
        body = self._post("lead-abc", csv, dry_run=False).get_json()
        self.assertEqual(body["summary"]["would_update"], 1)
        self.assertEqual(body["summary"]["would_add"], 0)
        contacts = self._list("lead-abc")
        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0]["title"], "New Title")

    def test_empty_csv_400(self):
        r = self._post("lead-abc", "")
        self.assertEqual(r.status_code, 400)

    def test_row_without_name_or_email_errors(self):
        csv = "name,email\n,\nReal Person,"
        body = self._post("lead-abc", csv).get_json()
        self.assertEqual(body["summary"]["errored"], 1)
        self.assertEqual(body["summary"]["would_add"], 1)

    def test_stakeholder_role_round_trips(self):
        """contacts_store supports stakeholder_role / influence /
        interest — should flow through the CSV importer unchanged
        (these aren't in the header synonym table but they ARE valid
        store fields; unknown headers get listed in the summary)."""
        csv = "name,title\nChampion Co,VP Loyalty"
        self._post("lead-abc", csv, dry_run=False)
        contacts = self._list("lead-abc")
        self.assertEqual(len(contacts), 1)


# -----------------------------------------------------------------
# Expansion target contacts CSV import
# -----------------------------------------------------------------

class ExpansionTargetContactsCsvImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["EXPANSION_TARGETS_STORE_DIR"] = os.path.join(cls.tmp, "ex")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "expansion_targets_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("EXPANSION_TARGETS_STORE_DIR", "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        import expansion_targets_store
        d = expansion_targets_store._store_dir()
        if d.exists():
            for f in d.glob("*.json"):
                f.unlink()
        # Seed a target per test.
        self.target = expansion_targets_store.create(
            "shell-na", "Shell UK", region="UK")

    def _post(self, target_id, csv, dry_run=True):
        return self.client.post(
            f"/api/expansion-targets/{target_id}/contacts/import-csv",
            json={"csv": csv, "dry_run": dry_run})

    def _contacts(self):
        import expansion_targets_store
        t = expansion_targets_store.get(self.target["id"])
        return t.get("contacts") or []

    def test_unknown_target_404(self):
        r = self._post("does-not-exist", "name\nJane")
        self.assertEqual(r.status_code, 404)

    def test_commit_writes_embedded_contacts(self):
        csv = "name,title,email\nSarah,Head of Loyalty,sarah@shell.com\nMarina,AE,"
        r = self._post(self.target["id"], csv, dry_run=False)
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["summary"]["would_add"], 2)
        contacts = self._contacts()
        self.assertEqual(len(contacts), 2)
        names = {c["name"] for c in contacts}
        self.assertEqual(names, {"Sarah", "Marina"})

    def test_narrower_schema_drops_extra_fields(self):
        """Expansion target contacts have name/title/email/source/notes
        only. Other CSV columns (tier, region, etc.) should be silently
        dropped by the allowed_keys filter — not error the row."""
        csv = "name,title,email,tier,region,industries\nSarah,VP,s@x.com,T1,EMEA,QSR"
        body = self._post(self.target["id"], csv, dry_run=False).get_json()
        self.assertEqual(body["summary"]["would_add"], 1)
        self.assertEqual(body["summary"]["errored"], 0)
        c = self._contacts()[0]
        self.assertEqual(c["name"], "Sarah")
        self.assertEqual(c["title"], "VP")
        self.assertEqual(c["email"], "s@x.com")
        # tier / region / industries shouldn't leak into the stored
        # embedded contact (they're not part of its schema).
        self.assertNotIn("tier", c)
        self.assertNotIn("regions", c)

    def test_update_by_name_preserves_other_fields(self):
        import expansion_targets_store
        # Seed an existing contact.
        existing = expansion_targets_store.add_contact(
            self.target["id"], {"name": "Sarah", "title": "Old",
                                 "email": "old@shell.com"})
        csv = "name,title\nSarah,New Title"
        body = self._post(self.target["id"], csv, dry_run=False).get_json()
        self.assertEqual(body["summary"]["would_update"], 1)
        contacts = self._contacts()
        # Update flow re-adds; should be one contact, with both
        # the new title AND the preserved email.
        self.assertEqual(len(contacts), 1)
        c = contacts[0]
        self.assertEqual(c["title"], "New Title")

    def test_row_without_name_or_email_errors(self):
        csv = "name,email\n,\nGood Row,"
        body = self._post(self.target["id"], csv).get_json()
        self.assertEqual(body["summary"]["errored"], 1)
        self.assertEqual(body["summary"]["would_add"], 1)


if __name__ == "__main__":
    unittest.main()
