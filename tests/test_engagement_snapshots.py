"""v1.0.0bc — engagement snapshots store + drop notification tests."""
from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _payload(score, band, *, contacts_total=5, contacts_engaged=3,
              events_30d=4):
    return {
        "score": score, "band": band,
        "signals": {
            "considered_contacts": contacts_total,
            "active_contacts":     contacts_engaged,
            "coverage_pct":        100 if contacts_engaged
                                      and contacts_engaged == contacts_total
                                      else int(100 * contacts_engaged
                                                   / max(1, contacts_engaged)),
            "events_30d":          events_30d,
        },
    }


class EngagementSnapshotsStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["ENGAGEMENT_SNAPSHOTS_STORE_DIR"] = self.tmp
        sys.modules.pop("engagement_snapshots_store", None)
        import engagement_snapshots_store
        self.store = engagement_snapshots_store

    def tearDown(self):
        os.environ.pop("ENGAGEMENT_SNAPSHOTS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ----- record + dedup per day -------------------------------------

    def test_record_first_snapshot(self):
        s = self.store.record("acme", _payload(80, "strong"),
                                today_iso="2026-05-23")
        self.assertEqual(s["date"], "2026-05-23")
        self.assertEqual(s["score"], 80)
        self.assertEqual(s["band"], "strong")
        history = self.store.history("acme")
        self.assertEqual(len(history), 1)

    def test_same_day_record_updates_in_place(self):
        """Two calls on the same date → only one entry, second overwrites."""
        self.store.record("acme", _payload(50, "warm"),
                            today_iso="2026-05-23")
        self.store.record("acme", _payload(60, "warm"),
                            today_iso="2026-05-23")
        history = self.store.history("acme")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["score"], 60)

    def test_multi_day_accumulates(self):
        self.store.record("acme", _payload(80, "strong"),
                            today_iso="2026-05-20")
        self.store.record("acme", _payload(60, "warm"),
                            today_iso="2026-05-22")
        self.store.record("acme", _payload(40, "weak"),
                            today_iso="2026-05-23")
        history = self.store.history("acme")
        # Newest first.
        self.assertEqual([h["date"] for h in history],
                         ["2026-05-23", "2026-05-22", "2026-05-20"])

    def test_ring_buffer_cap_30(self):
        for i in range(35):
            day = f"2026-{(i // 31) + 4:02d}-{(i % 31) + 1:02d}"
            self.store.record("acme", _payload(50, "warm"), today_iso=day)
        history = self.store.history("acme", limit=100)
        self.assertEqual(len(history), 30)

    def test_per_lead_isolation(self):
        self.store.record("acme", _payload(80, "strong"))
        self.store.record("beta", _payload(20, "cold"))
        self.assertEqual(self.store.history("acme")[0]["score"], 80)
        self.assertEqual(self.store.history("beta")[0]["score"], 20)

    # ----- previous_snapshot -----------------------------------------

    def test_previous_snapshot_finds_most_recent_before_date(self):
        self.store.record("acme", _payload(80, "strong"),
                            today_iso="2026-05-20")
        self.store.record("acme", _payload(60, "warm"),
                            today_iso="2026-05-22")
        # Today is 23rd; previous should be the 22nd.
        prev = self.store.previous_snapshot("acme",
                                              before_date="2026-05-23")
        self.assertEqual(prev["date"], "2026-05-22")
        self.assertEqual(prev["score"], 60)

    def test_previous_snapshot_none_when_no_history(self):
        self.assertIsNone(self.store.previous_snapshot(
            "acme", before_date="2026-05-23"))

    def test_previous_snapshot_excludes_today(self):
        """previous_snapshot strictly excludes the `before_date` itself
        — used to compare today vs the most recent earlier snapshot."""
        self.store.record("acme", _payload(80, "strong"),
                            today_iso="2026-05-22")
        self.store.record("acme", _payload(40, "weak"),
                            today_iso="2026-05-23")
        prev = self.store.previous_snapshot("acme",
                                              before_date="2026-05-23")
        self.assertEqual(prev["date"], "2026-05-22")

    # ----- delta -----------------------------------------------------

    def test_delta_none_when_only_one_snapshot(self):
        self.store.record("acme", _payload(80, "strong"))
        self.assertIsNone(self.store.delta("acme"))

    def test_delta_finds_score_n_days_ago(self):
        self.store.record("acme", _payload(50, "warm"),
                            today_iso="2026-05-16")
        self.store.record("acme", _payload(80, "strong"),
                            today_iso="2026-05-23")
        d = self.store.delta("acme", days_ago=7)
        self.assertEqual(d["now"], 80)
        self.assertEqual(d["then"], 50)
        self.assertEqual(d["delta"], 30)
        self.assertEqual(d["direction"], "up")
        self.assertEqual(d["days_compared"], 7)

    def test_delta_direction_down(self):
        self.store.record("acme", _payload(80, "strong"),
                            today_iso="2026-05-16")
        self.store.record("acme", _payload(50, "warm"),
                            today_iso="2026-05-23")
        d = self.store.delta("acme", days_ago=7)
        self.assertEqual(d["delta"], -30)
        self.assertEqual(d["direction"], "down")

    def test_delta_direction_flat(self):
        self.store.record("acme", _payload(80, "strong"),
                            today_iso="2026-05-16")
        self.store.record("acme", _payload(80, "strong"),
                            today_iso="2026-05-23")
        d = self.store.delta("acme", days_ago=7)
        self.assertEqual(d["direction"], "flat")

    def test_delta_falls_back_to_oldest_when_not_enough_history(self):
        """7-day delta asked but only 3 days of history → compare against
        the oldest available snapshot."""
        self.store.record("acme", _payload(50, "warm"),
                            today_iso="2026-05-20")
        self.store.record("acme", _payload(80, "strong"),
                            today_iso="2026-05-23")
        d = self.store.delta("acme", days_ago=7)
        self.assertIsNotNone(d)
        self.assertEqual(d["then"], 50)
        self.assertEqual(d["days_compared"], 3)

    # ----- band_downgraded -------------------------------------------

    def test_band_downgrade_detection(self):
        self.assertTrue(self.store.band_downgraded("strong", "warm"))
        self.assertTrue(self.store.band_downgraded("warm", "cold"))
        self.assertTrue(self.store.band_downgraded("strong", "cold"))
        self.assertFalse(self.store.band_downgraded("cold", "warm"))
        self.assertFalse(self.store.band_downgraded("warm", "warm"))
        self.assertFalse(self.store.band_downgraded(None, "cold"))
        self.assertFalse(self.store.band_downgraded("strong", None))


class EngagementDropNotificationTests(unittest.TestCase):
    """Integration: opening the lead drawer (which fires the engagement
    score endpoint) writes a snapshot AND fires a bell notification on
    a band downgrade. Subsequent opens on the same day don't re-fire."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "contacts")
        os.environ["CALLS_STORE_DIR"] = os.path.join(cls.tmp, "calls")
        os.environ["LEAD_CONTACT_NOTES_STORE_DIR"] = os.path.join(cls.tmp, "notes")
        os.environ["ENGAGEMENT_SNAPSHOTS_STORE_DIR"] = os.path.join(cls.tmp, "snap")
        os.environ["NOTIFICATIONS_STORE_DIR"] = os.path.join(cls.tmp, "notif")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "contacts_store", "calls_store",
                    "lead_contact_notes_store", "engagement",
                    "engagement_snapshots_store",
                    "notifications_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("CONTACTS_STORE_DIR", "CALLS_STORE_DIR",
                  "LEAD_CONTACT_NOTES_STORE_DIR",
                  "ENGAGEMENT_SNAPSHOTS_STORE_DIR",
                  "NOTIFICATIONS_STORE_DIR",
                  "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        # Fresh state per test.
        for sub in ("snap", "notif"):
            d = Path(self.tmp) / sub
            if d.exists():
                shutil.rmtree(d)

    def test_band_downgrade_fires_engagement_dropped_notification(self):
        import engagement_snapshots_store, notifications_store
        # Seed a previous "strong" snapshot for yesterday.
        engagement_snapshots_store.record(
            "lead-drop",
            {"score": 80, "band": "strong",
             "signals": {"considered_contacts": 1, "active_contacts": 1,
                          "coverage_pct": 100, "events_30d": 5}},
            today_iso="2026-05-22")
        # Hit the score endpoint. Lead has no contacts → today's score
        # will be 0 (cold) — a downgrade from "strong".
        with patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.get_page.return_value = {
                "id": "lead-drop", "company": "Acme",
                "owner": "Ben Ojuolape",
            }
            self.client.get("/api/lead/lead-drop/engagement-score")
        items = notifications_store.list_for("Ben Ojuolape")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["type"], "engagement_dropped")
        self.assertIn("Acme", items[0]["title"])
        self.assertIn("cold", items[0]["title"])
        self.assertEqual(items[0]["link"]["lead_id"], "lead-drop")

    def test_same_day_repeat_does_not_re_fire_notification(self):
        import engagement_snapshots_store, notifications_store
        engagement_snapshots_store.record(
            "lead-drop2",
            {"score": 80, "band": "strong",
             "signals": {"considered_contacts": 1, "active_contacts": 1,
                          "coverage_pct": 100, "events_30d": 5}},
            today_iso="2026-05-22")
        with patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.get_page.return_value = {
                "id": "lead-drop2", "company": "Beta",
                "owner": "Ben Ojuolape",
            }
            # Open twice in the same day.
            self.client.get("/api/lead/lead-drop2/engagement-score")
            self.client.get("/api/lead/lead-drop2/engagement-score")
        items = notifications_store.list_for("Ben Ojuolape")
        # Still only 1 notification — second call was deduped.
        self.assertEqual(len(items), 1)

    def test_no_notification_when_band_unchanged(self):
        import engagement_snapshots_store, notifications_store
        # Yesterday: cold. Today: still cold (no contacts) → no drop.
        engagement_snapshots_store.record(
            "lead-flat",
            {"score": 20, "band": "cold",
             "signals": {"considered_contacts": 0, "active_contacts": 0,
                          "coverage_pct": 0, "events_30d": 0}},
            today_iso="2026-05-22")
        with patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.get_page.return_value = {
                "id": "lead-flat", "company": "Gamma",
                "owner": "Ben Ojuolape",
            }
            self.client.get("/api/lead/lead-flat/engagement-score")
        items = notifications_store.list_for("Ben Ojuolape")
        self.assertEqual(items, [])

    def test_no_notification_when_band_improves(self):
        import engagement_snapshots_store, notifications_store
        # Yesterday: weak. Today: warmer (good news, no notification).
        # We need today's score to actually improve. Seed a contact +
        # a fresh note.
        import contacts_store
        c = contacts_store.save_contact(
            "lead-up", {"name": "Champ", "is_primary": True})
        self.client.post(
            f"/api/contacts/lead-up/{c['id']}/notes",
            json={"type": "touch", "content": "spoke today"})
        engagement_snapshots_store.record(
            "lead-up",
            {"score": 20, "band": "cold",
             "signals": {"considered_contacts": 1, "active_contacts": 1,
                          "coverage_pct": 0, "events_30d": 0}},
            today_iso="2026-05-22")
        with patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.get_page.return_value = {
                "id": "lead-up", "company": "Delta",
                "owner": "Ben Ojuolape",
            }
            self.client.get("/api/lead/lead-up/engagement-score")
        items = notifications_store.list_for("Ben Ojuolape")
        self.assertEqual(items, [])

    def test_trend_field_in_response(self):
        """The /engagement-score response includes a trend block when
        there's history to compare against."""
        import engagement_snapshots_store
        engagement_snapshots_store.record(
            "lead-trend",
            {"score": 80, "band": "strong",
             "signals": {"considered_contacts": 1, "active_contacts": 1,
                          "coverage_pct": 100, "events_30d": 5}},
            today_iso="2026-05-16")
        with patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.get_page.return_value = {
                "id": "lead-trend", "company": "Eps", "owner": "Glenn",
            }
            body = self.client.get(
                "/api/lead/lead-trend/engagement-score").get_json()
        self.assertIn("trend", body)
        self.assertIsNotNone(body["trend"])
        self.assertEqual(body["trend"]["then"], 80)


if __name__ == "__main__":
    unittest.main()
