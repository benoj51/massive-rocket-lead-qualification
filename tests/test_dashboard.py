"""v1.0.0t — team activity dashboard tests.

Covers:
- Window filtering on touches (in-window vs out-of-window notes)
- Per-MR-owner attribution via contact.mr_owner
- Per-partner activity rollup
- Coverage compliance math
- New-leads-in-window proxy
- Owner filter param scopes the totals
- Empty roster doesn't crash; KPIs default to zero
- /api/dashboard endpoint shape (with mocked pipeline)
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _iso(when: datetime) -> str:
    return when.isoformat(timespec="seconds").replace("+00:00", "Z")


class DashboardBuilderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Snapshot env so tearDown doesn't wipe test-runner-set values
        # (e.g. SKIP_COMMAND_CENTRE_SEED on the CLI) and pollute later
        # test-class module reloads.
        self._env_set: dict[str, str | None] = {}
        for k, v in {
            "PARTNERS_STORE_PATH":           os.path.join(self.tmp, "p.json"),
            "PARTNER_CONTACTS_STORE_DIR":    os.path.join(self.tmp, "pc"),
            "PARTNER_NOTES_STORE_DIR":       os.path.join(self.tmp, "pn"),
            "CALLS_STORE_DIR":               os.path.join(self.tmp, "calls"),
            "LEAD_AGENCIES_STORE_DIR":       os.path.join(self.tmp, "la"),
            "SKIP_NOTION_BOOT":              "1",
            "SKIP_COMMAND_CENTRE_SEED":      "1",
        }.items():
            self._env_set[k] = os.environ.get(k)
            os.environ[k] = v
        for mod in ("dashboard", "partners_store", "partner_contacts_store",
                     "partner_notes_store", "calls_store", "mr_owners",
                     "project_store"):
            sys.modules.pop(mod, None)

    def tearDown(self):
        for k, original in self._env_set.items():
            if original is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = original
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _seed_partner(self, partner_id="braze", name="Braze"):
        import partners_store
        return partners_store.save_partner({"id": partner_id, "name": name,
                                              "type": "Technology partner"})

    def _seed_contact(self, partner_id, contact_id, *, mr_owner="Ben Ojuolape",
                       added_days_ago=0, last_touched_days_ago=None,
                       cadence_days=30, status="active"):
        import partner_contacts_store
        from datetime import datetime, timezone, timedelta
        c = {
            "id": contact_id, "name": f"Contact {contact_id}",
            "mr_owner": mr_owner, "status": status,
            "cadence_days": cadence_days,
            "added_at": _iso(datetime.now(timezone.utc) - timedelta(days=added_days_ago)),
        }
        if last_touched_days_ago is not None:
            c["last_touched_at"] = _iso(
                datetime.now(timezone.utc) - timedelta(days=last_touched_days_ago)
            )
        return partner_contacts_store.save_contact(partner_id, c)

    def _seed_note(self, partner_id, contact_id, *, days_ago=0, note_type="call",
                    content="hello"):
        import partner_notes_store
        from datetime import datetime, timezone, timedelta
        # add_note generates created_at automatically — we need to override
        # via the store's lower-level path.
        notes = partner_notes_store._load_raw(partner_id, contact_id)
        import uuid
        notes.append({
            "id": uuid.uuid4().hex[:12],
            "partner_id": partner_id, "contact_id": contact_id,
            "type": note_type, "content": content, "author": "anon",
            "created_at": _iso(datetime.now(timezone.utc) - timedelta(days=days_ago)),
        })
        partner_notes_store._write_raw(partner_id, contact_id, notes)

    # ── Window filtering ────────────────────────────────────────

    def test_touches_outside_window_excluded(self):
        import dashboard
        self._seed_partner()
        self._seed_contact("braze", "c1", mr_owner="Ben Ojuolape")
        self._seed_note("braze", "c1", days_ago=2)    # in 7-day window
        self._seed_note("braze", "c1", days_ago=20)   # outside 7-day window
        result = dashboard.build_dashboard(window_days=7)
        self.assertEqual(result["totals"]["touches"], 1)

    def test_touches_inside_window_counted_by_type(self):
        import dashboard
        self._seed_partner()
        self._seed_contact("braze", "c1", mr_owner="Ben Ojuolape")
        self._seed_note("braze", "c1", days_ago=1, note_type="call")
        self._seed_note("braze", "c1", days_ago=2, note_type="email")
        self._seed_note("braze", "c1", days_ago=3, note_type="intro")
        result = dashboard.build_dashboard(window_days=7)
        self.assertEqual(result["totals"]["touches"], 3)
        self.assertEqual(result["totals"]["by_type"]["call"], 1)
        self.assertEqual(result["totals"]["by_type"]["email"], 1)
        self.assertEqual(result["totals"]["by_type"]["intro"], 1)

    # ── Per-owner attribution ───────────────────────────────────

    def test_per_owner_attribution_via_mr_owner(self):
        import dashboard
        self._seed_partner()
        self._seed_contact("braze", "c1", mr_owner="Ben Ojuolape")
        self._seed_contact("braze", "c2", mr_owner="Daniel Ergueta")
        self._seed_note("braze", "c1", days_ago=1)
        self._seed_note("braze", "c2", days_ago=1)
        self._seed_note("braze", "c2", days_ago=2)
        result = dashboard.build_dashboard(window_days=7)
        ben     = next(o for o in result["by_owner"] if o["name"] == "Ben Ojuolape")
        daniel  = next(o for o in result["by_owner"] if o["name"] == "Daniel Ergueta")
        self.assertEqual(ben["touches"], 1)
        self.assertEqual(daniel["touches"], 2)

    def test_per_owner_includes_inactive_owners(self):
        """Owners with no activity still show up — manager wants to see
        the goose-eggs too."""
        import dashboard
        self._seed_partner()
        # Only seed Ben's contact + note
        self._seed_contact("braze", "c1", mr_owner="Ben Ojuolape")
        self._seed_note("braze", "c1", days_ago=1)
        result = dashboard.build_dashboard(window_days=7)
        names = {o["name"] for o in result["by_owner"]}
        # Other 11 MR owners should also appear with 0 touches
        self.assertIn("Daniel Craig", names)
        self.assertIn("Claudia Lima", names)
        self.assertIn("Lea", names)
        # And their touches should be 0
        lea = next(o for o in result["by_owner"] if o["name"] == "Lea")
        self.assertEqual(lea["touches"], 0)

    def test_owner_filter_scopes_results(self):
        import dashboard
        self._seed_partner()
        self._seed_contact("braze", "c1", mr_owner="Ben Ojuolape")
        self._seed_contact("braze", "c2", mr_owner="Daniel Ergueta")
        self._seed_note("braze", "c1", days_ago=1)
        self._seed_note("braze", "c2", days_ago=1)
        result = dashboard.build_dashboard(window_days=7,
                                            owner_filter="Daniel Ergueta")
        # Only Daniel's owner row present
        self.assertEqual(len(result["by_owner"]), 1)
        self.assertEqual(result["by_owner"][0]["name"], "Daniel Ergueta")
        # Total touches reflect only Daniel's contacts
        self.assertEqual(result["totals"]["touches"], 1)

    # ── Per-partner attribution ─────────────────────────────────

    def test_per_partner_rollup(self):
        import dashboard
        self._seed_partner("braze", "Braze")
        self._seed_partner("hightouch", "Hightouch")
        self._seed_contact("braze",     "b1")
        self._seed_contact("hightouch", "h1")
        self._seed_contact("hightouch", "h2")
        self._seed_note("braze",     "b1", days_ago=1)
        self._seed_note("hightouch", "h1", days_ago=1)
        self._seed_note("hightouch", "h2", days_ago=1)
        result = dashboard.build_dashboard(window_days=7)
        braze = next(p for p in result["by_partner"] if p["id"] == "braze")
        ht    = next(p for p in result["by_partner"] if p["id"] == "hightouch")
        self.assertEqual(braze["touches"], 1)
        self.assertEqual(braze["contacts"], 1)
        self.assertEqual(ht["touches"], 2)
        self.assertEqual(ht["contacts"], 2)

    # ── Coverage compliance ─────────────────────────────────────

    def test_coverage_compliance_math(self):
        import dashboard
        self._seed_partner()
        # 4 active contacts: 3 within cadence, 1 overdue
        self._seed_contact("braze", "c1", added_days_ago=10, last_touched_days_ago=5,
                            cadence_days=30)  # within cadence
        self._seed_contact("braze", "c2", added_days_ago=10, last_touched_days_ago=5,
                            cadence_days=30)  # within
        self._seed_contact("braze", "c3", added_days_ago=10, last_touched_days_ago=5,
                            cadence_days=30)  # within
        self._seed_contact("braze", "c4", added_days_ago=60, last_touched_days_ago=50,
                            cadence_days=30)  # overdue
        result = dashboard.build_dashboard(window_days=7)
        cov = result["coverage"]
        self.assertEqual(cov["active_contacts"], 4)
        self.assertEqual(cov["overdue"], 1)
        self.assertEqual(cov["within_cadence"], 3)
        # 3/4 = 75%
        self.assertEqual(cov["compliance_pct"], 75.0)

    def test_coverage_never_touched_counted(self):
        import dashboard
        self._seed_partner()
        # added 60 days ago, never touched, 30d cadence → overdue + never_touched
        self._seed_contact("braze", "c1", added_days_ago=60, cadence_days=30)
        result = dashboard.build_dashboard(window_days=7)
        self.assertEqual(result["coverage"]["never_touched"], 1)
        self.assertEqual(result["coverage"]["overdue"], 1)

    def test_inactive_contacts_excluded_from_coverage(self):
        import dashboard
        self._seed_partner()
        # status=left contacts shouldn't count toward coverage
        self._seed_contact("braze", "c1", status="left",
                            added_days_ago=60, cadence_days=30)
        result = dashboard.build_dashboard(window_days=7)
        self.assertEqual(result["coverage"]["active_contacts"], 0)

    # ── Empty + degenerate ──────────────────────────────────────

    def test_empty_roster_returns_zero_kpis(self):
        import dashboard
        result = dashboard.build_dashboard(window_days=7)
        self.assertEqual(result["totals"]["touches"], 0)
        self.assertEqual(result["totals"]["cadence_compliance_pct"], 0.0)
        # All 12 MR owners still listed with goose-eggs.
        self.assertEqual(len(result["by_owner"]), 12)


class DashboardEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._env_set: dict[str, str | None] = {}
        for k, v in {
            "PARTNERS_STORE_PATH":           os.path.join(self.tmp, "p.json"),
            "PARTNER_CONTACTS_STORE_DIR":    os.path.join(self.tmp, "pc"),
            "PARTNER_NOTES_STORE_DIR":       os.path.join(self.tmp, "pn"),
            "CALLS_STORE_DIR":               os.path.join(self.tmp, "calls"),
            "SKIP_NOTION_BOOT":              "1",
            "SKIP_COMMAND_CENTRE_SEED":      "1",
        }.items():
            self._env_set[k] = os.environ.get(k)
            os.environ[k] = v
        for mod in ("server", "dashboard", "partners_store",
                     "partner_contacts_store", "partner_notes_store",
                     "calls_store"):
            sys.modules.pop(mod, None)
        import server
        self.server = server
        self.client = server.app.test_client()

    def tearDown(self):
        for k, original in self._env_set.items():
            if original is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = original
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _mock_notion_sync(self, *, list_pipeline_return=None,
                            list_pipeline_side_effect=None):
        fake = mock.MagicMock()
        if list_pipeline_side_effect is not None:
            fake.list_pipeline.side_effect = list_pipeline_side_effect
        else:
            fake.list_pipeline.return_value = list_pipeline_return or []
        return mock.patch.object(self.server, "NotionSync",
                                  return_value=fake)

    def test_endpoint_shape(self):
        with self._mock_notion_sync(list_pipeline_return=[]):
            r = self.client.get("/api/dashboard?window=7")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        for k in ("window_days", "since", "generated_at",
                   "totals", "coverage", "by_owner", "by_partner"):
            self.assertIn(k, data)
        self.assertEqual(data["window_days"], 7)

    def test_endpoint_clamps_window(self):
        with self._mock_notion_sync(list_pipeline_return=[]):
            r = self.client.get("/api/dashboard?window=99999")
        self.assertEqual(r.get_json()["window_days"], 365)
        with self._mock_notion_sync(list_pipeline_return=[]):
            r = self.client.get("/api/dashboard?window=0")
        self.assertEqual(r.get_json()["window_days"], 1)

    def test_endpoint_still_returns_when_notion_unavailable(self):
        """A Notion outage shouldn't break the dashboard — partner-side
        stats should still come through."""
        from notion_sync import NotionSyncError
        with self._mock_notion_sync(
            list_pipeline_side_effect=NotionSyncError("502 from Notion"),
        ):
            r = self.client.get("/api/dashboard?window=7")
        # Returns 200 (not 502) because we degraded gracefully
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["totals"]["lead_calls"], 0)
        # Partner-side keys still present
        self.assertIn("by_owner", data)
        self.assertIn("by_partner", data)


if __name__ == "__main__":
    unittest.main()
