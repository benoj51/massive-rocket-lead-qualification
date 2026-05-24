"""v1.0.0bv — CSV import for partner contacts.

Covers /api/partners/<pid>/contacts/import-csv:
- Header normalisation + synonyms + unknown-header detection
- Multi-tag splitting (comma / pipe / semicolon)
- City stashed in tags (no first-class city field)
- Dry-run vs commit (same parse, different write)
- Name + email dedup → update mode
- Update merge: empty CSV cells DON'T clobber existing fields
- Validation: rows without name/email surface as errors
- BOM-tolerant parsing (Excel exports)
- Same name appearing twice in one CSV → second row updates the first
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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class PartnerContactsCsvImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["PARTNERS_STORE_PATH"] = os.path.join(cls.tmp, "partners.json")
        os.environ["PARTNER_CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "pc")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "partners_store", "partner_contacts_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("PARTNERS_STORE_PATH", "PARTNER_CONTACTS_STORE_DIR",
                  "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        import partners_store, partner_contacts_store
        p = partners_store._path()
        if p.exists():
            p.unlink()
        d = partner_contacts_store._store_dir()
        if d.exists():
            for f in d.glob("*.json"):
                f.unlink()
        # Seed a partner per test.
        self.partner = partners_store.save_partner({
            "name": "Hightouch", "type": "Technology partner"})

    def _post(self, csv, dry_run=True):
        return self.client.post(
            f"/api/partners/{self.partner['id']}/contacts/import-csv",
            json={"csv": csv, "dry_run": dry_run})

    def _list(self):
        import partner_contacts_store
        return partner_contacts_store.list_contacts(self.partner["id"])

    # ---- happy paths ------------------------------------------------

    def test_dry_run_returns_preview_without_writing(self):
        csv = "name,title\nJane Doe,VP Sales\nJohn Roe,AE"
        r = self._post(csv, dry_run=True)
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["summary"]["would_add"], 2)
        self.assertEqual(body["summary"]["committed"], False)
        # Store still empty.
        self.assertEqual(len(self._list()), 0)

    def test_commit_writes_to_store(self):
        csv = "name,title\nJane Doe,VP Sales\nJohn Roe,AE"
        r = self._post(csv, dry_run=False)
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["summary"]["would_add"], 2)
        self.assertEqual(body["summary"]["committed"], True)
        contacts = self._list()
        names = {c["name"] for c in contacts}
        self.assertEqual(names, {"Jane Doe", "John Roe"})

    # ---- header normalisation --------------------------------------

    def test_header_synonyms(self):
        # "Full Name" → name; "Role" → title; "Owner" → mr_owner.
        csv = "Full Name,Role,Owner\nJane,CEO,Ben Ojuolape"
        r = self._post(csv, dry_run=False)
        c = self._list()[0]
        self.assertEqual(c["name"], "Jane")
        self.assertEqual(c["title"], "CEO")
        self.assertEqual(c["mr_owner"], "Ben Ojuolape")

    def test_header_case_and_space_insensitive(self):
        csv = "  NAME  ,  TITLE  \nJane,CEO"
        r = self._post(csv, dry_run=False)
        c = self._list()[0]
        self.assertEqual(c["name"], "Jane")
        self.assertEqual(c["title"], "CEO")

    def test_unknown_headers_listed_in_warnings(self):
        csv = "name,bogus_column,title\nJane,xxx,CEO"
        body = self._post(csv).get_json()
        self.assertIn("bogus_column", body["summary"]["unknown_headers"])
        # Row still parses fine — bogus column is ignored.
        self.assertEqual(body["summary"]["would_add"], 1)

    # ---- multi-tag splits ------------------------------------------

    def test_regions_comma_separated(self):
        csv = "name,regions\nJane,UK,EMEA"  # NO — comma's the delim
        # The proper format: quote the cell so CSV doesn't split.
        csv = 'name,regions\nJane,"UK,EMEA"'
        body = self._post(csv, dry_run=False).get_json()
        c = self._list()[0]
        self.assertEqual(set(c["regions"]), {"UK", "EMEA"})

    def test_regions_pipe_separated(self):
        csv = "name,regions\nJane,UK|EMEA"
        self._post(csv, dry_run=False)
        c = self._list()[0]
        self.assertEqual(set(c["regions"]), {"UK", "EMEA"})

    def test_regions_semicolon_separated(self):
        csv = "name,regions\nJane,UK;EMEA"
        self._post(csv, dry_run=False)
        c = self._list()[0]
        self.assertEqual(set(c["regions"]), {"UK", "EMEA"})

    def test_industries_multi(self):
        csv = "name,industries\nJane,QSR|Retail|Telecom"
        self._post(csv, dry_run=False)
        c = self._list()[0]
        self.assertEqual(set(c["industries"]), {"QSR", "Retail", "Telecom"})

    # ---- city → tags -----------------------------------------------

    def test_city_lands_in_tags(self):
        csv = "name,city\nJane,London"
        self._post(csv, dry_run=False)
        c = self._list()[0]
        self.assertIn("London", c["tags"])

    def test_city_combines_with_explicit_tags(self):
        csv = 'name,city,tags\nJane,London,priority|new'
        self._post(csv, dry_run=False)
        c = self._list()[0]
        # City + the two explicit tags.
        self.assertEqual(set(c["tags"]), {"London", "priority", "new"})

    # ---- update mode -----------------------------------------------

    def test_update_match_by_name_case_insensitive(self):
        import partner_contacts_store
        partner_contacts_store.save_contact(self.partner["id"], {
            "name": "Jane Doe", "title": "Old Title", "country": "USA"})
        csv = "name,title\nJANE DOE,New Title"
        body = self._post(csv, dry_run=False).get_json()
        self.assertEqual(body["summary"]["would_update"], 1)
        self.assertEqual(body["summary"]["would_add"], 0)
        # Title updated, country preserved (empty CSV cell doesn't clobber).
        c = self._list()[0]
        self.assertEqual(c["title"], "New Title")
        self.assertEqual(c["country"], "USA")

    def test_update_match_by_email(self):
        import partner_contacts_store
        partner_contacts_store.save_contact(self.partner["id"], {
            "name": "Jane", "email": "jane@example.com",
            "title": "Old"})
        # Different name, same email — should update the existing row.
        csv = "name,email,title\nJane Doe,jane@example.com,New"
        body = self._post(csv, dry_run=False).get_json()
        self.assertEqual(body["summary"]["would_update"], 1)
        contacts = self._list()
        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0]["title"], "New")
        # Name updated too (CSV provided a non-empty value).
        self.assertEqual(contacts[0]["name"], "Jane Doe")

    def test_empty_csv_cells_dont_clobber(self):
        """Update mode policy: an empty CSV cell means "no change",
        not "set to null". Otherwise bulk-updating titles via CSV
        would wipe every other field on those rows."""
        import partner_contacts_store
        partner_contacts_store.save_contact(self.partner["id"], {
            "name": "Jane", "title": "Old", "country": "USA",
            "regions": ["West Coast"], "seniority": "VP",
            "industries": ["QSR"]})
        # CSV only updates the title.
        csv = "name,title\nJane,New Title"
        self._post(csv, dry_run=False)
        c = self._list()[0]
        self.assertEqual(c["title"], "New Title")
        self.assertEqual(c["country"], "USA")           # preserved
        self.assertEqual(c["regions"], ["West Coast"])  # preserved
        self.assertEqual(c["seniority"], "VP")          # preserved
        self.assertEqual(c["industries"], ["QSR"])      # preserved

    def test_intra_csv_duplicate_collapses(self):
        """Same name twice in one CSV → the second row updates the
        first, NOT add two rows. Without this, a sloppy CSV could
        leave the partner roster with twins."""
        csv = "name,title\nJane,First\nJane,Second"
        self._post(csv, dry_run=False)
        contacts = self._list()
        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0]["title"], "Second")

    # ---- validation -------------------------------------------------

    def test_row_without_name_or_email_errors(self):
        csv = "name,email,title\n,,no identity"
        body = self._post(csv).get_json()
        self.assertEqual(body["summary"]["errored"], 1)
        self.assertEqual(body["summary"]["would_add"], 0)
        err_row = next(r for r in body["rows"] if r["action"] == "error")
        self.assertIn("name", err_row["reason"].lower())

    def test_empty_csv_400s(self):
        r = self._post("")
        self.assertEqual(r.status_code, 400)
        self.assertIn("required", r.get_json()["error"])

    def test_unknown_partner_404(self):
        r = self.client.post(
            "/api/partners/does-not-exist/contacts/import-csv",
            json={"csv": "name\nJane"})
        self.assertEqual(r.status_code, 404)

    def test_bom_tolerated(self):
        """Excel saves CSVs with a UTF-8 BOM. The parser strips it
        so the first header isn't mangled into a "﻿ name" key."""
        csv = "﻿name,title\nJane,CEO"
        body = self._post(csv, dry_run=False).get_json()
        self.assertEqual(body["summary"]["would_add"], 1)
        c = self._list()[0]
        self.assertEqual(c["name"], "Jane")

    # ---- end-to-end realistic --------------------------------------

    def test_realistic_hightouch_emea_roster(self):
        """The exact roster Ben asked me to add earlier — proves the
        same data we hand-built in scripts/add_hightouch_emea_contacts.py
        also lands cleanly via CSV import."""
        csv = (
            "name,title,country,city,regions,seniority\n"
            'Jennifer Timmerman,VP Sales Europe South & MENA,France,Paris,EMEA,VP\n'
            'Alexandre Poullard,Enterprise Account Executive EMEA,France,Paris,EMEA,Individual Contributor\n'
            'Alexandre Paradelo,"Account Executive, EMEA",France,,EMEA,Individual Contributor\n'
            'Hugo Boudry,Account Executive EMEA,Italy,,EMEA,Individual Contributor\n'
            'John Ade,Senior Enterprise Account Executive,United Kingdom,London,"UK|EMEA",Individual Contributor\n'
            'George Lynch,Director of Technology Partnerships,United Kingdom,London,"UK|EMEA",Director\n'
        )
        body = self._post(csv, dry_run=False).get_json()
        self.assertEqual(body["summary"]["would_add"], 6)
        self.assertEqual(body["summary"]["would_update"], 0)
        self.assertEqual(body["summary"]["errored"], 0)
        contacts = self._list()
        names = {c["name"] for c in contacts}
        self.assertEqual(names, {
            "Jennifer Timmerman", "Alexandre Poullard", "Alexandre Paradelo",
            "Hugo Boudry", "John Ade", "George Lynch"})
        # John Ade gets both regions.
        john = next(c for c in contacts if c["name"] == "John Ade")
        self.assertEqual(set(john["regions"]), {"UK", "EMEA"})
        self.assertIn("London", john["tags"])
        # VP seniority round-tripped.
        jen = next(c for c in contacts if c["name"] == "Jennifer Timmerman")
        self.assertEqual(jen["seniority"], "VP")


if __name__ == "__main__":
    unittest.main()
