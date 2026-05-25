"""v0.10.0y — Partners CRM stores + endpoints."""
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


class PartnersStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["PARTNERS_STORE_PATH"] = os.path.join(self.tmp, "partners.json")
        for mod in ("partners_store", "project_store"):
            sys.modules.pop(mod, None)

    def tearDown(self):
        os.environ.pop("PARTNERS_STORE_PATH", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_list_returns_empty(self):
        import partners_store
        self.assertEqual(partners_store.list_partners(), [])

    def test_save_and_get_partner(self):
        import partners_store
        saved = partners_store.save_partner({"name": "Braze",
                                             "type": "Technology partner",
                                             "url": "braze.com"})
        self.assertEqual(saved["id"], "braze")
        self.assertEqual(saved["name"], "Braze")
        found = partners_store.get_partner("braze")
        self.assertIsNotNone(found)
        self.assertEqual(found["name"], "Braze")

    def test_save_requires_name(self):
        import partners_store
        with self.assertRaises(partners_store.PartnersStoreError):
            partners_store.save_partner({"type": "Reseller"})

    def test_update_preserves_created_at(self):
        import partners_store, time
        first = partners_store.save_partner({"name": "Hightouch"})
        # v1.0.0cg: was sleep(0.01) when _now() had microsecond precision.
        # Aligned to second precision system-wide; sleep needs to span
        # a tick boundary for the timestamp to actually bump.
        time.sleep(1.1)
        second = partners_store.save_partner({"id": first["id"], "name": "Hightouch",
                                              "description": "Reverse ETL"})
        self.assertEqual(first["created_at"], second["created_at"])
        self.assertNotEqual(first["updated_at"], second["updated_at"])
        self.assertEqual(second["description"], "Reverse ETL")

    def test_delete_partner(self):
        import partners_store
        partners_store.save_partner({"name": "Segment"})
        self.assertTrue(partners_store.delete_partner("segment"))
        self.assertIsNone(partners_store.get_partner("segment"))
        # Idempotent delete
        self.assertFalse(partners_store.delete_partner("segment"))

    def test_list_sorted_alpha(self):
        import partners_store
        for name in ("Snowflake", "Braze", "mParticle"):
            partners_store.save_partner({"name": name})
        names = [p["name"] for p in partners_store.list_partners()]
        self.assertEqual(names, ["Braze", "mParticle", "Snowflake"])


class PartnerContactsStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["PARTNER_CONTACTS_STORE_DIR"] = os.path.join(self.tmp, "pc")
        for mod in ("partner_contacts_store", "project_store"):
            sys.modules.pop(mod, None)

    def tearDown(self):
        os.environ.pop("PARTNER_CONTACTS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_contact_with_full_metadata(self):
        import partner_contacts_store
        c = partner_contacts_store.save_contact("braze", {
            "name": "Glenn Bonforte",
            "title": "Partner Success",
            "email": "glenn@braze.com",
            "territory": "Strategic Enterprise",
            "region": "East Coast",
            "country": "United States",
            "industries": ["QSR", "Retail"],
            "mr_owner": "Ben Ojuolape",
        })
        self.assertEqual(c["partner_id"], "braze")
        self.assertEqual(c["territory"], "Strategic Enterprise")
        self.assertEqual(set(c["industries"]), {"QSR", "Retail"})

    def test_save_requires_name_or_email(self):
        import partner_contacts_store
        with self.assertRaises(partner_contacts_store.PartnerContactsStoreError):
            partner_contacts_store.save_contact("braze", {"title": "VP"})

    def test_industries_string_parsed(self):
        """Tolerant input — accept comma-separated string from CSV imports."""
        import partner_contacts_store
        c = partner_contacts_store.save_contact("braze", {
            "name": "Marina Klusas",
            "industries": "QSR, C-Store / Gas, Retail",
        })
        self.assertIn("QSR", c["industries"])
        self.assertIn("C-Store / Gas", c["industries"])
        self.assertEqual(len(c["industries"]), 3)

    def test_list_active_first(self):
        import partner_contacts_store
        partner_contacts_store.save_contact("braze",
            {"name": "Active Person", "status": "active"})
        partner_contacts_store.save_contact("braze",
            {"name": "Left Person", "status": "left"})
        names = [c["name"] for c in partner_contacts_store.list_contacts("braze")]
        self.assertEqual(names[0], "Active Person")

    def test_partners_isolated_by_id(self):
        """Saving contacts under one partner shouldn't bleed into another."""
        import partner_contacts_store
        partner_contacts_store.save_contact("braze", {"name": "A"})
        partner_contacts_store.save_contact("hightouch", {"name": "B"})
        self.assertEqual(len(partner_contacts_store.list_contacts("braze")), 1)
        self.assertEqual(len(partner_contacts_store.list_contacts("hightouch")), 1)

    def test_delete_contact(self):
        import partner_contacts_store
        c = partner_contacts_store.save_contact("braze", {"name": "Glenn"})
        self.assertTrue(partner_contacts_store.delete_contact("braze", c["id"]))
        self.assertIsNone(partner_contacts_store.get_contact("braze", c["id"]))


class PartnerNotesStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["PARTNER_NOTES_STORE_DIR"] = os.path.join(self.tmp, "pn")
        for mod in ("partner_notes_store", "project_store"):
            sys.modules.pop(mod, None)

    def tearDown(self):
        os.environ.pop("PARTNER_NOTES_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_add_note_requires_content(self):
        import partner_notes_store
        with self.assertRaises(partner_notes_store.PartnerNotesStoreError):
            partner_notes_store.add_note("braze", "c1", {"type": "call"})

    def test_notes_listed_newest_first(self):
        import partner_notes_store, time
        partner_notes_store.add_note("braze", "c1", {"content": "First touch"})
        time.sleep(0.001)
        partner_notes_store.add_note("braze", "c1", {"content": "Second touch"})
        notes = partner_notes_store.list_notes("braze", "c1")
        self.assertEqual(notes[0]["content"], "Second touch")

    def test_cascade_delete_for_contact(self):
        import partner_notes_store
        partner_notes_store.add_note("braze", "c1", {"content": "hi"})
        self.assertTrue(partner_notes_store.delete_all_for_contact("braze", "c1"))
        self.assertEqual(partner_notes_store.list_notes("braze", "c1"), [])


class PartnersEndpointsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["PARTNERS_STORE_PATH"] = os.path.join(cls.tmp, "partners.json")
        os.environ["PARTNER_CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "pc")
        os.environ["PARTNER_NOTES_STORE_DIR"] = os.path.join(cls.tmp, "pn")
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "partners_store", "partner_contacts_store",
                    "partner_notes_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("PARTNERS_STORE_PATH", None)
        os.environ.pop("PARTNER_CONTACTS_STORE_DIR", None)
        os.environ.pop("PARTNER_NOTES_STORE_DIR", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_enums_endpoint(self):
        r = self.client.get("/api/partners/enums")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn("Strategic Enterprise", body["territories"])
        self.assertIn("UK", body["regions"])
        self.assertIn("QSR", body["industries"])
        self.assertIn("C-Store / Gas", body["industries"])

    def test_create_list_get_partner(self):
        r = self.client.post("/api/partners", json={"name": "Iterable",
                                                    "type": "Technology partner"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()["partner"]["id"], "iterable")

        lst = self.client.get("/api/partners")
        self.assertEqual(lst.status_code, 200)
        partners = lst.get_json()["partners"]
        names = [p["name"] for p in partners]
        self.assertIn("Iterable", names)

        get_one = self.client.get("/api/partners/iterable")
        self.assertEqual(get_one.status_code, 200)
        self.assertEqual(get_one.get_json()["partner"]["name"], "Iterable")

    def test_save_partner_contact_and_list(self):
        self.client.post("/api/partners", json={"name": "mParticle"})
        c = self.client.post("/api/partners/mparticle/contacts",
                             json={"name": "Jamie MacDow",
                                   "title": "Account Director",
                                   "territory": "Enterprise",
                                   "region": "UK",
                                   "industries": ["QSR", "Retail"]})
        self.assertEqual(c.status_code, 200)
        body = c.get_json()
        self.assertIn("contact", body)
        # List back
        lst = self.client.get("/api/partners/mparticle/contacts")
        contacts = lst.get_json()["contacts"]
        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0]["territory"], "Enterprise")
        self.assertEqual(set(contacts[0]["industries"]), {"QSR", "Retail"})

    def test_add_and_list_contact_notes(self):
        self.client.post("/api/partners", json={"name": "Talon.one"})
        contact = self.client.post("/api/partners/talon_one/contacts",
                                   json={"name": "Sample"}).get_json()["contact"]
        n = self.client.post(
            f"/api/partners/talon_one/contacts/{contact['id']}/notes",
            json={"content": "Intro call booked for Tuesday"})
        self.assertEqual(n.status_code, 200)
        notes = self.client.get(
            f"/api/partners/talon_one/contacts/{contact['id']}/notes"
        ).get_json()["notes"]
        self.assertEqual(len(notes), 1)
        self.assertIn("Intro call", notes[0]["content"])

    def test_cannot_delete_partner_with_contacts(self):
        self.client.post("/api/partners", json={"name": "Snowflake"})
        self.client.post("/api/partners/snowflake/contacts",
                         json={"name": "Pinned"})
        r = self.client.delete("/api/partners/snowflake")
        self.assertEqual(r.status_code, 409)
        self.assertIn("contacts", r.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
