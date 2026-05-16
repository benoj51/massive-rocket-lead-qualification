"""End-to-end tests for the v0.4 scope + pricing API surface."""
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


class ScopeEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["PROJECT_STORE_DIR"] = cls.tmp
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "project_store", "scope"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("PROJECT_STORE_DIR", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_library_endpoint(self):
        r = self.client.get("/api/scope/library")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn("project_types", body)
        self.assertIn("criteria", body)
        self.assertIn("discovery_questions", body)
        self.assertIn("crm_build", body["project_types"])

    def test_upsert_then_get(self):
        r = self.client.post("/api/scope/deliveroo", json={
            "company_name": "Deliveroo",
            "project_types": ["crm_build", "data_work"],
        })
        self.assertEqual(r.status_code, 200, msg=r.get_json())
        got = self.client.get("/api/scope/deliveroo")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.get_json()["project"]["company_name"], "Deliveroo")
        # Two streams
        self.assertEqual(len(got.get_json()["project"]["streams"]), 2)

    def test_upsert_with_criteria_updates(self):
        self.client.post("/api/scope/d2", json={
            "company_name": "Acme",
            "project_types": ["crm_build"],
            "criteria_updates": [
                {"project_type": "crm_build", "key": "migrating_campaigns",
                 "value": "40", "status": "qualifying"},
            ],
        })
        got = self.client.get("/api/scope/d2").get_json()
        crit = next(c for c in got["project"]["streams"][0]["criteria"]
                    if c["key"] == "migrating_campaigns")
        self.assertEqual(crit["value"], "40")
        self.assertEqual(crit["status"], "qualifying")

    def test_transition_state_machine(self):
        self.client.post("/api/scope/d3", json={
            "company_name": "Bravo", "project_types": ["crm_build"]
        })
        # bad transition
        r = self.client.post("/api/scope/d3/transition", json={"action": "validated"})
        self.assertEqual(r.status_code, 400)
        # good path
        r = self.client.post("/api/scope/d3/transition",
                             json={"action": "pending_validation"})
        self.assertEqual(r.status_code, 200)
        r = self.client.post("/api/scope/d3/transition",
                             json={"action": "validated", "notes": "approved"})
        self.assertEqual(r.status_code, 200)
        summary = r.get_json()["summary"]
        self.assertEqual(summary["validation_status"], "validated")
        self.assertTrue(summary["ready_for_pricing"])

    def test_pricing_preview_from_lead(self):
        self.client.post("/api/scope/d4", json={
            "company_name": "Charlie", "project_types": ["crm_build"]
        })
        r = self.client.post("/api/pricing/preview",
                             json={"lead_id": "d4", "months": 12})
        self.assertEqual(r.status_code, 200, msg=r.get_json())
        q = r.get_json()
        self.assertGreater(q["totals"]["net_usd"], 0)
        self.assertEqual(len(q["monthly"]), 12)

    def test_pricing_preview_from_raw_inputs(self):
        r = self.client.post("/api/pricing/preview", json={
            "project_types": ["crm_build"], "months": 12,
        })
        self.assertEqual(r.status_code, 200)
        # Should match the reference deal totals (modulo discount drift)
        self.assertEqual(r.get_json()["totals"]["gross_usd"], 1_191_360)

    def test_pricing_preview_missing_input(self):
        r = self.client.post("/api/pricing/preview", json={"months": 12})
        self.assertEqual(r.status_code, 400)

    def test_list_projects_endpoint(self):
        self.client.post("/api/scope/d5",
                         json={"company_name": "E", "project_types": ["crm_build"]})
        self.client.post("/api/scope/d5/transition",
                         json={"action": "pending_validation"})
        all_resp = self.client.get("/api/scope/projects").get_json()
        pending_resp = self.client.get("/api/scope/projects?pending_validation_only=1").get_json()
        self.assertGreaterEqual(all_resp["count"], 1)
        self.assertGreaterEqual(pending_resp["count"], 1)
        # pending list should be a subset of all list
        self.assertLessEqual(pending_resp["count"], all_resp["count"])


if __name__ == "__main__":
    unittest.main()
