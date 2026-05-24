"""v1.0.0bk — live projects + OKRs + promote-to-live tests."""
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


# -----------------------------------------------------------------
# Layer 1: live_projects_store
# -----------------------------------------------------------------

class LiveProjectsStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["LIVE_PROJECTS_STORE_DIR"] = self.tmp
        sys.modules.pop("live_projects_store", None)
        import live_projects_store
        self.store = live_projects_store

    def tearDown(self):
        os.environ.pop("LIVE_PROJECTS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_create_and_get(self):
        p = self.store.create("lead-abc", "Shell Loyalty",
                                owner="Ben", summary="Loyalty rebuild")
        self.assertEqual(p["lead_id"], "lead-abc")
        self.assertEqual(p["name"], "Shell Loyalty")
        self.assertEqual(p["status"], "active")
        self.assertEqual(p["owner"], "Ben")
        fetched = self.store.get(p["id"])
        self.assertEqual(fetched["id"], p["id"])

    def test_create_uses_today_when_no_started_at(self):
        p = self.store.create("lead-abc", "X")
        # YYYY-MM-DD shape.
        import re
        self.assertTrue(re.match(r"^\d{4}-\d{2}-\d{2}$", p["started_at"]))

    def test_only_one_live_project_per_lead(self):
        self.store.create("lead-abc", "First")
        with self.assertRaises(self.store.LiveProjectsStoreError):
            self.store.create("lead-abc", "Second")

    def test_get_by_lead(self):
        self.store.create("lead-abc", "Project A")
        found = self.store.get_by_lead("lead-abc")
        self.assertIsNotNone(found)
        self.assertEqual(found["name"], "Project A")
        self.assertIsNone(self.store.get_by_lead("nonexistent"))

    def test_list_filter_by_status(self):
        p1 = self.store.create("a", "A")
        p2 = self.store.create("b", "B")
        self.store.set_status(p2["id"], "completed")
        active = self.store.list_all(status="active")
        completed = self.store.list_all(status="completed")
        self.assertEqual([p["id"] for p in active], [p1["id"]])
        self.assertEqual([p["id"] for p in completed], [p2["id"]])

    def test_status_transition_sets_ended_at(self):
        p = self.store.create("a", "A")
        updated = self.store.set_status(p["id"], "completed")
        self.assertEqual(updated["status"], "completed")
        self.assertIsNotNone(updated["ended_at"])

    def test_status_transition_back_to_active_clears_ended_at(self):
        p = self.store.create("a", "A")
        self.store.set_status(p["id"], "completed")
        re_opened = self.store.set_status(p["id"], "active")
        self.assertEqual(re_opened["status"], "active")
        self.assertIsNone(re_opened["ended_at"])

    def test_update_validates_status_enum(self):
        p = self.store.create("a", "A")
        with self.assertRaises(self.store.LiveProjectsStoreError):
            self.store.set_status(p["id"], "invalid-status")

    def test_update_validates_date_shape(self):
        p = self.store.create("a", "A")
        with self.assertRaises(self.store.LiveProjectsStoreError):
            self.store.update(p["id"], started_at="not-a-date")

    def test_update_rejects_unknown_field(self):
        p = self.store.create("a", "A")
        with self.assertRaises(self.store.LiveProjectsStoreError):
            self.store.update(p["id"], lead_id="changed")

    def test_delete(self):
        p = self.store.create("a", "A")
        self.assertTrue(self.store.delete(p["id"]))
        self.assertIsNone(self.store.get(p["id"]))
        self.assertFalse(self.store.delete(p["id"]))

    def test_validation_lead_id_required(self):
        with self.assertRaises(self.store.LiveProjectsStoreError):
            self.store.create("", "X")

    def test_validation_name_required(self):
        with self.assertRaises(self.store.LiveProjectsStoreError):
            self.store.create("a", "")


# -----------------------------------------------------------------
# Layer 2: live_project_okrs_store
# -----------------------------------------------------------------

class LiveProjectOkrsStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["LIVE_PROJECT_OKRS_STORE_DIR"] = self.tmp
        sys.modules.pop("live_project_okrs_store", None)
        import live_project_okrs_store
        self.store = live_project_okrs_store

    def tearDown(self):
        os.environ.pop("LIVE_PROJECT_OKRS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_create_with_key_results(self):
        okr = self.store.create("proj-1", "Q2 2026",
                                  "Launch loyalty MVP",
                                  key_results=[
            {"description": "Rollout to 10% stations",
             "target": "10", "unit": "%", "current": "5",
             "status": "on_track"},
            {"description": "Onboard 50 sites", "target": "50",
             "current": "20", "status": "at_risk"},
        ])
        self.assertEqual(okr["quarter"], "Q2 2026")
        self.assertEqual(len(okr["key_results"]), 2)
        # IDs were assigned per KR.
        self.assertTrue(all(kr["id"] for kr in okr["key_results"]))

    def test_summarise(self):
        okr = self.store.create("proj-1", "Q2 2026", "Obj",
                                  key_results=[
            {"description": "kr1", "status": "on_track"},
            {"description": "kr2", "status": "on_track"},
            {"description": "kr3", "status": "at_risk"},
            {"description": "kr4", "status": "done"},
        ])
        s = self.store.summarise(okr)
        self.assertEqual(s["total_krs"], 4)
        self.assertEqual(s["on_track"], 2)
        self.assertEqual(s["at_risk"], 1)
        self.assertEqual(s["done"], 1)
        # health = (on_track + done) / total = 3/4 = 75%
        self.assertEqual(s["health_pct"], 75)

    def test_summarise_empty(self):
        okr = self.store.create("proj-1", "Q2 2026", "Obj")
        s = self.store.summarise(okr)
        self.assertEqual(s["total_krs"], 0)
        self.assertEqual(s["health_pct"], 0)

    def test_add_key_result(self):
        okr = self.store.create("proj-1", "Q2 2026", "Obj")
        kr = self.store.add_key_result(okr["id"], {
            "description": "new kr", "target": "100"})
        self.assertTrue(kr["id"])
        self.assertEqual(kr["target"], "100")
        # Persisted.
        fetched = self.store.get(okr["id"])
        self.assertEqual(len(fetched["key_results"]), 1)

    def test_update_key_result(self):
        okr = self.store.create("proj-1", "Q2 2026", "Obj",
                                  key_results=[
            {"description": "kr", "current": "5", "status": "on_track"}])
        kr_id = okr["key_results"][0]["id"]
        updated = self.store.update_key_result(okr["id"], kr_id,
                                                  current="9",
                                                  status="done")
        self.assertEqual(updated["current"], "9")
        self.assertEqual(updated["status"], "done")

    def test_delete_key_result(self):
        okr = self.store.create("proj-1", "Q2 2026", "Obj",
                                  key_results=[
            {"description": "a"}, {"description": "b"}])
        a_id = okr["key_results"][0]["id"]
        self.assertTrue(self.store.delete_key_result(okr["id"], a_id))
        remaining = self.store.get(okr["id"])
        self.assertEqual([k["description"] for k in remaining["key_results"]],
                         ["b"])

    def test_list_for_project_sorted_by_quarter(self):
        self.store.create("p", "Q1 2026", "obj1")
        self.store.create("p", "Q3 2026", "obj3")
        self.store.create("p", "Q2 2026", "obj2")
        out = self.store.list_for_project("p")
        # Newest quarter first.
        self.assertEqual([o["quarter"] for o in out],
                         ["Q3 2026", "Q2 2026", "Q1 2026"])

    def test_validate_status_enum_on_kr(self):
        with self.assertRaises(self.store.LiveProjectOkrsStoreError):
            self.store.create("p", "Q1 2026", "obj",
                                key_results=[
                {"description": "x", "status": "bogus"}])

    def test_validation_quarter_required(self):
        with self.assertRaises(self.store.LiveProjectOkrsStoreError):
            self.store.create("p", "", "obj")


# -----------------------------------------------------------------
# Layer 3: endpoints + promote-to-live
# -----------------------------------------------------------------

class LiveProjectsEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["LIVE_PROJECTS_STORE_DIR"] = os.path.join(cls.tmp, "lp")
        os.environ["LIVE_PROJECT_OKRS_STORE_DIR"] = os.path.join(cls.tmp, "okrs")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "live_projects_store",
                    "live_project_okrs_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("LIVE_PROJECTS_STORE_DIR", "LIVE_PROJECT_OKRS_STORE_DIR",
                  "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        import live_projects_store, live_project_okrs_store
        for f in live_projects_store._store_dir().glob("*.json"):
            f.unlink()
        for f in live_project_okrs_store._store_dir().glob("*.json"):
            f.unlink()

    def test_promote_lead_to_live_creates_project(self):
        with patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.get_page.return_value = {
                "id": "lead-shell", "company": "Shell",
                "owner": "Ben Ojuolape"}
            MockSync.return_value.list_pipeline.return_value = []
            r = self.client.post(
                "/api/lead/lead-shell/promote-to-live",
                json={})
        self.assertEqual(r.status_code, 201)
        body = r.get_json()
        self.assertTrue(body["created"])
        # Default name pulled from Notion company.
        self.assertEqual(body["project"]["name"], "Shell")
        # Default owner from lead.
        self.assertEqual(body["project"]["owner"], "Ben Ojuolape")
        self.assertEqual(body["project"]["status"], "active")

    def test_promote_idempotent(self):
        """Second promote returns the existing project, doesn't error."""
        with patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.get_page.return_value = {
                "id": "lead-shell", "company": "Shell"}
            MockSync.return_value.list_pipeline.return_value = []
            r1 = self.client.post("/api/lead/lead-shell/promote-to-live",
                                   json={})
            r2 = self.client.post("/api/lead/lead-shell/promote-to-live",
                                   json={})
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 200)
        self.assertFalse(r2.get_json()["created"])
        # Same project id either way.
        self.assertEqual(r1.get_json()["project"]["id"],
                         r2.get_json()["project"]["id"])

    def test_list_with_status_filter(self):
        with patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.get_page.return_value = {
                "id": "a", "company": "A"}
            MockSync.return_value.list_pipeline.return_value = []
            r = self.client.post("/api/lead/a/promote-to-live", json={})
            pid = r.get_json()["project"]["id"]
            self.client.patch(f"/api/live-projects/{pid}",
                                json={"status": "completed"})
            with patch.object(self.server, "NotionSync") as M2:
                M2.return_value.list_pipeline.return_value = []
                completed = self.client.get(
                    "/api/live-projects?status=completed").get_json()
                active = self.client.get(
                    "/api/live-projects?status=active").get_json()
        self.assertEqual(len(completed["items"]), 1)
        self.assertEqual(len(active["items"]), 0)

    def test_okr_lifecycle_end_to_end(self):
        """Create project → add OKR → add KR → update KR → delete."""
        with patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.get_page.return_value = {
                "id": "lead-x", "company": "X"}
            MockSync.return_value.list_pipeline.return_value = []
            r = self.client.post("/api/lead/lead-x/promote-to-live",
                                  json={})
        pid = r.get_json()["project"]["id"]
        # Add an OKR.
        r = self.client.post(f"/api/live-projects/{pid}/okrs",
                              json={"quarter": "Q2 2026",
                                    "objective": "Launch loyalty MVP",
                                    "key_results": [
                                        {"description": "10% rollout",
                                         "target": "10", "unit": "%",
                                         "current": "0",
                                         "status": "on_track"},
                                    ]})
        self.assertEqual(r.status_code, 201)
        okr_id = r.get_json()["okr"]["id"]
        # Detail should reflect the OKR + summary.
        with patch.object(self.server, "NotionSync") as M2:
            M2.return_value.get_page.return_value = {
                "id": "lead-x", "company": "X"}
            detail = self.client.get(
                f"/api/live-projects/{pid}").get_json()
        self.assertEqual(len(detail["okrs"]), 1)
        self.assertEqual(detail["okrs"][0]["summary"]["total_krs"], 1)
        # Add another KR via the nested endpoint.
        r = self.client.post(f"/api/okrs/{okr_id}/key-results",
                              json={"description": "Site count",
                                    "target": "50", "current": "10"})
        self.assertEqual(r.status_code, 201)
        kr_id = r.get_json()["key_result"]["id"]
        # Update it.
        r = self.client.patch(
            f"/api/okrs/{okr_id}/key-results/{kr_id}",
            json={"status": "done", "current": "50"})
        self.assertEqual(r.get_json()["key_result"]["status"], "done")
        # Delete it.
        r = self.client.delete(
            f"/api/okrs/{okr_id}/key-results/{kr_id}")
        self.assertTrue(r.get_json()["deleted"])

    def test_get_unknown_project_returns_404(self):
        r = self.client.get("/api/live-projects/does-not-exist")
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
