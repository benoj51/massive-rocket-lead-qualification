"""v0.9.0 — roadmap module + endpoints + SOW integration."""
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


class RoadmapStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["ROADMAP_STORE_DIR"] = self.tmp
        for mod in ("roadmap", "project_store"):
            sys.modules.pop(mod, None)

    def tearDown(self):
        os.environ.pop("ROADMAP_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_new_then_save_then_load(self):
        import roadmap
        r = roadmap.new_roadmap("lead-a", months=12, start_date="2026-06-01")
        r.milestones.append(roadmap.Milestone(
            id="", workstream="CRM Build", title="Discovery",
            month_offset=0, duration_months=3, phase="Understand",
        ))
        roadmap.save("lead-a", r)
        loaded = roadmap.load("lead-a")
        self.assertEqual(len(loaded.milestones), 1)
        self.assertEqual(loaded.milestones[0].title, "Discovery")
        self.assertEqual(loaded.start_date, "2026-06-01")

    def test_end_date_auto_derived_from_start_plus_months(self):
        import roadmap
        r = roadmap.new_roadmap("lead-b", months=12, start_date="2026-01-15")
        r.touch()
        # 2026-01-15 + 12 months = 2027-01-15
        self.assertEqual(r.end_date, "2027-01-15")

    def test_workstreams_from_scope(self):
        import roadmap
        self.assertEqual(
            roadmap.workstreams_from_scope(["crm_build", "data_work"]),
            ["CRM Build", "Data"],
        )
        # Empty scope falls back to a sensible default
        self.assertEqual(roadmap.workstreams_from_scope([]), ["Cross-cutting"])

    def test_seed_milestones_from_package(self):
        import roadmap, packages
        r = roadmap.new_roadmap("lead-c", months=6)
        pkg = packages.get_package("Braze - Migration")
        self.assertIsNotNone(pkg)
        roadmap.seed_milestones_from_package(r, pkg)
        self.assertGreater(len(r.milestones), 0)
        # All milestones should fit within the project length
        for m in r.milestones:
            self.assertLessEqual(m.month_offset + m.duration_months, r.months + 1)
        # Should have workstream tags
        for m in r.milestones:
            self.assertTrue(m.workstream)

    def test_milestone_normalises_inputs(self):
        import roadmap
        m = roadmap.Milestone(
            id="", workstream="CRM Build", title="t",
            month_offset=-3, duration_months=0,  # invalid
        )
        self.assertEqual(m.month_offset, 0)
        self.assertEqual(m.duration_months, 1)

    def test_round_trip_via_dict(self):
        import roadmap
        original = roadmap.new_roadmap("lead-rt", months=6, start_date="2026-03-01")
        original.milestones.append(roadmap.Milestone(
            id="", workstream="Data", title="Audit", month_offset=0,
            duration_months=2, phase="Understand",
        ))
        original.extended_engagement.append(roadmap.ExtendedItem(
            id="", year=2, title="CDP Phase 2", description="ride on year 1 wins",
            estimated_hours=200, estimated_price_usd=40_000,
        ))
        roadmap.save("lead-rt", original)
        loaded = roadmap.load("lead-rt")
        self.assertEqual(loaded.lead_id, "lead-rt")
        self.assertEqual(len(loaded.milestones), 1)
        self.assertEqual(len(loaded.extended_engagement), 1)
        self.assertEqual(loaded.extended_engagement[0].year, 2)


class RoadmapEndpointsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["ROADMAP_STORE_DIR"] = os.path.join(cls.tmp, "roadmaps")
        os.environ["PROJECT_STORE_DIR"] = os.path.join(cls.tmp, "projects")
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        for mod in ("server", "roadmap", "project_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("ROADMAP_STORE_DIR", "PROJECT_STORE_DIR"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_get_returns_null_when_no_roadmap(self):
        r = self.client.get("/api/roadmap/nope")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.get_json()["roadmap"])

    def test_post_creates_and_get_returns(self):
        r = self.client.post("/api/roadmap/lead-1", json={
            "months": 12, "start_date": "2026-07-01",
            "milestones": [
                {"workstream": "CRM Build", "title": "Kickoff",
                 "month_offset": 0, "duration_months": 1, "phase": "Understand"},
            ],
        })
        self.assertEqual(r.status_code, 200)
        got = self.client.get("/api/roadmap/lead-1").get_json()
        self.assertEqual(len(got["roadmap"]["milestones"]), 1)
        self.assertEqual(got["roadmap"]["start_date"], "2026-07-01")

    def test_seed_from_package(self):
        r = self.client.post("/api/roadmap/lead-pkg/seed-from-package",
                              json={"package_key": "Braze - Migration",
                                    "start_date": "2026-04-01"})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertGreater(len(body["roadmap"]["milestones"]), 0)

    def test_seed_from_unknown_package_returns_400(self):
        r = self.client.post("/api/roadmap/lead-x/seed-from-package",
                              json={"package_key": "Not Real"})
        self.assertEqual(r.status_code, 400)

    def test_ai_refine_without_anthropic_returns_503(self):
        # Create a roadmap first so we don't get 404
        self.client.post("/api/roadmap/lead-ai", json={"months": 12})
        r = self.client.post("/api/roadmap/lead-ai/ai-refine", json={})
        self.assertEqual(r.status_code, 503)

    def test_ai_suggest_extended_without_anthropic_returns_503(self):
        r = self.client.post("/api/roadmap/lead-x/ai-suggest-extended", json={})
        self.assertEqual(r.status_code, 503)


class SowIncludesRoadmapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["ROADMAP_STORE_DIR"] = os.path.join(cls.tmp, "roadmaps")
        os.environ["PROJECT_STORE_DIR"] = os.path.join(cls.tmp, "projects")
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        for mod in ("server", "roadmap", "project_store", "sow", "scope"):
            sys.modules.pop(mod, None)
        import project_store, scope as scope_module, roadmap as roadmap_module
        # Seed a project
        p = scope_module.new_project("sow-rm", "Roadmap Test", ["crm_build"])
        scope_module.transition(p, "pending_validation", actor="ae")
        scope_module.transition(p, "validated", actor="d1")
        project_store.save(p)
        # Seed a roadmap
        r = roadmap_module.new_roadmap("sow-rm", months=12, start_date="2026-06-01")
        r.milestones.append(roadmap_module.Milestone(
            id="", workstream="CRM Build", title="Discovery sprint",
            month_offset=0, duration_months=2, phase="Understand",
        ))
        r.extended_engagement.append(roadmap_module.ExtendedItem(
            id="", year=2, title="CDP rollout", description="Phase 2",
            estimated_hours=200, estimated_price_usd=40_000,
        ))
        roadmap_module.save("sow-rm", r)

    @classmethod
    def tearDownClass(cls):
        for k in ("ROADMAP_STORE_DIR", "PROJECT_STORE_DIR"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_snapshot_includes_roadmap(self):
        import sow
        snap = sow.build_snapshot("sow-rm")
        rm = snap["sections"].get("roadmap")
        self.assertIsNotNone(rm)
        self.assertEqual(len(rm["milestones"]), 1)
        self.assertEqual(len(rm["extended_engagement"]), 1)

    def test_html_render_includes_roadmap_sections(self):
        import sow
        snap = sow.build_snapshot("sow-rm")
        html = sow.render_html(snap, version=1)
        self.assertIn("Roadmap", html)
        self.assertIn("Discovery sprint", html)
        self.assertIn("Beyond Year 1", html)
        self.assertIn("CDP rollout", html)


if __name__ == "__main__":
    unittest.main()
