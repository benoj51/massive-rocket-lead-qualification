"""v1.0.0ah — personalised Home view endpoint."""
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


class HomeEndpointTests(unittest.TestCase):
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
                     "calls_store", "mr_owners"):
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

    def _mock_notion_sync(self, *, list_pipeline_return=None):
        fake = mock.MagicMock()
        fake.list_pipeline.return_value = list_pipeline_return or []
        return mock.patch.object(self.server, "NotionSync", return_value=fake)

    # ── Auth / lookup ────────────────────────────────────────

    def test_missing_owner_returns_400(self):
        with self._mock_notion_sync():
            r = self.client.get("/api/home")
        self.assertEqual(r.status_code, 400)
        self.assertIn("owner", r.get_json()["error"].lower())

    def test_unknown_owner_returns_404(self):
        with self._mock_notion_sync():
            r = self.client.get("/api/home?owner=Not%20A%20Person")
        self.assertEqual(r.status_code, 404)

    # ── Shape ─────────────────────────────────────────────────

    def test_returns_full_shape_for_known_owner(self):
        with self._mock_notion_sync():
            r = self.client.get("/api/home?owner=Ben%20Ojuolape")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        for key in ("owner", "kpis", "overdue_contacts",
                     "active_leads", "team_snapshot",
                     "role_extras", "generated_at"):
            self.assertIn(key, data)
        # Owner block carries the role + region the picker showed.
        self.assertEqual(data["owner"]["name"], "Ben Ojuolape")
        self.assertIn("Growth Lead", data["owner"]["role"])

    # ── Per-owner attribution ───────────────────────────────

    def _seed_partner_contact(self, partner_id, contact_id, *, mr_owner,
                                  added_days_ago=0, last_touched_days_ago=None,
                                  cadence_days=30, status="active"):
        import partner_contacts_store, partners_store
        partners_store.save_partner({
            "id": partner_id, "name": partner_id.title(),
            "type": "Technology partner",
        })
        c = {
            "id": contact_id, "name": f"Contact {contact_id}",
            "mr_owner": mr_owner, "status": status,
            "cadence_days": cadence_days,
            "added_at": _iso(datetime.now(timezone.utc)
                              - timedelta(days=added_days_ago)),
        }
        if last_touched_days_ago is not None:
            c["last_touched_at"] = _iso(
                datetime.now(timezone.utc) - timedelta(days=last_touched_days_ago)
            )
        partner_contacts_store.save_contact(partner_id, c)

    def test_kpis_scoped_to_owner_book(self):
        # Ben owns 2 contacts (1 overdue), Daniel owns 1 (in cadence)
        self._seed_partner_contact("braze", "c1", mr_owner="Ben Ojuolape",
                                     added_days_ago=10, last_touched_days_ago=5,
                                     cadence_days=30)
        self._seed_partner_contact("braze", "c2", mr_owner="Ben Ojuolape",
                                     added_days_ago=60, last_touched_days_ago=50,
                                     cadence_days=30)
        self._seed_partner_contact("braze", "c3", mr_owner="Daniel Ergueta",
                                     added_days_ago=10, last_touched_days_ago=5,
                                     cadence_days=30)
        with self._mock_notion_sync():
            r = self.client.get("/api/home?owner=Ben%20Ojuolape")
        kpis = r.get_json()["kpis"]
        self.assertEqual(kpis["partner_contacts_owned"], 2)
        self.assertEqual(kpis["partner_contacts_overdue"], 1)

    def test_overdue_list_returns_top_overdue_owned(self):
        # 3 overdue contacts on Ben's book, ranked by days overdue.
        for i, ago in enumerate([60, 90, 120]):
            self._seed_partner_contact("braze", f"c{i}",
                                          mr_owner="Ben Ojuolape",
                                          added_days_ago=ago,
                                          last_touched_days_ago=ago - 5,
                                          cadence_days=30)
        with self._mock_notion_sync():
            r = self.client.get("/api/home?owner=Ben%20Ojuolape")
        overdue = r.get_json()["overdue_contacts"]
        self.assertEqual(len(overdue), 3)
        # Top of the list is the most overdue.
        self.assertGreater(overdue[0]["days_overdue"], 0)

    def test_active_leads_filter_excludes_disqualified(self):
        sample_rows = [
            {"id": "a", "company": "Popeyes US", "owner": "Ben Ojuolape",
              "status": "Qualified", "sales_stage": "Negotiation",
              "icp_normalised": 8.5},
            {"id": "b", "company": "Old Co", "owner": "Ben Ojuolape",
              "status": "Disqualified", "sales_stage": "Discovery",
              "icp_normalised": 2.0},
            {"id": "c", "company": "Other Person Lead",
              "owner": "Daniel Ergueta",
              "status": "Qualified", "sales_stage": "Discovery"},
        ]
        with self._mock_notion_sync(list_pipeline_return=sample_rows):
            r = self.client.get("/api/home?owner=Ben%20Ojuolape")
        leads = r.get_json()["active_leads"]
        # Only "Popeyes US" — the disqualified one + the other owner's
        # lead both excluded.
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["company"], "Popeyes US")

    # ── Role-aware extras ──────────────────────────────────

    def test_exec_role_gets_exec_block(self):
        with self._mock_notion_sync():
            r = self.client.get("/api/home?owner=Thierry%20Sequeira")
        extras = r.get_json()["role_extras"]
        self.assertIn("exec", extras)
        self.assertIn("team_touches_30d", extras["exec"])

    def test_director_of_growth_also_gets_exec_block(self):
        with self._mock_notion_sync():
            r = self.client.get("/api/home?owner=Daniel%20Craig")
        self.assertIn("exec", r.get_json()["role_extras"])

    def test_marketing_role_gets_marketing_block(self):
        with self._mock_notion_sync():
            r = self.client.get("/api/home?owner=Jamie%20MacDow")
        extras = r.get_json()["role_extras"]
        self.assertIn("marketing", extras)
        self.assertIn("new_leads_30d", extras["marketing"])

    def test_lea_marketing_role_gets_marketing_block(self):
        with self._mock_notion_sync():
            r = self.client.get("/api/home?owner=Lea")
        self.assertIn("marketing", r.get_json()["role_extras"])

    def test_sales_role_gets_no_extras(self):
        """Account Managers + AE-transitioning get the standard view
        only — no exec / marketing block."""
        with self._mock_notion_sync():
            r = self.client.get("/api/home?owner=Daniel%20Ergueta")
        self.assertEqual(r.get_json()["role_extras"], {})

    # ── Degradation ─────────────────────────────────────────

    def test_notion_down_still_returns_partner_side(self):
        from notion_sync import NotionSyncError
        fake = mock.MagicMock()
        fake.list_pipeline.side_effect = NotionSyncError("502")
        with mock.patch.object(self.server, "NotionSync", return_value=fake):
            r = self.client.get("/api/home?owner=Ben%20Ojuolape")
        # Should still 200 with empty leads
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["active_leads"], [])


if __name__ == "__main__":
    unittest.main()
