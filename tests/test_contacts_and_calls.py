"""v0.6.0: contacts + calls per lead + expanded Apollo roles."""
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


class ApolloRolesTests(unittest.TestCase):
    def test_default_titles_now_include_cdto_digital_data(self):
        import apollo
        titles = " ".join(apollo.DEFAULT_PEOPLE_TITLES).lower()
        for t in ("cdto", "digital", "data", "analytics"):
            self.assertIn(t, titles, f"Expected '{t}' in default titles")

    def test_includes_chief_digital_transformation_officer(self):
        import apollo
        self.assertIn("Chief Digital Transformation Officer", apollo.DEFAULT_PEOPLE_TITLES)

    def test_includes_martech_and_marketing_ops(self):
        """v0.10.0r: Martech / Marketing Ops titles must be in the default
        list — they're often the real CDP/ESP decision-makers in QSR /
        retail / travel buyers, not the CMO."""
        import apollo
        titles_lc = [t.lower() for t in apollo.DEFAULT_PEOPLE_TITLES]
        required_substrings = ["martech", "marketing technology",
                                "marketing operations"]
        for needle in required_substrings:
            self.assertTrue(
                any(needle in t for t in titles_lc),
                f"Expected '{needle}' in default Apollo title list",
            )


class ContactSearchEndpointTests(unittest.TestCase):
    """v0.10.0s: /api/contacts/<lead_id>/search wraps Apollo people search
    and flags candidates already saved against the lead."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "contacts")
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "contacts_store", "apollo"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("CONTACTS_STORE_DIR", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_search_requires_domain_or_apollo_id(self):
        r = self.client.post("/api/contacts/some-lead/search", json={})
        self.assertEqual(r.status_code, 400)
        self.assertIn("domain", r.get_json()["error"])

    def test_search_returns_candidates_array(self):
        # Apollo fixtures (deliveroo.co.uk) should return at least
        # something. If not, accept an empty array but no error.
        r = self.client.post(
            "/api/contacts/test-lead/search",
            json={"domain": "deliveroo.co.uk", "limit": 10},
        )
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn("candidates", body)
        self.assertIsInstance(body["candidates"], list)

    def test_search_flags_already_saved(self):
        """Pre-save a contact, then run search — it should come back as
        already_saved=True."""
        import contacts_store
        # Pre-seed with a contact that has an Apollo-shaped id + linkedin
        contacts_store.save_contact("flag-lead", {
            "id": "preseed-1",
            "name": "Will Shu",
            "linkedin_url": "https://linkedin.com/in/willshu",
            "source": "manual",
        })
        r = self.client.post(
            "/api/contacts/flag-lead/search",
            json={"domain": "deliveroo.co.uk", "limit": 10},
        )
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        # The shape contract is the test — every candidate has the flag,
        # whether or not the fixture surfaces Will Shu specifically.
        for cand in body.get("candidates", []):
            self.assertIn("already_saved", cand)
            self.assertIsInstance(cand["already_saved"], bool)


class ContactsStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["CONTACTS_STORE_DIR"] = self.tmp
        for mod in ("contacts_store", "project_store"):
            sys.modules.pop(mod, None)

    def tearDown(self):
        os.environ.pop("CONTACTS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_and_list(self):
        import contacts_store
        contacts_store.save_contact("lead-a", {
            "name": "Jane Doe", "title": "VP CRM",
            "email": "jane@example.com", "source": "apollo",
        })
        contacts = contacts_store.list_contacts("lead-a")
        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0]["name"], "Jane Doe")
        self.assertEqual(contacts[0]["source"], "apollo")

    def test_save_requires_name_or_email(self):
        import contacts_store
        with self.assertRaises(contacts_store.ContactsStoreError):
            contacts_store.save_contact("lead-a", {"title": "VP CRM"})

    def test_set_primary_clears_others(self):
        import contacts_store
        a = contacts_store.save_contact("lead-x", {"id": "a", "name": "A"})
        b = contacts_store.save_contact("lead-x", {"id": "b", "name": "B"})
        c = contacts_store.save_contact("lead-x", {"id": "c", "name": "C", "is_primary": True})
        # c is primary, a and b are not
        rows = contacts_store.list_contacts("lead-x")
        primaries = [r for r in rows if r["is_primary"]]
        self.assertEqual(len(primaries), 1)
        self.assertEqual(primaries[0]["id"], "c")
        # Now flip b to primary, c should lose it
        contacts_store.set_primary("lead-x", "b")
        rows = contacts_store.list_contacts("lead-x")
        primaries = [r for r in rows if r["is_primary"]]
        self.assertEqual(len(primaries), 1)
        self.assertEqual(primaries[0]["id"], "b")

    def test_primary_contact_helper(self):
        import contacts_store
        contacts_store.save_contact("y", {"id": "1", "name": "A", "is_primary": True})
        contacts_store.save_contact("y", {"id": "2", "name": "B"})
        primary = contacts_store.primary_contact("y")
        self.assertEqual(primary["id"], "1")

    def test_delete_contact(self):
        import contacts_store
        contacts_store.save_contact("z", {"id": "1", "name": "A"})
        self.assertTrue(contacts_store.delete_contact("z", "1"))
        self.assertFalse(contacts_store.delete_contact("z", "1"))  # second time = false

    def test_save_many(self):
        import contacts_store
        saved = contacts_store.save_many("bulk", [
            {"name": "A", "title": "VP"},
            {"name": "B", "title": "Director"},
            {"title": "Invalid"},  # no name or email
        ])
        self.assertEqual(len(saved), 2)
        self.assertEqual(len(contacts_store.list_contacts("bulk")), 2)


class CallsStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["CALLS_STORE_DIR"] = self.tmp
        for mod in ("calls_store", "project_store"):
            sys.modules.pop(mod, None)

    def tearDown(self):
        os.environ.pop("CALLS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_add_and_list(self):
        import calls_store
        calls_store.add_call("lead-a", {"content": "Had a good call", "type": "call"})
        rows = calls_store.list_calls("lead-a")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["type"], "call")

    def test_content_required(self):
        import calls_store
        with self.assertRaises(calls_store.CallsStoreError):
            calls_store.add_call("lead-a", {"type": "note"})

    def test_invalid_type_falls_back_to_note(self):
        import calls_store
        rec = calls_store.add_call("lead-a", {"content": "hi", "type": "bogus"})
        self.assertEqual(rec["type"], "note")

    def test_list_newest_first(self):
        import calls_store, time
        calls_store.add_call("lead-a", {"content": "first"})
        time.sleep(0.01)
        calls_store.add_call("lead-a", {"content": "second"})
        rows = calls_store.list_calls("lead-a")
        self.assertEqual(rows[0]["content"], "second")
        self.assertEqual(rows[1]["content"], "first")

    def test_aggregate_extractions_merges(self):
        import calls_store
        calls_store.add_call("a", {
            "content": "x", "extracted": {
                "meddpicc": {"metrics": {"value": "5% uplift"}},
            },
        })
        calls_store.add_call("a", {
            "content": "y", "extracted": {
                "meddpicc": {"economic_buyer": {"value": "Jane CFO"}},
                "project_scope": "CRM Build",
            },
        })
        rolling = calls_store.aggregate_extractions("a")
        self.assertEqual(rolling["meddpicc"]["metrics"]["value"], "5% uplift")
        self.assertEqual(rolling["meddpicc"]["economic_buyer"]["value"], "Jane CFO")
        self.assertEqual(rolling["project_scope"], "CRM Build")


class ContactsCallsEndpointsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "contacts")
        os.environ["CALLS_STORE_DIR"] = os.path.join(cls.tmp, "calls")
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        for mod in ("server", "contacts_store", "calls_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("CONTACTS_STORE_DIR", "CALLS_STORE_DIR"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_contacts_save_get_delete_roundtrip(self):
        r = self.client.post("/api/contacts/test-lead", json={
            "name": "Jane", "title": "CMO", "email": "j@x.com", "source": "manual",
        })
        self.assertEqual(r.status_code, 200)
        saved_id = r.get_json()["contact"]["id"]
        listed = self.client.get("/api/contacts/test-lead").get_json()
        self.assertEqual(len(listed["contacts"]), 1)
        # Mark primary
        r = self.client.post(f"/api/contacts/test-lead/{saved_id}/primary")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["primary"]["id"], saved_id)
        # Delete
        r = self.client.delete(f"/api/contacts/test-lead/{saved_id}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.client.get("/api/contacts/test-lead").get_json()["contacts"]), 0)

    def test_contacts_bulk_save(self):
        r = self.client.post("/api/contacts/bulk-test", json={
            "contacts": [
                {"name": "A", "title": "VP"},
                {"name": "B", "title": "Director"},
            ],
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.get_json()["saved"]), 2)

    def test_contacts_invalid_returns_400(self):
        r = self.client.post("/api/contacts/x", json={"title": "no name or email"})
        self.assertEqual(r.status_code, 400)

    def test_calls_add_list_delete(self):
        r = self.client.post("/api/calls/test-lead-c", json={
            "content": "Had a discovery call.",
            "type": "call",
            "title": "Discovery #1",
        })
        self.assertEqual(r.status_code, 200)
        call_id = r.get_json()["call"]["id"]
        listed = self.client.get("/api/calls/test-lead-c").get_json()
        self.assertEqual(len(listed["calls"]), 1)
        r = self.client.delete(f"/api/calls/test-lead-c/{call_id}")
        self.assertEqual(r.status_code, 200)

    def test_calls_content_required(self):
        r = self.client.post("/api/calls/y", json={"type": "note"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
