"""v1.0.0as — /api/lead/<id>/engagement-timeline tests.

Unified reverse-chronological feed merging per-contact stakeholder
notes, lead-level calls, and last-touched timestamps. Powers the
Timeline view in the lead drawer's Account section.
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


class EngagementTimelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "contacts")
        os.environ["LEAD_CONTACT_NOTES_STORE_DIR"] = os.path.join(cls.tmp, "notes")
        os.environ["CALLS_STORE_DIR"] = os.path.join(cls.tmp, "calls")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "contacts_store", "calls_store",
                    "lead_contact_notes_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("CONTACTS_STORE_DIR", "LEAD_CONTACT_NOTES_STORE_DIR",
                  "CALLS_STORE_DIR", "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        # Each test: wipe and re-seed under a fresh lead slug.
        # Slug-per-test isolation avoids cross-contamination from
        # an earlier test's cached files.
        self.lead_id = f"acme-{int(time.time() * 1000)}"
        import contacts_store, calls_store, lead_contact_notes_store
        self.contacts = contacts_store
        self.calls = calls_store
        self.notes = lead_contact_notes_store

    # -----------------------------------------------------------------
    # Endpoint shape + empty case
    # -----------------------------------------------------------------

    def test_empty_account_returns_empty_items(self):
        r = self.client.get(
            f"/api/lead/{self.lead_id}/engagement-timeline")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["items"], [])
        self.assertEqual(body["stats"]["total"], 0)
        self.assertEqual(body["stats"]["contacts_total"], 0)

    def test_contacts_with_no_engagement(self):
        """Contacts exist but no notes/calls/touches yet."""
        self.contacts.save_contact(self.lead_id,
                                     {"name": "Jane Doe"})
        r = self.client.get(
            f"/api/lead/{self.lead_id}/engagement-timeline")
        body = r.get_json()
        self.assertEqual(body["items"], [])
        self.assertEqual(body["stats"]["contacts_total"], 1)
        self.assertEqual(body["stats"]["contacts_with_engagement"], 0)

    # -----------------------------------------------------------------
    # Mixed events sorted newest first
    # -----------------------------------------------------------------

    def test_mixed_event_sources_sorted_newest_first(self):
        c1 = self.contacts.save_contact(self.lead_id,
                                          {"name": "Jane Doe"})
        # Sleep 1.1s between events so the per-second timestamps differ
        # and the sort order is deterministic.
        self.notes.add_note(self.lead_id, c1["id"],
                             {"type": "touch", "content": "First note"})
        time.sleep(1.1)
        self.calls.add_call(self.lead_id, {
            "type": "discovery", "title": "Discovery #1",
            "content": "First call",
        })
        time.sleep(1.1)
        self.notes.add_note(self.lead_id, c1["id"],
                             {"type": "touch", "content": "Latest note"})

        r = self.client.get(
            f"/api/lead/{self.lead_id}/engagement-timeline")
        body = r.get_json()
        titles_or_previews = [i["preview"] for i in body["items"]
                                if i["preview"]]
        # Newest first: "Latest note" should be at index 0
        self.assertEqual(titles_or_previews[0], "Latest note")
        # Stats sanity
        self.assertGreaterEqual(body["stats"]["notes"], 2)
        self.assertGreaterEqual(body["stats"]["calls"], 1)

    def test_long_content_is_truncated_with_ellipsis(self):
        c = self.contacts.save_contact(self.lead_id, {"name": "X"})
        long = "a" * 500
        self.notes.add_note(self.lead_id, c["id"],
                             {"type": "touch", "content": long})
        r = self.client.get(
            f"/api/lead/{self.lead_id}/engagement-timeline")
        preview = r.get_json()["items"][0]["preview"]
        self.assertLessEqual(len(preview), 241)  # 240 + ellipsis
        self.assertTrue(preview.endswith("…"))

    # -----------------------------------------------------------------
    # Contact attribution
    # -----------------------------------------------------------------

    def test_note_carries_contact_id_and_name(self):
        c = self.contacts.save_contact(self.lead_id,
                                         {"name": "Marina Klusas"})
        self.notes.add_note(self.lead_id, c["id"],
                             {"type": "touch", "content": "hello"})
        r = self.client.get(
            f"/api/lead/{self.lead_id}/engagement-timeline")
        item = r.get_json()["items"][0]
        self.assertEqual(item["contact_id"], c["id"])
        self.assertEqual(item["contact_name"], "Marina Klusas")

    def test_call_with_matching_attendee_attributes_to_contact(self):
        """A call whose first attendee matches a contact name should
        be attributed to that contact in the timeline."""
        c = self.contacts.save_contact(self.lead_id,
                                         {"name": "Marina Klusas"})
        self.calls.add_call(self.lead_id, {
            "type": "discovery", "title": "Disco",
            "content": "call notes here",
            "attendees": ["Marina Klusas"],
        })
        r = self.client.get(
            f"/api/lead/{self.lead_id}/engagement-timeline")
        item = next(i for i in r.get_json()["items"] if i["kind"] == "call")
        self.assertEqual(item["contact_id"], c["id"])

    def test_call_without_matching_attendee_has_no_contact(self):
        self.contacts.save_contact(self.lead_id, {"name": "Marina Klusas"})
        self.calls.add_call(self.lead_id, {
            "type": "note", "title": "Internal sync",
            "content": "internal MR thinking",
        })
        r = self.client.get(
            f"/api/lead/{self.lead_id}/engagement-timeline")
        item = next(i for i in r.get_json()["items"] if i["kind"] == "call")
        self.assertIsNone(item["contact_id"])

    # -----------------------------------------------------------------
    # Touch de-dup
    # -----------------------------------------------------------------

    def test_touch_dedup_when_note_fired_the_touch(self):
        """Adding a note auto-bumps the contact's last_touched_at to
        the same iso. We shouldn't surface a duplicate "Touched" event
        in addition to the note — the note already represents that
        engagement."""
        c = self.contacts.save_contact(self.lead_id, {"name": "X"})
        # The notes endpoint touches the contact, so let's simulate
        # that via the API rather than the store (so the timestamps
        # match what production produces).
        self.client.post(
            f"/api/contacts/{self.lead_id}/{c['id']}/notes",
            json={"type": "touch", "content": "hi"})
        r = self.client.get(
            f"/api/lead/{self.lead_id}/engagement-timeline")
        items = r.get_json()["items"]
        # One note, no extra touch event
        kinds = [i["kind"] for i in items]
        self.assertIn("note", kinds)
        self.assertNotIn("touch", kinds)

    # -----------------------------------------------------------------
    # Limit clamping
    # -----------------------------------------------------------------

    def test_limit_clamping(self):
        c = self.contacts.save_contact(self.lead_id, {"name": "X"})
        for i in range(15):
            self.notes.add_note(self.lead_id, c["id"],
                                 {"type": "touch",
                                  "content": f"note {i}"})
        r = self.client.get(
            f"/api/lead/{self.lead_id}/engagement-timeline?limit=5")
        items = r.get_json()["items"]
        self.assertEqual(len(items), 5)

    def test_default_limit_is_100(self):
        c = self.contacts.save_contact(self.lead_id, {"name": "X"})
        for i in range(120):
            self.notes.add_note(self.lead_id, c["id"],
                                 {"type": "touch",
                                  "content": f"note {i}"})
        r = self.client.get(
            f"/api/lead/{self.lead_id}/engagement-timeline")
        self.assertEqual(len(r.get_json()["items"]), 100)

    def test_bad_limit_falls_back(self):
        c = self.contacts.save_contact(self.lead_id, {"name": "X"})
        self.notes.add_note(self.lead_id, c["id"],
                             {"type": "touch", "content": "x"})
        r = self.client.get(
            f"/api/lead/{self.lead_id}/engagement-timeline?limit=not-a-num")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.get_json()["items"]), 1)

    # -----------------------------------------------------------------
    # Stats correctness
    # -----------------------------------------------------------------

    def test_stats_count_contacts_with_engagement(self):
        a = self.contacts.save_contact(self.lead_id, {"name": "A"})
        self.contacts.save_contact(self.lead_id, {"name": "B"})  # unengaged
        self.contacts.save_contact(self.lead_id, {"name": "C"})  # unengaged
        self.notes.add_note(self.lead_id, a["id"],
                             {"type": "touch", "content": "x"})
        body = self.client.get(
            f"/api/lead/{self.lead_id}/engagement-timeline").get_json()
        self.assertEqual(body["stats"]["contacts_total"], 3)
        self.assertEqual(body["stats"]["contacts_with_engagement"], 1)


if __name__ == "__main__":
    unittest.main()
