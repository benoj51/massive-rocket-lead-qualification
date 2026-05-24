"""v1.0.0bl — stakeholder mapping + concurrent agencies tests.

Covers:
1. contacts_store stakeholder_role / influence / interest fields:
   accepted values, invalid normalised to None, backward-compat.
2. lead_agencies_store TYPE_CONCURRENT + embedded contacts array.
3. Live project detail endpoint includes contacts + agencies.
"""
from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# -----------------------------------------------------------------
# contacts_store stakeholder fields
# -----------------------------------------------------------------

class ContactsStoreStakeholderFieldsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["CONTACTS_STORE_DIR"] = self.tmp
        sys.modules.pop("contacts_store", None)
        import contacts_store
        self.store = contacts_store

    def tearDown(self):
        os.environ.pop("CONTACTS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_defaults_to_none(self):
        c = self.store.save_contact("acme",
                                      {"name": "Jane", "title": "CMO"})
        self.assertIsNone(c["stakeholder_role"])
        self.assertIsNone(c["influence"])
        self.assertIsNone(c["interest"])

    def test_accepts_valid_values(self):
        c = self.store.save_contact("acme", {
            "name": "Champ", "stakeholder_role": "champion",
            "influence": "high", "interest": "high"})
        self.assertEqual(c["stakeholder_role"], "champion")
        self.assertEqual(c["influence"], "high")
        self.assertEqual(c["interest"], "high")

    def test_invalid_values_normalise_to_none(self):
        c = self.store.save_contact("acme", {
            "name": "X", "stakeholder_role": "ceo",  # not in enum
            "influence": "very high", "interest": "meh"})
        self.assertIsNone(c["stakeholder_role"])
        self.assertIsNone(c["influence"])
        self.assertIsNone(c["interest"])

    def test_case_insensitive(self):
        c = self.store.save_contact("acme", {
            "name": "X", "stakeholder_role": "CHAMPION",
            "influence": "High", "interest": "MEDIUM"})
        self.assertEqual(c["stakeholder_role"], "champion")
        self.assertEqual(c["influence"], "high")
        self.assertEqual(c["interest"], "medium")

    def test_round_trips_through_list(self):
        a = self.store.save_contact("acme", {
            "name": "A", "stakeholder_role": "sponsor",
            "influence": "high", "interest": "high"})
        b = self.store.save_contact("acme", {
            "name": "B", "stakeholder_role": "blocker",
            "influence": "high", "interest": "low"})
        rows = self.store.list_contacts("acme")
        by_name = {r["name"]: r for r in rows}
        self.assertEqual(by_name["A"]["stakeholder_role"], "sponsor")
        self.assertEqual(by_name["B"]["stakeholder_role"], "blocker")
        self.assertEqual(by_name["B"]["interest"], "low")


# -----------------------------------------------------------------
# lead_agencies_store TYPE_CONCURRENT + contacts
# -----------------------------------------------------------------

class LeadAgenciesConcurrentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["LEAD_AGENCIES_STORE_DIR"] = self.tmp
        sys.modules.pop("lead_agencies_store", None)
        import lead_agencies_store
        self.store = lead_agencies_store

    def tearDown(self):
        os.environ.pop("LEAD_AGENCIES_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_concurrent_type_accepted(self):
        a = self.store.save_agency("shell", {
            "name": "Accenture", "type": "concurrent",
            "scope": "Broader digital transformation"})
        self.assertEqual(a["type"], "concurrent")

    def test_existing_types_still_work(self):
        """Backward-compat: existing types (incumbent/previous/
        competitor) keep working after the new enum addition."""
        for t in ("incumbent", "previous", "competitor"):
            a = self.store.save_agency("shell",
                                          {"name": f"Test {t}", "type": t})
            self.assertEqual(a["type"], t)

    def test_invalid_type_still_rejected(self):
        with self.assertRaises(self.store.LeadAgenciesStoreError):
            self.store.save_agency("shell",
                                      {"name": "X", "type": "made-up"})

    def test_embedded_contacts_persist(self):
        a = self.store.save_agency("shell", {
            "name": "Accenture", "type": "concurrent",
            "contacts": [
                {"name": "Alice Smith", "title": "Partner",
                 "email": "alice@accenture.com"},
                {"name": "Bob Jones", "title": "MD"},
            ]})
        self.assertEqual(len(a["contacts"]), 2)
        self.assertEqual(a["contacts"][0]["name"], "Alice Smith")
        self.assertEqual(a["contacts"][0]["email"], "alice@accenture.com")
        # IDs auto-assigned.
        self.assertTrue(all(c["id"] for c in a["contacts"]))

    def test_embedded_contacts_default_empty_list(self):
        a = self.store.save_agency("shell",
                                      {"name": "X", "type": "concurrent"})
        self.assertEqual(a["contacts"], [])

    def test_embedded_contacts_skip_nameless(self):
        a = self.store.save_agency("shell", {
            "name": "X", "type": "concurrent",
            "contacts": [
                {"name": "Real Person"},
                {"name": ""},  # skipped
                {"title": "Solo title — no name"},  # skipped
                "not a dict",  # skipped
            ]})
        self.assertEqual(len(a["contacts"]), 1)
        self.assertEqual(a["contacts"][0]["name"], "Real Person")

    def test_contacts_preserved_through_update(self):
        a = self.store.save_agency("shell", {
            "name": "X", "type": "concurrent",
            "contacts": [{"name": "Alice"}]})
        # Re-save with scope change but no contacts field — should
        # preserve existing contacts via _normalise's fallback to
        # `existing or {}`.contacts.
        updated = self.store.save_agency("shell", {
            **a, "scope": "Updated scope"})
        self.assertEqual(updated["scope"], "Updated scope")
        self.assertEqual(len(updated["contacts"]), 1)
        self.assertEqual(updated["contacts"][0]["name"], "Alice")


# -----------------------------------------------------------------
# Live project detail endpoint includes contacts + agencies
# -----------------------------------------------------------------

class LiveProjectDetailEnrichmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["LIVE_PROJECTS_STORE_DIR"] = os.path.join(cls.tmp, "lp")
        os.environ["LIVE_PROJECT_OKRS_STORE_DIR"] = os.path.join(cls.tmp, "okrs")
        os.environ["CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "c")
        os.environ["LEAD_AGENCIES_STORE_DIR"] = os.path.join(cls.tmp, "ag")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "live_projects_store",
                    "live_project_okrs_store",
                    "contacts_store", "lead_agencies_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("LIVE_PROJECTS_STORE_DIR", "LIVE_PROJECT_OKRS_STORE_DIR",
                  "CONTACTS_STORE_DIR", "LEAD_AGENCIES_STORE_DIR",
                  "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        # Wipe everything per test.
        import live_projects_store, contacts_store, lead_agencies_store
        for f in live_projects_store._store_dir().glob("*.json"):
            f.unlink()
        for f in contacts_store._store_dir().glob("*.json"):
            f.unlink()
        for f in lead_agencies_store._store_dir().glob("*.json"):
            f.unlink()

    def test_detail_includes_contacts_and_agencies(self):
        import live_projects_store, contacts_store, lead_agencies_store
        # Seed: a live project, two contacts on the lead, one
        # concurrent agency.
        project = live_projects_store.create("shell-lead", "Shell Loyalty")
        contacts_store.save_contact("shell-lead", {
            "name": "Champion", "stakeholder_role": "champion",
            "influence": "high", "interest": "high"})
        contacts_store.save_contact("shell-lead", {
            "name": "Blocker", "stakeholder_role": "blocker",
            "influence": "high", "interest": "low"})
        lead_agencies_store.save_agency("shell-lead", {
            "name": "Accenture", "type": "concurrent",
            "scope": "Digital transformation",
            "contacts": [{"name": "Alice", "title": "Partner"}]})
        with patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.get_page.return_value = {
                "id": "shell-lead", "company": "Shell"}
            body = self.client.get(
                f"/api/live-projects/{project['id']}").get_json()
        self.assertEqual(body["project"]["name"], "Shell Loyalty")
        self.assertEqual(body["project"]["company"], "Shell")
        # Contacts include stakeholder fields.
        contact_names = {c["name"] for c in body["contacts"]}
        self.assertEqual(contact_names, {"Champion", "Blocker"})
        champ = next(c for c in body["contacts"] if c["name"] == "Champion")
        self.assertEqual(champ["stakeholder_role"], "champion")
        self.assertEqual(champ["influence"], "high")
        # Agencies include the concurrent type + embedded contact.
        self.assertEqual(len(body["agencies"]), 1)
        ag = body["agencies"][0]
        self.assertEqual(ag["type"], "concurrent")
        self.assertEqual(ag["scope"], "Digital transformation")
        self.assertEqual(len(ag["contacts"]), 1)
        self.assertEqual(ag["contacts"][0]["name"], "Alice")


if __name__ == "__main__":
    unittest.main()
