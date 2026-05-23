"""v1.0.0ax — bulk-update endpoint for partner contacts.

Adds POST /api/partners/<id>/contacts/bulk-update so the AE can
select multiple rows in the partner contacts table and apply the
same field update to all of them in one round-trip. Honours the
same notification contract as the single-PATCH endpoint: a bulk
mr_owner reassign fires one notification per newly-owned contact.
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


class PartnerContactsBulkUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["NOTIFICATIONS_STORE_DIR"] = os.path.join(cls.tmp, "notif")
        os.environ["PARTNERS_STORE_PATH"] = os.path.join(cls.tmp, "p.json")
        os.environ["PARTNER_CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "pc")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "notifications_store",
                    "partners_store", "partner_contacts_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("NOTIFICATIONS_STORE_DIR", "PARTNERS_STORE_PATH",
                  "PARTNER_CONTACTS_STORE_DIR",
                  "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        # Fresh partner + 3 contacts per test for isolation.
        import partner_contacts_store, partners_store, notifications_store
        # Wipe partner contacts file if it exists.
        p_file = Path(os.environ["PARTNERS_STORE_PATH"])
        if p_file.exists():
            p_file.unlink()
        pc_dir = Path(os.environ["PARTNER_CONTACTS_STORE_DIR"])
        if pc_dir.exists():
            shutil.rmtree(pc_dir)
        notifications_store.clear("Ben Ojuolape")
        notifications_store.clear("Glenn Bonforte")
        self.client.post("/api/partners", json={"name": "Braze"})
        self.c1 = partner_contacts_store.save_contact(
            "braze", {"name": "Alice",
                       "mr_owner": "Glenn Bonforte",
                       "status": "active"})
        self.c2 = partner_contacts_store.save_contact(
            "braze", {"name": "Bob",
                       "mr_owner": "Glenn Bonforte",
                       "status": "active"})
        self.c3 = partner_contacts_store.save_contact(
            "braze", {"name": "Carol",
                       "mr_owner": "Glenn Bonforte",
                       "status": "active"})

    # ----- validation -------------------------------------------------

    def test_missing_contact_ids_returns_400(self):
        r = self.client.post(
            "/api/partners/braze/contacts/bulk-update",
            json={"updates": {"tier": "Tier 1"}})
        self.assertEqual(r.status_code, 400)
        self.assertIn("contact_ids", r.get_json()["error"])

    def test_empty_contact_ids_returns_400(self):
        r = self.client.post(
            "/api/partners/braze/contacts/bulk-update",
            json={"contact_ids": [], "updates": {"tier": "Tier 1"}})
        self.assertEqual(r.status_code, 400)

    def test_missing_updates_returns_400(self):
        r = self.client.post(
            "/api/partners/braze/contacts/bulk-update",
            json={"contact_ids": [self.c1["id"]]})
        self.assertEqual(r.status_code, 400)

    def test_disallowed_field_rejected(self):
        """Allowlist gates writes — free-text fields (name, email)
        aren't bulk-settable to prevent accidental wipeouts."""
        r = self.client.post(
            "/api/partners/braze/contacts/bulk-update",
            json={"contact_ids": [self.c1["id"]],
                   "updates": {"name": "Overwritten"}})
        self.assertEqual(r.status_code, 400)
        self.assertIn("not allowed", r.get_json()["error"])

    def test_more_than_200_contacts_rejected(self):
        ids = [f"id-{i}" for i in range(201)]
        r = self.client.post(
            "/api/partners/braze/contacts/bulk-update",
            json={"contact_ids": ids, "updates": {"tier": "Tier 1"}})
        self.assertEqual(r.status_code, 400)

    # ----- happy path -------------------------------------------------

    def test_bulk_set_tier_updates_all(self):
        ids = [self.c1["id"], self.c2["id"], self.c3["id"]]
        r = self.client.post(
            "/api/partners/braze/contacts/bulk-update",
            json={"contact_ids": ids,
                   "updates": {"tier": "Tier 1"}})
        body = r.get_json()
        self.assertEqual(body["updated"], 3)
        self.assertEqual(body["errors"], [])
        # Verify persistence.
        import partner_contacts_store
        contacts = partner_contacts_store.list_contacts("braze")
        for c in contacts:
            self.assertEqual(c["tier"], "Tier 1")

    def test_bulk_set_status_dormant(self):
        ids = [self.c1["id"], self.c2["id"]]
        self.client.post(
            "/api/partners/braze/contacts/bulk-update",
            json={"contact_ids": ids,
                   "updates": {"status": "dormant"}})
        import partner_contacts_store
        contacts = {c["id"]: c
                     for c in partner_contacts_store.list_contacts("braze")}
        self.assertEqual(contacts[self.c1["id"]]["status"], "dormant")
        self.assertEqual(contacts[self.c2["id"]]["status"], "dormant")
        # c3 untouched
        self.assertEqual(contacts[self.c3["id"]]["status"], "active")

    def test_missing_contact_id_lands_in_errors(self):
        """Partial fan-out: bad ids land in errors, good ones still save."""
        r = self.client.post(
            "/api/partners/braze/contacts/bulk-update",
            json={"contact_ids": [self.c1["id"], "does-not-exist"],
                   "updates": {"tier": "Tier 2"}})
        body = r.get_json()
        self.assertEqual(body["updated"], 1)
        self.assertEqual(len(body["errors"]), 1)
        self.assertEqual(body["errors"][0]["contact_id"], "does-not-exist")
        self.assertEqual(body["errors"][0]["error"], "not_found")

    # ----- notifications ---------------------------------------------

    def test_bulk_reassign_fires_per_contact_notifications(self):
        """Reassigning 3 contacts from Glenn to Ben should drop 3
        notifications in Ben's bell, one per contact, each linking
        back to that specific contact."""
        ids = [self.c1["id"], self.c2["id"], self.c3["id"]]
        body = self.client.post(
            "/api/partners/braze/contacts/bulk-update",
            json={"contact_ids": ids,
                   "updates": {"mr_owner": "Ben Ojuolape"}}).get_json()
        self.assertEqual(body["updated"], 3)
        self.assertEqual(body["notified"], 3)
        items = self.client.get(
            "/api/notifications?recipient=Ben%20Ojuolape").get_json()["items"]
        self.assertEqual(len(items), 3)
        # Each carries a distinct contact_id link.
        linked_contacts = {n["link"]["contact_id"] for n in items}
        self.assertEqual(linked_contacts, set(ids))
        # Body mentions the bulk source.
        for n in items:
            self.assertIn("Bulk-reassigned from Glenn Bonforte", n["body"])

    def test_bulk_reassign_skips_already_owned(self):
        """If a contact already has the new owner, no notification
        fires for them (idempotent bulk-set shouldn't spam)."""
        import partner_contacts_store
        # Pre-set c1's owner to Ben so it's a no-change.
        partner_contacts_store.save_contact("braze", {
            **self.c1, "mr_owner": "Ben Ojuolape",
        })
        body = self.client.post(
            "/api/partners/braze/contacts/bulk-update",
            json={"contact_ids": [self.c1["id"], self.c2["id"], self.c3["id"]],
                   "updates": {"mr_owner": "Ben Ojuolape"}}).get_json()
        # All 3 saved (idempotent), but only 2 notifications (c2 + c3).
        self.assertEqual(body["updated"], 3)
        self.assertEqual(body["notified"], 2)

    def test_bulk_tier_update_no_notifications(self):
        """Non-owner updates don't fire notifications."""
        self.client.post(
            "/api/partners/braze/contacts/bulk-update",
            json={"contact_ids": [self.c1["id"], self.c2["id"]],
                   "updates": {"tier": "Tier 1"}})
        items = self.client.get(
            "/api/notifications?recipient=Glenn%20Bonforte").get_json()["items"]
        self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()
