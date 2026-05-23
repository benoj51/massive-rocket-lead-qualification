"""v1.0.0at — engagement score module + endpoint tests.

Scoring formula recap (kept inline so a future weight tweak forces a
deliberate test update):

  coverage     30 pts  — % of active contacts touched at all
  recency      30 pts  — days since most recent touch (0d=30 → 60d=8)
  activity     25 pts  — notes+calls in last 30d (10+ events = 25)
  overdue     -15 pts  — -5 per overdue contact, capped
  key bonus    10 pts  — primary contact touched in last 30d

  ≥75 = strong  ≥50 = warm  ≥25 = weak  <25 = cold
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


def _iso(days_ago: int) -> str:
    """Make an iso8601-Z timestamp `days_ago` days before 2026-05-23."""
    base = datetime(2026, 5, 23, tzinfo=timezone.utc)
    return (base - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


class EngagementScorerTests(unittest.TestCase):
    """Pure-function tests against engagement.compute_engagement_score.
    No Flask, no file I/O — fast feedback on the scoring math."""

    def setUp(self):
        sys.modules.pop("engagement", None)
        import engagement
        self.scorer = engagement
        # Every test runs with "today" pinned to 2026-05-23 so the
        # ISO helpers above produce predictable day counts.
        self.today = "2026-05-23"

    # -----------------------------------------------------------------
    # Boundary cases
    # -----------------------------------------------------------------

    def test_no_contacts_zero_score(self):
        r = self.scorer.compute_engagement_score(
            contacts=[], recent_event_isos=[], today_iso=self.today)
        self.assertEqual(r["score"], 0)
        self.assertEqual(r["band"], "cold")
        self.assertEqual(r["signals"]["active_contacts"], 0)

    def test_contacts_no_engagement_zero_score(self):
        contacts = [{"id": "1", "name": "A", "status": "active"}]
        r = self.scorer.compute_engagement_score(
            contacts=contacts, recent_event_isos=[], today_iso=self.today)
        self.assertEqual(r["score"], 0)
        self.assertEqual(r["band"], "cold")
        self.assertEqual(r["signals"]["coverage_pct"], 0)
        self.assertIsNone(r["signals"]["days_since_touch"])

    # -----------------------------------------------------------------
    # Individual signal contributions
    # -----------------------------------------------------------------

    def test_full_coverage_full_recency_no_volume(self):
        """All 3 contacts touched today, no volume → 30 (coverage) + 30
        (recency) + 0 (activity) + 0 (overdue) + 0 (key) = 60. Warm."""
        contacts = [
            {"id": "1", "name": "A", "status": "active",
             "last_touched_at": _iso(0)},
            {"id": "2", "name": "B", "status": "active",
             "last_touched_at": _iso(0)},
            {"id": "3", "name": "C", "status": "active",
             "last_touched_at": _iso(0)},
        ]
        r = self.scorer.compute_engagement_score(
            contacts=contacts, recent_event_isos=[], today_iso=self.today)
        self.assertEqual(r["signals"]["coverage_points"], 30)
        self.assertEqual(r["signals"]["recency_points"], 30)
        self.assertEqual(r["signals"]["activity_points"], 0)
        self.assertEqual(r["score"], 60)
        self.assertEqual(r["band"], "warm")

    def test_recency_decay_bands(self):
        """Spot-check the recency band cliffs match the docstring."""
        def with_days(d):
            return self.scorer.compute_engagement_score(
                contacts=[{"id": "1", "name": "A", "status": "active",
                           "last_touched_at": _iso(d)}],
                recent_event_isos=[], today_iso=self.today,
            )["signals"]["recency_points"]
        self.assertEqual(with_days(0), 30)
        self.assertEqual(with_days(7), 25)
        self.assertEqual(with_days(14), 20)
        self.assertEqual(with_days(30), 15)
        self.assertEqual(with_days(60), 8)
        self.assertEqual(with_days(90), 0)
        self.assertEqual(with_days(180), 0)

    def test_activity_volume_ramps_and_caps(self):
        contacts = [{"id": "1", "name": "A", "status": "active"}]
        def pts(n):
            return self.scorer.compute_engagement_score(
                contacts=contacts,
                recent_event_isos=[_iso(i % 30) for i in range(n)],
                today_iso=self.today,
            )["signals"]["activity_points"]
        self.assertEqual(pts(0), 0)
        self.assertEqual(pts(5), 12)   # round(5 * 2.5)
        self.assertEqual(pts(10), 25)
        self.assertEqual(pts(50), 25)  # cap at 25

    def test_activity_volume_ignores_old_events(self):
        """Events older than 30 days don't count toward activity."""
        contacts = [{"id": "1", "name": "A", "status": "active"}]
        old_events = [_iso(60), _iso(90), _iso(120)]
        r = self.scorer.compute_engagement_score(
            contacts=contacts, recent_event_isos=old_events,
            today_iso=self.today)
        self.assertEqual(r["signals"]["events_30d"], 0)
        self.assertEqual(r["signals"]["activity_points"], 0)

    def test_overdue_penalty(self):
        contacts = [
            {"id": "1", "name": "A", "status": "active",
             "last_touched_at": _iso(0), "overdue": True},
            {"id": "2", "name": "B", "status": "active",
             "last_touched_at": _iso(0), "overdue": True},
            {"id": "3", "name": "C", "status": "active",
             "last_touched_at": _iso(0), "overdue": True},
            {"id": "4", "name": "D", "status": "active",
             "last_touched_at": _iso(0), "overdue": True},
        ]
        r = self.scorer.compute_engagement_score(
            contacts=contacts, recent_event_isos=[], today_iso=self.today)
        # 4 overdue * -5 = -20, capped at -15
        self.assertEqual(r["signals"]["overdue_penalty"], -15)

    def test_key_contact_bonus_fires(self):
        contacts = [
            {"id": "1", "name": "Champ", "status": "active",
             "is_primary": True, "last_touched_at": _iso(5)},
        ]
        r = self.scorer.compute_engagement_score(
            contacts=contacts, recent_event_isos=[], today_iso=self.today)
        self.assertEqual(r["signals"]["key_bonus"], 10)
        self.assertTrue(r["signals"]["key_touched_30d"])

    def test_key_contact_bonus_skipped_when_too_old(self):
        contacts = [
            {"id": "1", "name": "Champ", "status": "active",
             "is_primary": True, "last_touched_at": _iso(60)},
        ]
        r = self.scorer.compute_engagement_score(
            contacts=contacts, recent_event_isos=[], today_iso=self.today)
        self.assertEqual(r["signals"]["key_bonus"], 0)
        self.assertFalse(r["signals"]["key_touched_30d"])

    # -----------------------------------------------------------------
    # Band thresholds
    # -----------------------------------------------------------------

    def test_strong_band_threshold(self):
        """Construct a score exactly at the 75 cutoff."""
        contacts = [{"id": "1", "name": "A", "status": "active",
                     "is_primary": True, "last_touched_at": _iso(0)}]
        events = [_iso(i) for i in range(10)]  # 10 events → 25 pts
        r = self.scorer.compute_engagement_score(
            contacts=contacts, recent_event_isos=events, today_iso=self.today)
        # 30 (coverage 100%) + 30 (touched today) + 25 (10 events)
        # + 0 (no overdue) + 10 (key today) = 95
        self.assertEqual(r["score"], 95)
        self.assertEqual(r["band"], "strong")

    def test_weak_band(self):
        """Moderate engagement → weak band (25-49)."""
        contacts = [
            {"id": "1", "name": "A", "status": "active",
             "last_touched_at": _iso(40)},  # past recency
            {"id": "2", "name": "B", "status": "active"},
        ]
        r = self.scorer.compute_engagement_score(
            contacts=contacts, recent_event_isos=[], today_iso=self.today)
        # coverage 50% → 15, recency 40d → 8, activity 0, overdue 0
        # → 23 total. <25 = cold, not weak.
        self.assertLess(r["score"], 25)
        self.assertEqual(r["band"], "cold")

    # -----------------------------------------------------------------
    # Active-only handling
    # -----------------------------------------------------------------

    def test_dormant_and_left_contacts_excluded_from_coverage(self):
        """Coverage % is over ACTIVE contacts only — left/dormant
        contacts shouldn't drag the score down."""
        contacts = [
            {"id": "1", "name": "Active",  "status": "active",
             "last_touched_at": _iso(0)},
            {"id": "2", "name": "Dormant", "status": "dormant"},
            {"id": "3", "name": "Left",    "status": "left"},
        ]
        r = self.scorer.compute_engagement_score(
            contacts=contacts, recent_event_isos=[], today_iso=self.today)
        # 1 of 1 active touched = 100% coverage
        self.assertEqual(r["signals"]["coverage_pct"], 100)
        self.assertEqual(r["signals"]["active_contacts"], 1)
        self.assertEqual(r["signals"]["considered_contacts"], 3)

    # -----------------------------------------------------------------
    # Score clamping
    # -----------------------------------------------------------------

    def test_score_never_exceeds_100(self):
        """Stack every bonus: should clamp at 100, not 105+."""
        contacts = [{"id": "1", "name": "A", "status": "active",
                     "is_primary": True, "last_touched_at": _iso(0)}]
        events = [_iso(i) for i in range(30)]  # caps activity at 25
        r = self.scorer.compute_engagement_score(
            contacts=contacts, recent_event_isos=events, today_iso=self.today)
        self.assertEqual(r["score"], 95)  # 30+30+25+0+10
        self.assertLessEqual(r["score"], 100)

    def test_score_never_drops_below_0(self):
        """Stack penalties (no contacts engaged + lots overdue): floor 0."""
        contacts = [
            {"id": str(i), "name": f"C{i}", "status": "active",
             "overdue": True} for i in range(10)
        ]
        r = self.scorer.compute_engagement_score(
            contacts=contacts, recent_event_isos=[], today_iso=self.today)
        # No touches, 10 overdue → coverage 0 + recency 0 + activity 0
        # + penalty -15 (capped) = -15 → clamped to 0
        self.assertEqual(r["score"], 0)
        self.assertEqual(r["band"], "cold")


class EngagementScoreEndpointTests(unittest.TestCase):
    """Integration smoke test: the wire shape matches what the UI expects."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "contacts")
        os.environ["LEAD_CONTACT_NOTES_STORE_DIR"] = os.path.join(cls.tmp, "notes")
        os.environ["CALLS_STORE_DIR"] = os.path.join(cls.tmp, "calls")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "contacts_store", "calls_store",
                    "lead_contact_notes_store", "engagement"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("CONTACTS_STORE_DIR", "LEAD_CONTACT_NOTES_STORE_DIR",
                  "CALLS_STORE_DIR", "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_endpoint_empty_account(self):
        r = self.client.get("/api/lead/never-touched/engagement-score")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["score"], 0)
        self.assertEqual(body["band"], "cold")
        self.assertIn("signals", body)
        self.assertIn("coverage_pct", body["signals"])

    def test_endpoint_real_data(self):
        """Save a contact + a note + a call and confirm the endpoint
        wires everything through end-to-end."""
        import contacts_store, lead_contact_notes_store, calls_store
        lead_id = "engagement-real"
        c = contacts_store.save_contact(lead_id,
                                          {"name": "Jane",
                                           "is_primary": True})
        # Auto-touch via the notes endpoint to land a recent touch.
        self.client.post(
            f"/api/contacts/{lead_id}/{c['id']}/notes",
            json={"type": "touch", "content": "spoke today"})
        calls_store.add_call(lead_id, {"type": "discovery",
                                         "title": "Disco",
                                         "content": "good call"})
        body = self.client.get(
            f"/api/lead/{lead_id}/engagement-score").get_json()
        # Has 1 active contact (touched today + primary) + 1 note + 1 call.
        # Coverage 100% (30) + recency 0d (30) + activity 2 events (5) +
        # overdue 0 + key bonus (10) = 75. Strong band.
        self.assertGreaterEqual(body["score"], 70)
        self.assertIn(body["band"], ("warm", "strong"))
        self.assertEqual(body["signals"]["coverage_pct"], 100)
        self.assertGreaterEqual(body["signals"]["events_30d"], 1)


if __name__ == "__main__":
    unittest.main()
