"""v0.11.0 — partner contacts ↔ lead assignments."""
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


class AssignmentsStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["LEAD_PARTNER_ASSIGN_DIR"] = os.path.join(self.tmp, "lpa")
        for mod in ("lead_partner_assignments", "project_store"):
            sys.modules.pop(mod, None)

    def tearDown(self):
        os.environ.pop("LEAD_PARTNER_ASSIGN_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_lead_has_no_assignments(self):
        import lead_partner_assignments as lpa
        self.assertEqual(lpa.list_for_lead("yum"), [])

    def test_assign_creates_row(self):
        import lead_partner_assignments as lpa
        row = lpa.assign("yum", "braze", "abc123", assigned_by="ben",
                        note="Strategic AE")
        self.assertEqual(row["partner_id"], "braze")
        self.assertEqual(row["contact_id"], "abc123")
        self.assertEqual(row["assigned_by"], "ben")
        self.assertEqual(row["note"], "Strategic AE")
        rows = lpa.list_for_lead("yum")
        self.assertEqual(len(rows), 1)

    def test_assign_idempotent_updates_note(self):
        import lead_partner_assignments as lpa
        first = lpa.assign("yum", "braze", "abc")
        second = lpa.assign("yum", "braze", "abc", note="updated")
        rows = lpa.list_for_lead("yum")
        self.assertEqual(len(rows), 1)
        self.assertEqual(second["note"], "updated")
        # assigned_at preserved
        self.assertEqual(first["assigned_at"], second["assigned_at"])

    def test_assign_requires_ids(self):
        import lead_partner_assignments as lpa
        with self.assertRaises(lpa.AssignmentsStoreError):
            lpa.assign("yum", "", "abc")
        with self.assertRaises(lpa.AssignmentsStoreError):
            lpa.assign("yum", "braze", "")

    def test_unassign_removes_row(self):
        import lead_partner_assignments as lpa
        lpa.assign("yum", "braze", "abc")
        self.assertTrue(lpa.unassign("yum", "braze", "abc"))
        self.assertEqual(lpa.list_for_lead("yum"), [])
        # Idempotent
        self.assertFalse(lpa.unassign("yum", "braze", "abc"))

    def test_list_for_contact_finds_cross_lead(self):
        """One partner contact assigned to multiple leads should appear
        in list_for_contact for both."""
        import lead_partner_assignments as lpa
        lpa.assign("yum", "braze", "marina")
        lpa.assign("rbi", "braze", "marina")
        lpa.assign("yum", "snowflake", "other")
        leads = lpa.list_for_contact("braze", "marina")
        self.assertEqual(len(leads), 2)
        lead_ids = {l["lead_id"] for l in leads}
        self.assertEqual(lead_ids, {"yum", "rbi"})

    def test_multiple_partners_per_lead(self):
        """A lead can have many partner contacts assigned — Braze AE +
        Snowflake SE + Hightouch lead all at once."""
        import lead_partner_assignments as lpa
        lpa.assign("yum", "braze", "marina")
        lpa.assign("yum", "snowflake", "alex")
        lpa.assign("yum", "hightouch", "kim")
        rows = lpa.list_for_lead("yum")
        self.assertEqual(len(rows), 3)
        partners = {r["partner_id"] for r in rows}
        self.assertEqual(partners, {"braze", "snowflake", "hightouch"})


class AssignmentsEndpointsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["LEAD_PARTNER_ASSIGN_DIR"] = os.path.join(cls.tmp, "lpa")
        os.environ["PARTNERS_STORE_PATH"] = os.path.join(cls.tmp, "partners.json")
        os.environ["PARTNER_CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "pc")
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "lead_partner_assignments", "partners_store",
                    "partner_contacts_store", "partner_notes_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("LEAD_PARTNER_ASSIGN_DIR", "PARTNERS_STORE_PATH",
                  "PARTNER_CONTACTS_STORE_DIR"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _seed_partner_with_contact(self, partner_name="Braze",
                                   contact_name="Marina Klusas"):
        self.client.post("/api/partners", json={"name": partner_name})
        partner_id = partner_name.lower().replace(".", "_").replace("!", "")
        r = self.client.post(f"/api/partners/{partner_id}/contacts",
                              json={"name": contact_name, "territory": "Strategic Enterprise",
                                    "region": "East Coast", "industries": ["QSR"]})
        contact = r.get_json()["contact"]
        return partner_id, contact["id"]

    def test_assign_single_partner_contact_to_lead(self):
        partner_id, contact_id = self._seed_partner_with_contact()
        r = self.client.post("/api/lead/yum/partner-contacts",
                             json={"partner_id": partner_id, "contact_id": contact_id,
                                   "note": "Strategic AE for Yum"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["count"], 1)
        # List back
        r = self.client.get("/api/lead/yum/partner-contacts")
        body = r.get_json()
        self.assertEqual(body["count"], 1)
        a = body["assignments"][0]
        self.assertEqual(a["partner_name"], "Braze")
        self.assertEqual(a["contact"]["name"], "Marina Klusas")
        self.assertEqual(a["contact"]["territory"], "Strategic Enterprise")
        self.assertEqual(a["note"], "Strategic AE for Yum")

    def test_bulk_assign(self):
        p1, c1 = self._seed_partner_with_contact("Braze", "Marina")
        p2, c2 = self._seed_partner_with_contact("Snowflake", "Alex")
        r = self.client.post("/api/lead/yum/partner-contacts", json={
            "assignments": [
                {"partner_id": p1, "contact_id": c1},
                {"partner_id": p2, "contact_id": c2},
            ]
        })
        self.assertEqual(r.get_json()["count"], 2)

    def test_unassign_endpoint(self):
        # Use a fresh lead id so this test doesn't see leftovers from
        # earlier tests in the class (which share the setUpClass tmpdir).
        partner_id, contact_id = self._seed_partner_with_contact()
        self.client.post("/api/lead/unassign-target/partner-contacts",
                          json={"partner_id": partner_id, "contact_id": contact_id})
        r = self.client.delete(
            f"/api/lead/unassign-target/partner-contacts/{partner_id}/{contact_id}")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["removed"])
        # Gone from list
        rows = self.client.get("/api/lead/unassign-target/partner-contacts").get_json()["assignments"]
        self.assertEqual(rows, [])

    def test_assignment_missing_ids_returns_400(self):
        r = self.client.post("/api/lead/yum/partner-contacts", json={})
        self.assertEqual(r.status_code, 400)

    def test_assigned_leads_reverse_lookup(self):
        partner_id, contact_id = self._seed_partner_with_contact()
        self.client.post("/api/lead/yum/partner-contacts",
                          json={"partner_id": partner_id, "contact_id": contact_id})
        self.client.post("/api/lead/rbi/partner-contacts",
                          json={"partner_id": partner_id, "contact_id": contact_id})
        r = self.client.get(
            f"/api/partners/{partner_id}/contacts/{contact_id}/assigned-leads")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["count"], 2)
        lead_ids = {l["lead_id"] for l in body["leads"]}
        self.assertEqual(lead_ids, {"yum", "rbi"})


if __name__ == "__main__":
    unittest.main()
