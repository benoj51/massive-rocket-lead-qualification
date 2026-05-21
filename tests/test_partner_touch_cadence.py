"""v0.10.0z — touch cadence + overdue surfacing for partner contacts."""
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


class TouchCadenceStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["PARTNER_CONTACTS_STORE_DIR"] = os.path.join(self.tmp, "pc")
        for mod in ("partner_contacts_store", "project_store"):
            sys.modules.pop(mod, None)

    def tearDown(self):
        os.environ.pop("PARTNER_CONTACTS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_cadence_30_days(self):
        import partner_contacts_store
        c = partner_contacts_store.save_contact("braze", {"name": "x"})
        self.assertEqual(c["cadence_days"], 30)
        self.assertIsNone(c["last_touched_at"])

    def test_cadence_clamped_to_range(self):
        import partner_contacts_store
        c1 = partner_contacts_store.save_contact("braze", {"name": "a", "cadence_days": 0})
        c2 = partner_contacts_store.save_contact("braze", {"name": "b", "cadence_days": 5000})
        self.assertEqual(c1["cadence_days"], 1)
        self.assertEqual(c2["cadence_days"], 365)

    def test_annotate_never_touched_recently_added_is_not_overdue(self):
        """A contact added today with 30-day cadence isn't yet overdue."""
        import partner_contacts_store
        c = partner_contacts_store.save_contact("braze", {"name": "fresh"})
        annotated = partner_contacts_store.annotate_touch_state(c)
        self.assertFalse(annotated["overdue"])
        self.assertIsNone(annotated["days_since_touch"])  # never explicitly touched

    def test_annotate_never_touched_old_contact_is_overdue(self):
        """If a contact was added 90 days ago with 30-day cadence and
        never touched, the baseline-from-added_at rule marks them overdue."""
        import partner_contacts_store
        # Hand-craft an old added_at
        old_iso = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec="seconds").replace("+00:00", "Z")
        c = partner_contacts_store.save_contact("braze", {
            "name": "stale", "cadence_days": 30, "added_at": old_iso,
        })
        annotated = partner_contacts_store.annotate_touch_state(c)
        self.assertTrue(annotated["overdue"])
        self.assertLess(annotated["days_until_due"], 0)

    def test_touch_contact_bumps_last_touched(self):
        import partner_contacts_store
        c = partner_contacts_store.save_contact("braze", {"name": "T"})
        touched = partner_contacts_store.touch_contact("braze", c["id"])
        self.assertIsNotNone(touched["last_touched_at"])

    def test_touched_contact_no_longer_overdue(self):
        """Touch a 90-day-old contact → overdue=False on next annotate."""
        import partner_contacts_store
        old_iso = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec="seconds").replace("+00:00", "Z")
        c = partner_contacts_store.save_contact("braze", {
            "name": "y", "cadence_days": 30, "added_at": old_iso,
        })
        partner_contacts_store.touch_contact("braze", c["id"])
        reloaded = partner_contacts_store.list_contacts("braze")[0]
        self.assertFalse(reloaded["overdue"])

    def test_overdue_contacts_filters_by_active_status(self):
        """A contact with status='left' is excluded from overdue even if
        the dates would say otherwise."""
        import partner_contacts_store
        old_iso = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec="seconds").replace("+00:00", "Z")
        partner_contacts_store.save_contact("braze", {
            "name": "left",
            "added_at": old_iso,
            "cadence_days": 30,
            "status": "left",
        })
        partner_contacts_store.save_contact("braze", {
            "name": "active",
            "added_at": old_iso,
            "cadence_days": 30,
            "status": "active",
        })
        overdue = partner_contacts_store.overdue_contacts("braze")
        self.assertEqual(len(overdue), 1)
        self.assertEqual(overdue[0]["name"], "active")


class OverdueEndpointTests(unittest.TestCase):
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
        for k in ("PARTNERS_STORE_PATH", "PARTNER_CONTACTS_STORE_DIR",
                  "PARTNER_NOTES_STORE_DIR"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _seed_overdue(self):
        self.client.post("/api/partners", json={"name": "Braze"})
        old_iso = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec="seconds").replace("+00:00", "Z")
        # Bypass endpoint to set added_at directly via store
        import partner_contacts_store
        partner_contacts_store.save_contact("braze", {
            "name": "Stale Person", "added_at": old_iso, "cadence_days": 30,
            "status": "active", "mr_owner": "Ben",
        })

    def test_overdue_endpoint_returns_stale(self):
        self._seed_overdue()
        r = self.client.get("/api/partners/overdue")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertGreaterEqual(body["count"], 1)
        self.assertEqual(body["overdue"][0]["name"], "Stale Person")
        # Cross-partner enrichment
        self.assertEqual(body["overdue"][0]["partner_name"], "Braze")

    def test_overdue_endpoint_filters_by_owner(self):
        self._seed_overdue()
        r = self.client.get("/api/partners/overdue?owner=Someone%20Else")
        self.assertEqual(r.get_json()["count"], 0)
        r = self.client.get("/api/partners/overdue?owner=Ben")
        self.assertEqual(r.get_json()["count"], 1)

    def test_touch_endpoint_bumps_last_touched(self):
        self._seed_overdue()
        import partner_contacts_store
        contact = partner_contacts_store.list_contacts("braze")[0]
        r = self.client.post(f"/api/partners/braze/contacts/{contact['id']}/touch")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.get_json()["contact"]["overdue"])

    def test_note_add_also_bumps_touch(self):
        self._seed_overdue()
        import partner_contacts_store
        contact = partner_contacts_store.list_contacts("braze")[0]
        r = self.client.post(
            f"/api/partners/braze/contacts/{contact['id']}/notes",
            json={"content": "Caught up at the conference", "type": "intro"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIsNotNone(body.get("contact"))
        self.assertFalse(body["contact"]["overdue"])


if __name__ == "__main__":
    unittest.main()
