"""v1.0.0av — Home payload at_risk_leads tests.

Computes engagement score for the user's owned active leads, filters
to those scoring <50, sorts ascending (coldest first), caps at 5.
Powers the "Needs attention" Home card.
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
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _iso(days_ago: int) -> str:
    base = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return base.strftime("%Y-%m-%dT%H:%M:%SZ")


class HomeAtRiskLeadsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "contacts")
        os.environ["LEAD_CONTACT_NOTES_STORE_DIR"] = os.path.join(cls.tmp, "notes")
        os.environ["CALLS_STORE_DIR"] = os.path.join(cls.tmp, "calls")
        os.environ["PARTNERS_STORE_PATH"] = os.path.join(cls.tmp, "p.json")
        os.environ["PARTNER_CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "pc")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ["MR_OWNERS_PATH"] = os.path.join(cls.tmp, "mr_owners.json")
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "contacts_store", "calls_store",
                    "lead_contact_notes_store", "engagement",
                    "partners_store", "partner_contacts_store",
                    "mr_owners"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("CONTACTS_STORE_DIR", "LEAD_CONTACT_NOTES_STORE_DIR",
                  "CALLS_STORE_DIR", "PARTNERS_STORE_PATH",
                  "PARTNER_CONTACTS_STORE_DIR",
                  "SKIP_COMMAND_CENTRE_SEED", "MR_OWNERS_PATH"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _patched_home_call(self, fake_pipeline_rows):
        """Helper: invoke /api/home with NotionSync stubbed so we can
        feed in any pipeline shape we want without touching Notion.
        Uses Ben Ojuolape (a real seeded MR owner)."""
        with patch.object(self.server, "NotionSync") as MockSync:
            inst = MockSync.return_value
            inst.list_pipeline.return_value = fake_pipeline_rows
            r = self.client.get("/api/home?owner=Ben%20Ojuolape")
        return r

    def test_no_owned_leads_returns_empty_at_risk(self):
        r = self._patched_home_call([])
        body = r.get_json()
        self.assertEqual(body["at_risk_leads"], [])

    def test_lead_with_no_engagement_appears_at_risk(self):
        """A lead with no contacts at all has engagement score 0 →
        below the 50 threshold → surfaces in at_risk_leads."""
        rows = [{
            "id": "lead-empty", "company": "Acme",
            "owner": "Ben Ojuolape", "status": "Qualified",
            "icp_normalised": 8,
        }]
        body = self._patched_home_call(rows).get_json()
        self.assertEqual(len(body["at_risk_leads"]), 1)
        first = body["at_risk_leads"][0]
        self.assertEqual(first["id"], "lead-empty")
        self.assertEqual(first["engagement_score"], 0)
        self.assertEqual(first["engagement_band"], "cold")

    def test_high_engagement_lead_excluded(self):
        """Seed a lead with full engagement → score >=50 → NOT in
        at_risk_leads (it doesn't need attention)."""
        import contacts_store
        c = contacts_store.save_contact("lead-good",
                                          {"name": "Champ",
                                           "is_primary": True,
                                           "last_touched_at": _iso(0)})
        # Touch a few notes for activity points.
        for _ in range(3):
            self.client.post(
                f"/api/contacts/lead-good/{c['id']}/notes",
                json={"type": "touch", "content": "spoke"})
        rows = [{
            "id": "lead-good", "company": "Champion Co",
            "owner": "Ben Ojuolape", "status": "Qualified",
            "icp_normalised": 9,
        }]
        body = self._patched_home_call(rows).get_json()
        # Should be empty — single lead with high engagement is excluded.
        ids = [l["id"] for l in body["at_risk_leads"]]
        self.assertNotIn("lead-good", ids)

    def test_at_risk_sorted_coldest_first(self):
        """Multiple at-risk leads should sort by score ascending so the
        worst float to the top of the card."""
        import contacts_store
        # lead-a: no engagement → 0
        # lead-b: 1 contact touched 60d ago → coverage 30 + recency 8 = 38
        # lead-c: 1 contact touched today → coverage 30 + recency 30 = 60
        contacts_store.save_contact("lead-b",
                                      {"name": "X",
                                       "last_touched_at": _iso(60)})
        contacts_store.save_contact("lead-c",
                                      {"name": "Y",
                                       "last_touched_at": _iso(0)})
        rows = [
            {"id": "lead-a", "company": "A",
             "owner": "Ben Ojuolape", "status": "Qualified"},
            {"id": "lead-b", "company": "B",
             "owner": "Ben Ojuolape", "status": "Qualified"},
            {"id": "lead-c", "company": "C",
             "owner": "Ben Ojuolape", "status": "Qualified"},
        ]
        body = self._patched_home_call(rows).get_json()
        ids = [l["id"] for l in body["at_risk_leads"]]
        # lead-c (60) above threshold; only a (0) + b (38) appear.
        # a first (coldest).
        self.assertEqual(ids, ["lead-a", "lead-b"])

    def test_at_risk_capped_at_5(self):
        """Eight at-risk leads should return only the 5 coldest."""
        rows = [{"id": f"lead-{i}", "company": f"Co{i}",
                  "owner": "Ben Ojuolape", "status": "Qualified"}
                for i in range(8)]
        body = self._patched_home_call(rows).get_json()
        self.assertEqual(len(body["at_risk_leads"]), 5)

    def test_disqualified_leads_excluded(self):
        """Disqualified/On Hold/Closed Lost shouldn't show in at_risk
        — they're not part of the active book."""
        rows = [
            {"id": "lead-dq", "company": "X",
             "owner": "Ben Ojuolape", "status": "Disqualified"},
        ]
        body = self._patched_home_call(rows).get_json()
        self.assertEqual(body["at_risk_leads"], [])

    def test_other_owners_leads_excluded(self):
        rows = [
            {"id": "lead-other", "company": "Other",
             "owner": "Glenn Bonforte", "status": "Qualified"},
        ]
        body = self._patched_home_call(rows).get_json()
        self.assertEqual(body["at_risk_leads"], [])


if __name__ == "__main__":
    unittest.main()
