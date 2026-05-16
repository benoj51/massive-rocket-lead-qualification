"""SOW renderer + store + endpoints tests."""
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


class SowStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["SOW_STORE_DIR"] = self.tmp

    def tearDown(self):
        os.environ.pop("SOW_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_first_save_is_v1(self):
        import sow_store
        v = sow_store.save("lead_a", {"company_name": "A"})
        self.assertEqual(v, 1)

    def test_versions_auto_increment(self):
        import sow_store
        sow_store.save("lead_b", {"company_name": "B"})
        sow_store.save("lead_b", {"company_name": "B"})
        v3 = sow_store.save("lead_b", {"company_name": "B"})
        self.assertEqual(v3, 3)
        versions = sow_store.list_versions("lead_b")
        self.assertEqual([r["version"] for r in versions], [3, 2, 1])

    def test_load_specific_version(self):
        import sow_store
        sow_store.save("lead_c", {"foo": 1})
        sow_store.save("lead_c", {"foo": 2})
        sow_store.save("lead_c", {"foo": 3})
        self.assertEqual(sow_store.load("lead_c", 2).get("foo"), 2)

    def test_latest(self):
        import sow_store
        sow_store.save("lead_d", {"foo": 1})
        sow_store.save("lead_d", {"foo": 2})
        self.assertEqual(sow_store.latest("lead_d").get("foo"), 2)

    def test_load_unknown_version_returns_none(self):
        import sow_store
        self.assertIsNone(sow_store.load("nobody", 1))
        self.assertIsNone(sow_store.latest("nobody"))


class SowBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["PROJECT_STORE_DIR"] = os.path.join(cls.tmp, "projects")
        os.environ["CRITERIA_STORE_PATH"] = os.path.join(cls.tmp, "criteria.json")
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        for mod in ("project_store", "criteria_store", "scope", "sow"):
            sys.modules.pop(mod, None)

        import project_store, scope
        p = scope.new_project("deliveroo_co_uk", "Deliveroo", ["crm_build"])
        scope.update_criterion(p, "crm_build", "migrating_campaigns", value="25", status="qualified")
        scope.update_criterion(p, "crm_build", "channels", value="Email, Push", status="qualified")
        scope.update_criterion(p, "crm_build", "html_templates_count", value="4", status="qualifying")
        scope.transition(p, "pending_validation", actor="ae1")
        scope.transition(p, "validated", actor="d1", notes="ok")
        project_store.save(p)

    @classmethod
    def tearDownClass(cls):
        for k in ("PROJECT_STORE_DIR", "CRITERIA_STORE_PATH", "APOLLO_USE_FIXTURES"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_build_snapshot_has_all_sections(self):
        import sow
        snap = sow.build_snapshot("deliveroo_co_uk")
        self.assertEqual(snap["company_name"], "Deliveroo")
        self.assertEqual(snap["validation_status_at_generation"], "validated")
        sec = snap["sections"]
        for key in ("executive_summary", "engagement_overview", "scope_of_work",
                    "team_and_phases", "investment", "assumptions", "out_of_scope"):
            self.assertIn(key, sec)
        # Investment should reproduce a real net total
        self.assertGreater(sec["investment"]["totals"]["net_usd"], 0)

    def test_scope_of_work_only_includes_qualifying_or_better(self):
        import sow
        snap = sow.build_snapshot("deliveroo_co_uk")
        crm_stream = next(s for s in snap["sections"]["scope_of_work"]
                          if s["project_type"] == "crm_build")
        labels = {item["label"] for item in crm_stream["in_scope"]}
        # The two qualified + one qualifying criteria should appear
        self.assertIn("Number of campaigns to migrate", labels)
        self.assertIn("Channels in scope", labels)
        self.assertIn("Custom HTML templates required", labels)
        # An unanswered Unqualified criterion should NOT appear
        self.assertNotIn("Net-new campaigns? Count" if False else "Number of net-new campaigns", labels)

    def test_render_html_returns_full_page(self):
        import sow
        snap = sow.build_snapshot("deliveroo_co_uk")
        html = sow.render_html(snap, version=1)
        self.assertIn("<!doctype html>", html)
        self.assertIn("Deliveroo", html)
        self.assertIn("Statement of Work", html)
        self.assertIn("Print / Save as PDF", html)
        # Investment numbers should appear
        self.assertIn("Total investment", html)

    def test_build_snapshot_unknown_lead_raises(self):
        import sow
        with self.assertRaises(ValueError):
            sow.build_snapshot("does_not_exist")


class SowEndpointsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["PROJECT_STORE_DIR"] = os.path.join(cls.tmp, "projects")
        os.environ["CRITERIA_STORE_PATH"] = os.path.join(cls.tmp, "criteria.json")
        os.environ["SOW_STORE_DIR"] = os.path.join(cls.tmp, "sows")
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "project_store", "criteria_store", "scope", "sow", "sow_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()
        # Seed a project
        cls.client.post("/api/scope/sow_test_lead", json={
            "company_name": "SOW Test Co",
            "project_types": ["crm_build"],
            "criteria_updates": [
                {"project_type": "crm_build", "key": "migrating_campaigns",
                 "value": "30", "status": "qualified"},
            ],
        })

    @classmethod
    def tearDownClass(cls):
        for k in ("PROJECT_STORE_DIR", "CRITERIA_STORE_PATH", "SOW_STORE_DIR", "APOLLO_USE_FIXTURES"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_post_creates_v1(self):
        r = self.client.post("/api/sow/sow_test_lead", json={})
        self.assertEqual(r.status_code, 200, msg=r.get_json())
        body = r.get_json()
        self.assertEqual(body["version"], 1)
        self.assertIn("render_url", body)
        self.assertIn("snapshot", body)
        self.assertEqual(body["snapshot"]["company_name"], "SOW Test Co")

    def _seed_project(self, lead_id: str, name: str = "Seed Co"):
        self.client.post(f"/api/scope/{lead_id}", json={
            "company_name": name, "project_types": ["crm_build"],
        })

    def test_post_increments_version(self):
        self._seed_project("sow_test_lead2", "Two")
        self.client.post("/api/sow/sow_test_lead2", json={"months": 12})
        r2 = self.client.post("/api/sow/sow_test_lead2", json={})
        self.assertEqual(r2.get_json()["version"], 2)

    def test_post_unknown_lead_returns_404(self):
        r = self.client.post("/api/sow/no_such_lead", json={})
        self.assertEqual(r.status_code, 404)

    def test_list_returns_versions(self):
        self._seed_project("sow_list_test", "ListCo")
        self.client.post("/api/sow/sow_list_test", json={})
        self.client.post("/api/sow/sow_list_test", json={})
        r = self.client.get("/api/sow/sow_list_test")
        self.assertEqual(r.status_code, 200)
        versions = r.get_json()["versions"]
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[0]["version"], 2)  # newest first

    def test_get_json_returns_snapshot(self):
        self._seed_project("sow_json_test", "JsonCo")
        r1 = self.client.post("/api/sow/sow_json_test", json={})
        version = r1.get_json()["version"]
        r = self.client.get(f"/api/sow/sow_json_test/v{version}.json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["company_name"], "JsonCo")

    def test_get_html_returns_printable(self):
        self.client.post("/api/scope/sow_html_test", json={
            "company_name": "HTML Test", "project_types": ["crm_build"]})
        r1 = self.client.post("/api/sow/sow_html_test", json={})
        version = r1.get_json()["version"]
        r = self.client.get(f"/api/sow/sow_html_test/v{version}.html")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"<!doctype html>", r.data)
        self.assertIn(b"Statement of Work", r.data)
        self.assertIn(b"HTML Test", r.data)

    def test_get_html_unknown_version_returns_404(self):
        r = self.client.get("/api/sow/sow_test_lead/v999.html")
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
