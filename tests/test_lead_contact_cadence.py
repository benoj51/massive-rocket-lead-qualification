"""v1.0.0a (Tier 1c) — touch cadence + status lifecycle on LEAD contacts.

Brings the lead-side contact store to parity with the partner-side
contact store: cadence_days, last_touched_at, status, annotate_touch_state,
touch_contact, overdue_contacts, and a /touch endpoint.
"""
from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class LeadContactCadenceStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["CONTACTS_STORE_DIR"] = self.tmp
        for mod in ("contacts_store", "project_store"):
            sys.modules.pop(mod, None)

    def tearDown(self):
        os.environ.pop("CONTACTS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_defaults_cadence_30_status_active(self):
        import contacts_store
        c = contacts_store.save_contact("yum", {"name": "Jane"})
        self.assertEqual(c["cadence_days"], 30)
        self.assertEqual(c["status"], "active")
        self.assertIsNone(c["last_touched_at"])

    def test_cadence_clamped_to_range(self):
        import contacts_store
        c1 = contacts_store.save_contact("yum", {"name": "a", "cadence_days": 0})
        c2 = contacts_store.save_contact("yum", {"name": "b", "cadence_days": 9999})
        self.assertEqual(c1["cadence_days"], 1)
        self.assertEqual(c2["cadence_days"], 365)

    def test_unknown_status_falls_back_to_active(self):
        import contacts_store
        c = contacts_store.save_contact("yum", {"name": "x", "status": "wat"})
        self.assertEqual(c["status"], "active")

    def test_annotate_recent_add_not_overdue(self):
        import contacts_store
        c = contacts_store.save_contact("yum", {"name": "fresh"})
        annotated = contacts_store.annotate_touch_state(c)
        self.assertFalse(annotated["overdue"])
        self.assertIsNone(annotated["days_since_touch"])

    def test_annotate_old_never_touched_is_overdue(self):
        import contacts_store
        old_iso = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec="seconds").replace("+00:00", "Z")
        c = contacts_store.save_contact("yum", {
            "name": "stale", "cadence_days": 30, "added_at": old_iso,
        })
        annotated = contacts_store.annotate_touch_state(c)
        self.assertTrue(annotated["overdue"])

    def test_touch_contact_clears_overdue(self):
        import contacts_store
        old_iso = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec="seconds").replace("+00:00", "Z")
        c = contacts_store.save_contact("yum", {
            "name": "x", "cadence_days": 30, "added_at": old_iso,
        })
        contacts_store.touch_contact("yum", c["id"])
        reloaded = contacts_store.list_contacts("yum")[0]
        self.assertFalse(reloaded["overdue"])
        self.assertIsNotNone(reloaded["last_touched_at"])

    def test_overdue_contacts_excludes_left_status(self):
        import contacts_store
        old_iso = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec="seconds").replace("+00:00", "Z")
        contacts_store.save_contact("yum", {
            "name": "Active", "added_at": old_iso, "cadence_days": 30, "status": "active",
        })
        contacts_store.save_contact("yum", {
            "name": "Left", "added_at": old_iso, "cadence_days": 30, "status": "left",
        })
        overdue = contacts_store.overdue_contacts("yum")
        names = [c["name"] for c in overdue]
        self.assertIn("Active", names)
        self.assertNotIn("Left", names)

    def test_cross_lead_overdue_returns_all_active(self):
        import contacts_store
        old_iso = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec="seconds").replace("+00:00", "Z")
        contacts_store.save_contact("yum", {"name": "Y1", "added_at": old_iso, "cadence_days": 30})
        contacts_store.save_contact("kfc", {"name": "K1", "added_at": old_iso, "cadence_days": 30})
        overdue = contacts_store.overdue_contacts(lead_id=None)
        leads = {c["lead_id"] for c in overdue}
        self.assertEqual(leads, {"yum", "kfc"})


class LeadContactTouchEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "contacts")
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "contacts_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("CONTACTS_STORE_DIR", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_touch_endpoint_404_when_missing(self):
        r = self.client.post("/api/contacts/nobody/abc123/touch")
        self.assertEqual(r.status_code, 404)

    def test_touch_endpoint_bumps_last_touched(self):
        # Seed a stale contact
        import contacts_store
        old_iso = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec="seconds").replace("+00:00", "Z")
        c = contacts_store.save_contact("acme", {
            "name": "Stale", "added_at": old_iso, "cadence_days": 30,
        })
        r = self.client.post(f"/api/contacts/acme/{c['id']}/touch")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertFalse(body["contact"]["overdue"])
        self.assertIsNotNone(body["contact"]["last_touched_at"])

    def test_overdue_endpoint_cross_lead(self):
        import contacts_store
        old_iso = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec="seconds").replace("+00:00", "Z")
        contacts_store.save_contact("over1", {"name": "A", "added_at": old_iso, "cadence_days": 30})
        contacts_store.save_contact("over2", {"name": "B", "added_at": old_iso, "cadence_days": 30})
        r = self.client.get("/api/contacts/overdue")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertGreaterEqual(body["count"], 2)


if __name__ == "__main__":
    unittest.main()
