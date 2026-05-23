"""v1.0.0al — notifications store + endpoint tests.

Covers:
- store: notify, list (sorted), unread_count, mark_read, mark_all_read,
  ring-buffer cap, empty-recipient no-op
- endpoints: GET /api/notifications, GET unread-count, POST <id>/read,
  POST read-all, and the auto-fire path when a partner-contact's
  mr_owner changes.
"""
from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class NotificationsStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["NOTIFICATIONS_STORE_DIR"] = self.tmp
        sys.modules.pop("notifications_store", None)
        import notifications_store
        self.store = notifications_store

    def tearDown(self):
        os.environ.pop("NOTIFICATIONS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_notify_returns_normalized_row(self):
        n = self.store.notify_assignment(
            "Ben Ojuolape",
            kind="assigned_lead",
            title="You were assigned Acme",
            body="by Thierry",
            link={"kind": "lead", "lead_id": "abc"},
            actor="Thierry Sequeira",
        )
        self.assertIsNotNone(n)
        self.assertEqual(n["recipient"], "Ben Ojuolape")
        self.assertEqual(n["recipient_slug"], "ben-ojuolape")
        self.assertEqual(n["type"], "assigned_lead")
        self.assertIsNone(n["read_at"])
        self.assertTrue(n["id"])
        self.assertTrue(n["created_at"].endswith("Z"))

    def test_empty_recipient_is_noop(self):
        self.assertIsNone(self.store.notify_assignment(
            "", kind="info", title="x"))
        self.assertIsNone(self.store.notify_assignment(
            "   ", kind="info", title="x"))

    def test_list_for_returns_newest_first(self):
        self.store.notify_assignment("Ben", kind="info", title="first")
        # Force a different timestamp on the second one so sort order is
        # deterministic — the store uses second resolution.
        time.sleep(1.05)
        self.store.notify_assignment("Ben", kind="info", title="second")
        items = self.store.list_for("Ben")
        self.assertEqual([i["title"] for i in items], ["second", "first"])

    def test_unread_filter(self):
        a = self.store.notify_assignment("Ben", kind="info", title="A")
        self.store.notify_assignment("Ben", kind="info", title="B")
        self.store.mark_read(a["id"], recipient="Ben")
        unread = self.store.list_for("Ben", unread_only=True)
        self.assertEqual([i["title"] for i in unread], ["B"])

    def test_unread_count(self):
        self.store.notify_assignment("Ben", kind="info", title="A")
        self.store.notify_assignment("Ben", kind="info", title="B")
        self.assertEqual(self.store.unread_count("Ben"), 2)
        n = self.store.list_for("Ben")[0]
        self.store.mark_read(n["id"], recipient="Ben")
        self.assertEqual(self.store.unread_count("Ben"), 1)

    def test_mark_read_idempotent(self):
        n = self.store.notify_assignment("Ben", kind="info", title="A")
        self.assertTrue(self.store.mark_read(n["id"], recipient="Ben"))
        # Second call returns False — already read.
        self.assertFalse(self.store.mark_read(n["id"], recipient="Ben"))

    def test_mark_all_read(self):
        for i in range(5):
            self.store.notify_assignment("Ben", kind="info", title=f"#{i}")
        marked = self.store.mark_all_read("Ben")
        self.assertEqual(marked, 5)
        self.assertEqual(self.store.unread_count("Ben"), 0)
        # Second call: nothing left to flip.
        self.assertEqual(self.store.mark_all_read("Ben"), 0)

    def test_ring_buffer_cap(self):
        # Write 210 notifications; only the newest 200 should survive.
        for i in range(210):
            self.store.notify_assignment("Ben", kind="info", title=f"#{i:03d}")
        items = self.store.list_for("Ben", limit=500)
        self.assertEqual(len(items), 200)
        titles = [i["title"] for i in items]
        # Newest first means #209 is at index 0; oldest survivor is #010.
        self.assertEqual(titles[0], "#209")
        self.assertEqual(titles[-1], "#010")

    def test_per_recipient_isolation(self):
        self.store.notify_assignment("Ben", kind="info", title="ben-only")
        self.store.notify_assignment("Glenn", kind="info", title="glenn-only")
        ben = [i["title"] for i in self.store.list_for("Ben")]
        glenn = [i["title"] for i in self.store.list_for("Glenn")]
        self.assertEqual(ben, ["ben-only"])
        self.assertEqual(glenn, ["glenn-only"])

    def test_mark_read_wrong_recipient_no_match(self):
        n = self.store.notify_assignment("Ben", kind="info", title="A")
        # Marking with the wrong recipient slug should fail silently.
        self.assertFalse(self.store.mark_read(n["id"], recipient="Glenn"))
        self.assertEqual(self.store.unread_count("Ben"), 1)


class NotificationsEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["NOTIFICATIONS_STORE_DIR"] = os.path.join(cls.tmp, "n")
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
                  "PARTNER_CONTACTS_STORE_DIR", "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        # Fresh per-test: clear any notifications from the prior test.
        import notifications_store
        notifications_store.clear("Ben Ojuolape")
        notifications_store.clear("Glenn Bonforte")

    def test_list_requires_recipient(self):
        r = self.client.get("/api/notifications")
        self.assertEqual(r.status_code, 400)

    def test_list_returns_empty_payload_for_unknown_recipient(self):
        r = self.client.get("/api/notifications?recipient=Nobody")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["items"], [])
        self.assertEqual(body["unread_count"], 0)

    def test_list_returns_seeded_notifications(self):
        import notifications_store
        notifications_store.notify_assignment(
            "Ben Ojuolape", kind="assigned_lead", title="Acme")
        r = self.client.get("/api/notifications?recipient=Ben%20Ojuolape")
        body = r.get_json()
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["title"], "Acme")
        self.assertEqual(body["unread_count"], 1)

    def test_mark_read_endpoint(self):
        import notifications_store
        n = notifications_store.notify_assignment(
            "Ben Ojuolape", kind="info", title="x")
        r = self.client.post(
            f"/api/notifications/{n['id']}/read",
            json={"recipient": "Ben Ojuolape"})
        body = r.get_json()
        self.assertTrue(body["updated"])
        self.assertEqual(body["unread_count"], 0)

    def test_mark_all_read_endpoint(self):
        import notifications_store
        notifications_store.notify_assignment("Ben Ojuolape", kind="info", title="A")
        notifications_store.notify_assignment("Ben Ojuolape", kind="info", title="B")
        r = self.client.post(
            "/api/notifications/read-all",
            json={"recipient": "Ben Ojuolape"})
        body = r.get_json()
        self.assertEqual(body["marked"], 2)
        self.assertEqual(body["unread_count"], 0)

    def test_unread_count_endpoint(self):
        import notifications_store
        notifications_store.notify_assignment("Ben Ojuolape", kind="info", title="x")
        r = self.client.get("/api/notifications/unread-count?recipient=Ben%20Ojuolape")
        self.assertEqual(r.get_json()["unread_count"], 1)

    def test_partner_contact_reassignment_fires_notification(self):
        # Seed a partner + contact with one owner; reassign via PATCH;
        # the new owner should pick up a notification.
        self.client.post("/api/partners", json={"name": "Braze"})
        create = self.client.post(
            "/api/partners/braze/contacts",
            json={"name": "Marina Klusas", "mr_owner": "Glenn Bonforte"})
        contact_id = create.get_json()["contact"]["id"]
        # Glenn shouldn't have a "you were assigned" notification from the
        # initial create (we only fire on mr_owner CHANGES, not on first
        # set). Verify that, then trigger a reassign and check Ben got one.
        self.assertEqual(
            self.client.get("/api/notifications?recipient=Glenn%20Bonforte")
                       .get_json()["items"], [])
        self.client.patch(
            f"/api/partners/braze/contacts/{contact_id}",
            json={"mr_owner": "Ben Ojuolape"})
        items = self.client.get(
            "/api/notifications?recipient=Ben%20Ojuolape").get_json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["type"], "assigned_partner_contact")
        self.assertIn("Marina Klusas", items[0]["title"])
        self.assertIn("Braze", items[0]["title"])
        self.assertEqual(items[0]["link"]["partner_id"], "braze")
        self.assertEqual(items[0]["link"]["contact_id"], contact_id)
        self.assertIn("Reassigned from Glenn Bonforte", items[0]["body"])

    def test_partner_contact_same_owner_no_notification(self):
        """PATCHing without changing mr_owner shouldn't fire a notification."""
        self.client.post("/api/partners", json={"name": "Braze"})
        create = self.client.post(
            "/api/partners/braze/contacts",
            json={"name": "X", "mr_owner": "Ben Ojuolape"})
        contact_id = create.get_json()["contact"]["id"]
        self.client.patch(
            f"/api/partners/braze/contacts/{contact_id}",
            json={"title": "VP"})
        items = self.client.get(
            "/api/notifications?recipient=Ben%20Ojuolape").get_json()["items"]
        self.assertEqual(items, [])

    # v1.0.0ao: cover the lead-PATCH notify path -----------------------
    # The lead endpoint relies on NotionSync which we can't reach in
    # tests, so we patch the two methods it uses (get_page for the
    # owner peek, update_page for the write) and confirm a reassignment
    # fires a bell notification.

    def test_lead_reassignment_fires_notification(self):
        import notifications_store
        from unittest.mock import patch
        # Server module's NotionSync is what server.api_lead_update
        # instantiates — patch it there.
        with patch.object(self.server, "NotionSync") as MockSync:
            instance = MockSync.return_value
            instance.get_page.return_value = {
                "id": "page123", "owner": "Glenn Bonforte",
                "company": "Acme Corp",
            }
            instance.update_page.return_value = {
                "lead": {
                    "id": "page123", "owner": "Ben Ojuolape",
                    "company": "Acme Corp",
                },
            }
            r = self.client.patch("/api/lead/page123",
                                    json={"owner": "Ben Ojuolape"})
            self.assertEqual(r.status_code, 200)
        items = notifications_store.list_for("Ben Ojuolape")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["type"], "assigned_lead")
        self.assertIn("Acme Corp", items[0]["title"])
        self.assertEqual(items[0]["link"]["lead_id"], "page123")
        self.assertIn("Reassigned from Glenn Bonforte", items[0]["body"])

    def test_lead_no_owner_change_no_notification(self):
        import notifications_store
        from unittest.mock import patch
        with patch.object(self.server, "NotionSync") as MockSync:
            instance = MockSync.return_value
            instance.get_page.return_value = {
                "id": "page123", "owner": "Ben Ojuolape",
                "company": "Acme",
            }
            instance.update_page.return_value = {
                "lead": {"id": "page123", "owner": "Ben Ojuolape",
                          "company": "Acme"},
            }
            self.client.patch("/api/lead/page123",
                                json={"owner": "Ben Ojuolape"})
        self.assertEqual(notifications_store.list_for("Ben Ojuolape"), [])


if __name__ == "__main__":
    unittest.main()
