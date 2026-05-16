"""HTTP tests for the v0.4.1 admin criteria endpoints."""
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


class AdminCriteriaEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["CRITERIA_STORE_PATH"] = os.path.join(cls.tmp, "criteria.json")
        os.environ["PROJECT_STORE_DIR"] = os.path.join(cls.tmp, "projects")
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "criteria_store", "scope"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("CRITERIA_STORE_PATH", "PROJECT_STORE_DIR"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_list_returns_library(self):
        r = self.client.get("/api/admin/criteria")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn("library", body)
        self.assertIn("crm_build", body["library"])

    def test_upsert_new(self):
        r = self.client.post("/api/admin/criteria/crm_build", json={
            "key": "endpoint_test_key",
            "label": "Endpoint test",
            "role_driver": "CRM Developer",
            "scale_factor": 0.5,
        })
        self.assertEqual(r.status_code, 200, msg=r.get_json())
        keys = {c["key"] for c in r.get_json()["library"]["crm_build"]}
        self.assertIn("endpoint_test_key", keys)

    def test_upsert_missing_required_field_returns_400(self):
        r = self.client.post("/api/admin/criteria/crm_build", json={"key": "broken"})
        self.assertEqual(r.status_code, 400)

    def test_upsert_unknown_project_type_returns_400(self):
        r = self.client.post("/api/admin/criteria/no_such_type",
                             json={"key": "x", "label": "x"})
        self.assertEqual(r.status_code, 400)

    def test_delete(self):
        self.client.post("/api/admin/criteria/crm_build",
                         json={"key": "to_be_deleted", "label": "X"})
        r = self.client.delete("/api/admin/criteria/crm_build/to_be_deleted")
        self.assertEqual(r.status_code, 200)
        keys = {c["key"] for c in r.get_json()["library"]["crm_build"]}
        self.assertNotIn("to_be_deleted", keys)

    def test_delete_missing_returns_404(self):
        r = self.client.delete("/api/admin/criteria/crm_build/never_existed")
        self.assertEqual(r.status_code, 404)

    def test_reset_project_type(self):
        # Add a custom criterion, then reset and confirm it's gone
        self.client.post("/api/admin/criteria/crm_build",
                         json={"key": "tmp_for_reset", "label": "X"})
        r = self.client.post("/api/admin/criteria/crm_build/reset")
        self.assertEqual(r.status_code, 200)
        keys = {c["key"] for c in r.get_json()["library"]["crm_build"]}
        self.assertNotIn("tmp_for_reset", keys)

    def test_reset_all(self):
        self.client.post("/api/admin/criteria/data_work",
                         json={"key": "tmp", "label": "X"})
        r = self.client.post("/api/admin/criteria/reset_all")
        self.assertEqual(r.status_code, 200)
        keys = {c["key"] for c in r.get_json()["library"]["data_work"]}
        self.assertNotIn("tmp", keys)

    def test_new_criterion_visible_in_scope_library(self):
        """Adding a criterion shows up in the regular /api/scope/library too."""
        self.client.post("/api/admin/criteria/crm_build",
                         json={"key": "visible_in_scope", "label": "Visible"})
        r = self.client.get("/api/scope/library")
        self.assertEqual(r.status_code, 200)
        keys = {c["key"] for c in r.get_json()["criteria"]["crm_build"]}
        self.assertIn("visible_in_scope", keys)

    def test_new_criterion_can_be_saved_on_existing_project(self):
        """v0.4.1 contract: criteria added after a project exists should not
        break saves — update_criterion appends."""
        self.client.post("/api/scope/test_lead", json={
            "company_name": "Test", "project_types": ["crm_build"],
        })
        # Add a new criterion to the library after the project exists
        self.client.post("/api/admin/criteria/crm_build",
                         json={"key": "added_after_project", "label": "Late"})
        # Now save the project with an answer to the new criterion
        r = self.client.post("/api/scope/test_lead", json={
            "company_name": "Test", "project_types": ["crm_build"],
            "criteria_updates": [
                {"project_type": "crm_build", "key": "added_after_project",
                 "value": "yes", "status": "qualified"},
            ],
        })
        self.assertEqual(r.status_code, 200, msg=r.get_json())


if __name__ == "__main__":
    unittest.main()
