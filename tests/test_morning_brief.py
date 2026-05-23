"""v1.0.0bf — morning brief endpoint tests.

Aggregates today's notable signals into a single card at the top of
Home: engagement drops, todos due today + overdue, new assignment
notifications.
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


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _yesterday():
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


def _next_week():
    return (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")


class MorningBriefTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["NOTIFICATIONS_STORE_DIR"] = os.path.join(cls.tmp, "notif")
        os.environ["TODOS_STORE_DIR"] = os.path.join(cls.tmp, "todos")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "notifications_store", "todos_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("NOTIFICATIONS_STORE_DIR", "TODOS_STORE_DIR",
                  "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        import notifications_store, todos_store
        notifications_store.clear("Ben Ojuolape")
        for t in todos_store.list_for("Ben Ojuolape"):
            todos_store.delete("Ben Ojuolape", t["id"])

    def test_requires_owner(self):
        r = self.client.get("/api/home/morning-brief")
        self.assertEqual(r.status_code, 400)

    def test_empty_state(self):
        r = self.client.get("/api/home/morning-brief?owner=Ben%20Ojuolape")
        body = r.get_json()
        self.assertTrue(body["is_empty"])
        self.assertIsNone(body["headline"])
        self.assertEqual(body["engagement_drops"], [])
        self.assertEqual(body["todos_due_today"], [])
        self.assertEqual(body["todos_overdue"], [])
        self.assertEqual(body["new_assignments"], [])

    def test_engagement_drops_surfaced(self):
        import notifications_store
        notifications_store.notify_assignment(
            "Ben Ojuolape", kind="engagement_dropped",
            title="Acme dropped to cold",
            body="Fell from 75 to 35",
            link={"kind": "lead", "lead_id": "acme"})
        body = self.client.get(
            "/api/home/morning-brief?owner=Ben%20Ojuolape").get_json()
        self.assertFalse(body["is_empty"])
        self.assertEqual(len(body["engagement_drops"]), 1)
        self.assertIn("1 account", body["headline"])
        # Slim shape: notification_id, not id.
        self.assertIn("notification_id", body["engagement_drops"][0])
        self.assertEqual(body["engagement_drops"][0]["link"]["lead_id"],
                          "acme")

    def test_read_notifications_excluded(self):
        """Already-read engagement drops shouldn't reappear in the brief."""
        import notifications_store
        n = notifications_store.notify_assignment(
            "Ben Ojuolape", kind="engagement_dropped",
            title="x", body="y")
        notifications_store.mark_read(n["id"], recipient="Ben Ojuolape")
        body = self.client.get(
            "/api/home/morning-brief?owner=Ben%20Ojuolape").get_json()
        self.assertEqual(body["engagement_drops"], [])
        self.assertTrue(body["is_empty"])

    def test_todos_split_by_due_date(self):
        import todos_store
        todos_store.create("Ben Ojuolape", "Today task",
                            due_date=_today())
        todos_store.create("Ben Ojuolape", "Overdue task",
                            due_date=_yesterday())
        todos_store.create("Ben Ojuolape", "Future task",
                            due_date=_next_week())
        todos_store.create("Ben Ojuolape", "No due-date task")
        body = self.client.get(
            "/api/home/morning-brief?owner=Ben%20Ojuolape").get_json()
        self.assertEqual(len(body["todos_due_today"]), 1)
        self.assertEqual(body["todos_due_today"][0]["text"], "Today task")
        self.assertEqual(len(body["todos_overdue"]), 1)
        self.assertEqual(body["todos_overdue"][0]["text"], "Overdue task")
        self.assertEqual(body["todos_overdue"][0]["days_overdue"], 1)
        # No-due-date + future tasks DON'T surface — only actionable today.

    def test_completed_todos_excluded(self):
        import todos_store
        t = todos_store.create("Ben Ojuolape", "Done already",
                                 due_date=_yesterday())
        todos_store.update("Ben Ojuolape", t["id"], done=True)
        body = self.client.get(
            "/api/home/morning-brief?owner=Ben%20Ojuolape").get_json()
        self.assertEqual(body["todos_overdue"], [])

    def test_overdue_sorted_most_overdue_first(self):
        import todos_store
        five = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
        twenty = (datetime.now(timezone.utc) - timedelta(days=20)).strftime("%Y-%m-%d")
        todos_store.create("Ben Ojuolape", "5 days old", due_date=five)
        todos_store.create("Ben Ojuolape", "20 days old", due_date=twenty)
        body = self.client.get(
            "/api/home/morning-brief?owner=Ben%20Ojuolape").get_json()
        # Older (20d) first.
        self.assertEqual(body["todos_overdue"][0]["text"], "20 days old")

    def test_new_assignments_surfaced(self):
        import notifications_store
        notifications_store.notify_assignment(
            "Ben Ojuolape", kind="assigned_lead",
            title="You were assigned Acme",
            link={"kind": "lead", "lead_id": "acme"})
        notifications_store.notify_assignment(
            "Ben Ojuolape", kind="assigned_partner_contact",
            title="You were assigned Marina (Braze)",
            link={"kind": "partner_contact", "partner_id": "braze",
                   "contact_id": "marina"})
        body = self.client.get(
            "/api/home/morning-brief?owner=Ben%20Ojuolape").get_json()
        self.assertEqual(len(body["new_assignments"]), 2)
        self.assertIn("2 new assignments", body["headline"])

    def test_headline_combines_signal_counts(self):
        import notifications_store, todos_store
        notifications_store.notify_assignment(
            "Ben Ojuolape", kind="engagement_dropped", title="X drop")
        todos_store.create("Ben Ojuolape", "task", due_date=_today())
        body = self.client.get(
            "/api/home/morning-brief?owner=Ben%20Ojuolape").get_json()
        self.assertIn("1 account", body["headline"])
        self.assertIn("1 due today", body["headline"])


if __name__ == "__main__":
    unittest.main()
