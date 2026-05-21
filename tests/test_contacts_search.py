"""v1.0.0c (Tier 2a + 2b) — cross-surface contact search endpoint."""
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


class ContactsSearchEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "contacts")
        os.environ["PARTNERS_STORE_PATH"] = os.path.join(cls.tmp, "partners.json")
        os.environ["PARTNER_CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "pc")
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "contacts_store", "partners_store",
                    "partner_contacts_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()
        # Seed: 2 lead contacts + 2 partner contacts
        import contacts_store, partners_store, partner_contacts_store
        contacts_store.save_contact("yum", {
            "name": "Jane Doe", "title": "VP Marketing",
            "email": "jane@yum.com", "country": "United States",
        })
        contacts_store.save_contact("kfc", {
            "name": "Akira Tanaka", "title": "Head of CRM",
            "email": "akira@kfc.com", "country": "Japan",
        })
        partners_store.save_partner({"name": "Braze",
                                     "type": "Technology partner"})
        partners_store.save_partner({"name": "Snowflake"})
        partner_contacts_store.save_contact("braze", {
            "name": "Marina Klusas", "title": "Strategic AE",
            "territory": "Strategic Enterprise", "region": "East Coast",
            "industries": ["QSR", "Retail"],
            "mr_owner": "Ben Ojuolape",
        })
        partner_contacts_store.save_contact("snowflake", {
            "name": "Alex Smith", "title": "Sales Engineer",
            "territory": "Enterprise", "region": "West Coast",
            "industries": ["Travel & Hospitality"],
            "mr_owner": "Someone Else",
        })

    @classmethod
    def tearDownClass(cls):
        for k in ("CONTACTS_STORE_DIR", "PARTNERS_STORE_PATH",
                  "PARTNER_CONTACTS_STORE_DIR"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_empty_query_returns_both_surfaces(self):
        r = self.client.get("/api/contacts/search")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertGreaterEqual(len(body["lead"]), 2)
        self.assertGreaterEqual(len(body["partner"]), 2)
        # Each result is surface-tagged
        for c in body["lead"]:
            self.assertEqual(c["surface"], "lead")
            self.assertIn("parent_id", c)
        for c in body["partner"]:
            self.assertEqual(c["surface"], "partner")
            self.assertIn("parent_name", c)

    def test_query_matches_name(self):
        r = self.client.get("/api/contacts/search?q=marina")
        body = r.get_json()
        names = [c["name"] for c in body["partner"]]
        self.assertIn("Marina Klusas", names)
        # Marina is a partner contact, shouldn't appear in lead hits
        for c in body["lead"]:
            self.assertNotIn("Marina", c["name"])

    def test_query_matches_email(self):
        r = self.client.get("/api/contacts/search?q=akira@")
        body = r.get_json()
        names = [c["name"] for c in body["lead"]]
        self.assertIn("Akira Tanaka", names)

    def test_query_matches_country(self):
        r = self.client.get("/api/contacts/search?q=japan")
        body = r.get_json()
        names = [c["name"] for c in body["lead"]]
        self.assertIn("Akira Tanaka", names)

    def test_surface_filter_lead_only(self):
        r = self.client.get("/api/contacts/search?surface=lead")
        body = r.get_json()
        self.assertEqual(body["partner"], [])
        self.assertGreater(len(body["lead"]), 0)

    def test_surface_filter_partner_only(self):
        r = self.client.get("/api/contacts/search?surface=partner")
        body = r.get_json()
        self.assertEqual(body["lead"], [])
        self.assertGreater(len(body["partner"]), 0)

    def test_territory_filter_partner_only(self):
        """Territory is a partner-only field; filter should skip lead
        contacts entirely (they don't have the field)."""
        r = self.client.get("/api/contacts/search?territory=Strategic%20Enterprise")
        body = r.get_json()
        self.assertEqual(body["lead"], [])  # skipped because territory filter set
        names = [c["name"] for c in body["partner"]]
        self.assertIn("Marina Klusas", names)
        self.assertNotIn("Alex Smith", names)

    def test_region_filter(self):
        r = self.client.get("/api/contacts/search?region=East%20Coast")
        body = r.get_json()
        names = [c["name"] for c in body["partner"]]
        self.assertIn("Marina Klusas", names)
        self.assertNotIn("Alex Smith", names)

    def test_industry_filter(self):
        r = self.client.get("/api/contacts/search?industry=QSR")
        body = r.get_json()
        names = [c["name"] for c in body["partner"]]
        self.assertIn("Marina Klusas", names)
        self.assertNotIn("Alex Smith", names)

    def test_owner_filter_my_contacts(self):
        """'My contacts' workflow: filter by mr_owner contains."""
        r = self.client.get("/api/contacts/search?owner=Ben")
        body = r.get_json()
        # Lead contacts have no mr_owner field, so they're skipped
        self.assertEqual(body["lead"], [])
        names = [c["name"] for c in body["partner"]]
        self.assertIn("Marina Klusas", names)
        self.assertNotIn("Alex Smith", names)

    def test_combined_filters(self):
        r = self.client.get("/api/contacts/search?q=Klusas&territory=Strategic%20Enterprise")
        body = r.get_json()
        names = [c["name"] for c in body["partner"]]
        self.assertIn("Marina Klusas", names)

    def test_no_matches_returns_empty_lists(self):
        r = self.client.get("/api/contacts/search?q=zzzz-nobody-zzzz")
        body = r.get_json()
        self.assertEqual(body["lead"], [])
        self.assertEqual(body["partner"], [])
        self.assertEqual(body["total"], 0)


if __name__ == "__main__":
    unittest.main()
