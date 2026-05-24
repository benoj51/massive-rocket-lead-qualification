"""v1.0.0bo — account expansion (land-and-expand) tests.

Covers:
1. expansion_targets_store CRUD + status transitions + contact CRUD
   + mark_converted.
2. /api/expansion-targets* endpoints (create / get / patch / delete
   + nested contacts + convert-to-lead).
3. /api/expansion/overview aggregator: groups targets under their
   landed-account anchor, surfaces totals, sorts greenfield first,
   handles unlinked anchors gracefully.
"""
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
# Layer 1: expansion_targets_store
# -----------------------------------------------------------------

class ExpansionTargetsStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["EXPANSION_TARGETS_STORE_DIR"] = self.tmp
        sys.modules.pop("expansion_targets_store", None)
        import expansion_targets_store
        self.store = expansion_targets_store

    def tearDown(self):
        os.environ.pop("EXPANSION_TARGETS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- create / get -----------------------------------------------

    def test_create_and_get(self):
        t = self.store.create("shell-na", "Shell UK",
                                region="UK", vertical="Energy",
                                notes="Marina intro pending")
        self.assertEqual(t["anchor_lead_id"], "shell-na")
        self.assertEqual(t["name"], "Shell UK")
        self.assertEqual(t["region"], "UK")
        self.assertEqual(t["vertical"], "Energy")
        self.assertEqual(t["status"], "greenfield")
        self.assertEqual(t["notes"], "Marina intro pending")
        self.assertEqual(t["contacts"], [])
        self.assertIsNone(t["converted_lead_id"])
        self.assertIsNone(t["converted_at"])
        fetched = self.store.get(t["id"])
        self.assertEqual(fetched["id"], t["id"])

    def test_create_validates_anchor(self):
        with self.assertRaises(self.store.ExpansionTargetsStoreError):
            self.store.create("", "Shell UK")

    def test_create_validates_name(self):
        with self.assertRaises(self.store.ExpansionTargetsStoreError):
            self.store.create("shell-na", "")

    def test_create_strips_blanks_to_none(self):
        t = self.store.create("shell-na", "Shell UK",
                                region="   ", vertical="", notes="")
        self.assertIsNone(t["region"])
        self.assertIsNone(t["vertical"])
        self.assertIsNone(t["notes"])

    def test_get_returns_none_for_unknown(self):
        self.assertIsNone(self.store.get("nope"))
        self.assertIsNone(self.store.get(""))

    # ---- list_all + filters -----------------------------------------

    def test_list_all_sorted_by_anchor_then_name(self):
        self.store.create("b-anchor", "Zebra")
        self.store.create("a-anchor", "Beta")
        self.store.create("a-anchor", "Alpha")
        out = self.store.list_all()
        self.assertEqual([(t["anchor_lead_id"], t["name"]) for t in out],
                         [("a-anchor", "Alpha"),
                          ("a-anchor", "Beta"),
                          ("b-anchor", "Zebra")])

    def test_list_filter_by_status(self):
        a = self.store.create("x", "A")
        b = self.store.create("x", "B")
        self.store.update(b["id"], status="qualifying")
        greenfield = self.store.list_all(status="greenfield")
        qualifying = self.store.list_all(status="qualifying")
        self.assertEqual([t["id"] for t in greenfield], [a["id"]])
        self.assertEqual([t["id"] for t in qualifying], [b["id"]])

    def test_list_by_anchor(self):
        a = self.store.create("shell-na", "Shell UK")
        b = self.store.create("shell-na", "Shell APAC")
        self.store.create("other", "Other Co")
        out = self.store.list_by_anchor("shell-na")
        self.assertEqual({t["id"] for t in out}, {a["id"], b["id"]})

    def test_list_by_anchor_empty_string_returns_empty(self):
        self.store.create("x", "X")
        self.assertEqual(self.store.list_by_anchor(""), [])

    # ---- update ------------------------------------------------------

    def test_update_status_transitions(self):
        t = self.store.create("x", "T")
        for s in ("researching", "qualifying", "dropped",
                  "converted_to_lead", "greenfield"):
            updated = self.store.update(t["id"], status=s)
            self.assertEqual(updated["status"], s)

    def test_update_validates_status(self):
        t = self.store.create("x", "T")
        with self.assertRaises(self.store.ExpansionTargetsStoreError):
            self.store.update(t["id"], status="bogus")

    def test_update_rejects_unknown_field(self):
        t = self.store.create("x", "T")
        with self.assertRaises(self.store.ExpansionTargetsStoreError):
            self.store.update(t["id"], anchor_lead_id="changed")

    def test_update_name_cannot_be_empty(self):
        t = self.store.create("x", "T")
        with self.assertRaises(self.store.ExpansionTargetsStoreError):
            self.store.update(t["id"], name="")

    def test_update_blanks_clear_to_none(self):
        t = self.store.create("x", "T", region="UK", vertical="Energy",
                                notes="early")
        u = self.store.update(t["id"], region="", vertical="", notes="")
        self.assertIsNone(u["region"])
        self.assertIsNone(u["vertical"])
        self.assertIsNone(u["notes"])

    def test_update_unknown_id_returns_none(self):
        self.assertIsNone(self.store.update("nope", status="dropped"))

    def test_update_contacts_via_full_replace(self):
        t = self.store.create("x", "T")
        u = self.store.update(t["id"], contacts=[
            {"name": "Sarah Johnson", "title": "Head of Loyalty"},
        ])
        self.assertEqual(len(u["contacts"]), 1)
        self.assertEqual(u["contacts"][0]["name"], "Sarah Johnson")
        self.assertTrue(u["contacts"][0]["id"])

    def test_update_contacts_must_be_list(self):
        t = self.store.create("x", "T")
        with self.assertRaises(self.store.ExpansionTargetsStoreError):
            self.store.update(t["id"], contacts="not a list")

    # ---- delete ------------------------------------------------------

    def test_delete(self):
        t = self.store.create("x", "T")
        self.assertTrue(self.store.delete(t["id"]))
        self.assertIsNone(self.store.get(t["id"]))
        self.assertFalse(self.store.delete(t["id"]))

    def test_delete_unknown(self):
        self.assertFalse(self.store.delete("nope"))
        self.assertFalse(self.store.delete(""))

    # ---- contacts ----------------------------------------------------

    def test_add_contact(self):
        t = self.store.create("x", "T")
        c = self.store.add_contact(t["id"], {
            "name": "Sarah Johnson",
            "title": "Head of Loyalty UK",
            "email": "sarah@shell.com",
            "source": "Marina at Braze",
        })
        self.assertEqual(c["name"], "Sarah Johnson")
        self.assertEqual(c["email"], "sarah@shell.com")
        self.assertTrue(c["id"])
        # Persisted.
        fetched = self.store.get(t["id"])
        self.assertEqual(len(fetched["contacts"]), 1)
        self.assertEqual(fetched["contacts"][0]["id"], c["id"])

    def test_add_contact_requires_name(self):
        t = self.store.create("x", "T")
        with self.assertRaises(self.store.ExpansionTargetsStoreError):
            self.store.add_contact(t["id"], {"title": "no name"})

    def test_add_contact_unknown_target(self):
        with self.assertRaises(self.store.ExpansionTargetsStoreError):
            self.store.add_contact("nope", {"name": "X"})

    def test_update_contact(self):
        t = self.store.create("x", "T")
        c = self.store.add_contact(t["id"], {"name": "Old Name"})
        u = self.store.update_contact(t["id"], c["id"],
                                          name="New Name",
                                          email="x@y.com")
        self.assertEqual(u["name"], "New Name")
        self.assertEqual(u["email"], "x@y.com")
        # ID preserved.
        self.assertEqual(u["id"], c["id"])

    def test_update_contact_rejects_unknown_field(self):
        t = self.store.create("x", "T")
        c = self.store.add_contact(t["id"], {"name": "X"})
        with self.assertRaises(self.store.ExpansionTargetsStoreError):
            self.store.update_contact(t["id"], c["id"], bogus="z")

    def test_update_contact_unknown_returns_none(self):
        t = self.store.create("x", "T")
        self.assertIsNone(
            self.store.update_contact(t["id"], "no-such-id", name="X"))
        self.assertIsNone(
            self.store.update_contact("nope", "x", name="X"))

    def test_delete_contact(self):
        t = self.store.create("x", "T")
        c = self.store.add_contact(t["id"], {"name": "X"})
        self.assertTrue(self.store.delete_contact(t["id"], c["id"]))
        # Gone.
        fetched = self.store.get(t["id"])
        self.assertEqual(fetched["contacts"], [])
        # Second delete is False.
        self.assertFalse(self.store.delete_contact(t["id"], c["id"]))

    def test_delete_contact_unknown_target(self):
        self.assertFalse(self.store.delete_contact("nope", "x"))

    # ---- mark_converted ---------------------------------------------

    def test_mark_converted(self):
        t = self.store.create("shell-na", "Shell UK")
        u = self.store.mark_converted(t["id"], "new-lead-page-id")
        self.assertEqual(u["status"], "converted_to_lead")
        self.assertEqual(u["converted_lead_id"], "new-lead-page-id")
        self.assertIsNotNone(u["converted_at"])

    def test_mark_converted_is_idempotent(self):
        """Re-marking should update the converted_lead_id, not error."""
        t = self.store.create("shell-na", "Shell UK")
        self.store.mark_converted(t["id"], "first-lead")
        u = self.store.mark_converted(t["id"], "second-lead")
        # Last write wins.
        self.assertEqual(u["converted_lead_id"], "second-lead")
        self.assertEqual(u["status"], "converted_to_lead")

    def test_mark_converted_validates(self):
        self.assertIsNone(self.store.mark_converted("", "lead"))
        self.assertIsNone(self.store.mark_converted("t", ""))
        self.assertIsNone(self.store.mark_converted("nope", "lead"))


# -----------------------------------------------------------------
# Layer 2: endpoints
# -----------------------------------------------------------------

class ExpansionEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["EXPANSION_TARGETS_STORE_DIR"] = os.path.join(cls.tmp, "ex")
        os.environ["LIVE_PROJECTS_STORE_DIR"] = os.path.join(cls.tmp, "lp")
        os.environ["LIVE_PROJECT_OKRS_STORE_DIR"] = os.path.join(cls.tmp, "okrs")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "expansion_targets_store",
                    "live_projects_store", "live_project_okrs_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("EXPANSION_TARGETS_STORE_DIR",
                  "LIVE_PROJECTS_STORE_DIR",
                  "LIVE_PROJECT_OKRS_STORE_DIR",
                  "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        import expansion_targets_store, live_projects_store
        for f in expansion_targets_store._store_dir().glob("*.json"):
            f.unlink()
        for f in live_projects_store._store_dir().glob("*.json"):
            f.unlink()

    # ---- target CRUD ------------------------------------------------

    def test_create_target_endpoint(self):
        r = self.client.post("/api/expansion-targets", json={
            "anchor_lead_id": "shell-na",
            "name":           "Shell UK",
            "region":         "UK",
        })
        self.assertEqual(r.status_code, 201)
        t = r.get_json()["target"]
        self.assertEqual(t["name"], "Shell UK")
        self.assertEqual(t["status"], "greenfield")

    def test_create_validation_400(self):
        r = self.client.post("/api/expansion-targets",
                              json={"name": "X"})  # no anchor
        self.assertEqual(r.status_code, 400)
        self.assertIn("anchor_lead_id", r.get_json()["error"])

    def test_get_target_endpoint(self):
        r = self.client.post("/api/expansion-targets", json={
            "anchor_lead_id": "x", "name": "Y"})
        tid = r.get_json()["target"]["id"]
        r = self.client.get(f"/api/expansion-targets/{tid}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["target"]["name"], "Y")

    def test_get_unknown_target_404(self):
        r = self.client.get("/api/expansion-targets/does-not-exist")
        self.assertEqual(r.status_code, 404)

    def test_patch_target_endpoint(self):
        r = self.client.post("/api/expansion-targets", json={
            "anchor_lead_id": "x", "name": "Y"})
        tid = r.get_json()["target"]["id"]
        r = self.client.patch(f"/api/expansion-targets/{tid}",
                                json={"status": "qualifying",
                                      "notes": "talking to head of loyalty"})
        self.assertEqual(r.status_code, 200)
        t = r.get_json()["target"]
        self.assertEqual(t["status"], "qualifying")
        self.assertEqual(t["notes"], "talking to head of loyalty")

    def test_patch_invalid_status_400(self):
        r = self.client.post("/api/expansion-targets", json={
            "anchor_lead_id": "x", "name": "Y"})
        tid = r.get_json()["target"]["id"]
        r = self.client.patch(f"/api/expansion-targets/{tid}",
                                json={"status": "bogus"})
        self.assertEqual(r.status_code, 400)

    def test_patch_unknown_target_404(self):
        r = self.client.patch("/api/expansion-targets/nope",
                                json={"status": "dropped"})
        self.assertEqual(r.status_code, 404)

    def test_delete_target_endpoint(self):
        r = self.client.post("/api/expansion-targets", json={
            "anchor_lead_id": "x", "name": "Y"})
        tid = r.get_json()["target"]["id"]
        r = self.client.delete(f"/api/expansion-targets/{tid}")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["deleted"])
        # Second delete 404.
        r = self.client.delete(f"/api/expansion-targets/{tid}")
        self.assertEqual(r.status_code, 404)

    # ---- contact CRUD ----------------------------------------------

    def test_contact_lifecycle_endpoints(self):
        r = self.client.post("/api/expansion-targets", json={
            "anchor_lead_id": "x", "name": "Y"})
        tid = r.get_json()["target"]["id"]
        # Add.
        r = self.client.post(
            f"/api/expansion-targets/{tid}/contacts",
            json={"name": "Sarah", "title": "Head of Loyalty"})
        self.assertEqual(r.status_code, 201)
        cid = r.get_json()["contact"]["id"]
        # Update.
        r = self.client.patch(
            f"/api/expansion-targets/{tid}/contacts/{cid}",
            json={"email": "sarah@shell.com"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["contact"]["email"],
                         "sarah@shell.com")
        # Delete.
        r = self.client.delete(
            f"/api/expansion-targets/{tid}/contacts/{cid}")
        self.assertEqual(r.status_code, 200)
        # Second delete 404.
        r = self.client.delete(
            f"/api/expansion-targets/{tid}/contacts/{cid}")
        self.assertEqual(r.status_code, 404)

    def test_add_contact_to_unknown_target_404(self):
        r = self.client.post(
            "/api/expansion-targets/nope/contacts",
            json={"name": "X"})
        self.assertEqual(r.status_code, 404)

    def test_add_contact_without_name_400(self):
        r = self.client.post("/api/expansion-targets", json={
            "anchor_lead_id": "x", "name": "Y"})
        tid = r.get_json()["target"]["id"]
        r = self.client.post(
            f"/api/expansion-targets/{tid}/contacts",
            json={"title": "no name"})
        self.assertEqual(r.status_code, 400)

    # ---- convert-to-lead -------------------------------------------

    def test_convert_to_lead(self):
        r = self.client.post("/api/expansion-targets", json={
            "anchor_lead_id": "shell-na", "name": "Shell UK"})
        tid = r.get_json()["target"]["id"]
        r = self.client.post(
            f"/api/expansion-targets/{tid}/convert-to-lead",
            json={"lead_id": "new-page-id"})
        self.assertEqual(r.status_code, 200)
        t = r.get_json()["target"]
        self.assertEqual(t["status"], "converted_to_lead")
        self.assertEqual(t["converted_lead_id"], "new-page-id")
        self.assertIsNotNone(t["converted_at"])

    def test_convert_requires_lead_id(self):
        r = self.client.post("/api/expansion-targets", json={
            "anchor_lead_id": "x", "name": "Y"})
        tid = r.get_json()["target"]["id"]
        r = self.client.post(
            f"/api/expansion-targets/{tid}/convert-to-lead",
            json={})
        self.assertEqual(r.status_code, 400)

    def test_convert_unknown_target_404(self):
        r = self.client.post(
            "/api/expansion-targets/nope/convert-to-lead",
            json={"lead_id": "x"})
        self.assertEqual(r.status_code, 404)

    def test_convert_idempotent(self):
        r = self.client.post("/api/expansion-targets", json={
            "anchor_lead_id": "x", "name": "Y"})
        tid = r.get_json()["target"]["id"]
        r1 = self.client.post(
            f"/api/expansion-targets/{tid}/convert-to-lead",
            json={"lead_id": "first"})
        r2 = self.client.post(
            f"/api/expansion-targets/{tid}/convert-to-lead",
            json={"lead_id": "second"})
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        # Last write wins.
        self.assertEqual(r2.get_json()["target"]["converted_lead_id"],
                         "second")


# -----------------------------------------------------------------
# Layer 3: overview aggregator
# -----------------------------------------------------------------

class ExpansionOverviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["EXPANSION_TARGETS_STORE_DIR"] = os.path.join(cls.tmp, "ex")
        os.environ["LIVE_PROJECTS_STORE_DIR"] = os.path.join(cls.tmp, "lp")
        os.environ["LIVE_PROJECT_OKRS_STORE_DIR"] = os.path.join(cls.tmp, "okrs")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "expansion_targets_store",
                    "live_projects_store", "live_project_okrs_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("EXPANSION_TARGETS_STORE_DIR",
                  "LIVE_PROJECTS_STORE_DIR",
                  "LIVE_PROJECT_OKRS_STORE_DIR",
                  "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        import expansion_targets_store, live_projects_store
        for f in expansion_targets_store._store_dir().glob("*.json"):
            f.unlink()
        for f in live_projects_store._store_dir().glob("*.json"):
            f.unlink()

    def _overview(self, pipeline_rows=None):
        with patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.list_pipeline.return_value = (
                pipeline_rows or [])
            r = self.client.get("/api/expansion/overview")
        self.assertEqual(r.status_code, 200)
        return r.get_json()

    def test_empty_overview(self):
        body = self._overview()
        self.assertEqual(body["anchors"], [])
        self.assertEqual(body["totals"]["anchors"], 0)
        self.assertEqual(body["totals"]["targets"], 0)
        self.assertEqual(body["totals"]["greenfield"], 0)

    def test_overview_groups_targets_under_anchor(self):
        import live_projects_store, expansion_targets_store
        # Two anchors via live projects.
        live_projects_store.create("shell-na", "Shell Loyalty NA")
        live_projects_store.create("popeyes-us", "Popeyes Loyalty")
        # Two expansion targets on Shell, one on Popeyes.
        expansion_targets_store.create("shell-na", "Shell UK",
                                          region="UK")
        expansion_targets_store.create("shell-na", "Shell APAC",
                                          region="APAC")
        expansion_targets_store.create("popeyes-us", "Popeyes Canada")
        body = self._overview(pipeline_rows=[
            {"id": "shell-na", "company": "Shell"},
            {"id": "popeyes-us", "company": "Popeyes"},
        ])
        self.assertEqual(body["totals"]["anchors"], 2)
        self.assertEqual(body["totals"]["targets"], 3)
        self.assertEqual(body["totals"]["greenfield"], 3)
        by_lead = {a["lead_id"]: a for a in body["anchors"]}
        self.assertIn("shell-na", by_lead)
        self.assertEqual(by_lead["shell-na"]["company"], "Shell")
        self.assertEqual(by_lead["shell-na"]["target_counts"]["total"], 2)
        self.assertEqual(by_lead["popeyes-us"]["target_counts"]["total"], 1)

    def test_overview_includes_anchor_without_live_project(self):
        """A target whose anchor_lead_id has no live project still
        surfaces — we create a synthetic anchor for it so it stays
        visible."""
        import expansion_targets_store
        expansion_targets_store.create("orphan-anchor", "Some Target")
        body = self._overview(pipeline_rows=[
            {"id": "orphan-anchor", "company": "Orphan Co"},
        ])
        self.assertEqual(len(body["anchors"]), 1)
        a = body["anchors"][0]
        self.assertEqual(a["lead_id"], "orphan-anchor")
        self.assertEqual(a["company"], "Orphan Co")
        self.assertIsNone(a["anchor_id"])
        self.assertIsNone(a["project_status"])
        self.assertEqual(a["target_counts"]["total"], 1)

    def test_overview_sorts_greenfield_first_within_anchor(self):
        import live_projects_store, expansion_targets_store
        live_projects_store.create("a", "A")
        # Mix of statuses on the same anchor.
        dropped = expansion_targets_store.create("a", "Dropped Target")
        expansion_targets_store.update(dropped["id"], status="dropped")
        qualifying = expansion_targets_store.create("a", "Qualifying Target")
        expansion_targets_store.update(qualifying["id"], status="qualifying")
        expansion_targets_store.create("a", "Greenfield Target")
        body = self._overview(pipeline_rows=[{"id": "a", "company": "A"}])
        names = [t["name"] for t in body["anchors"][0]["targets"]]
        # Greenfield first, then in-progress, then dropped.
        self.assertEqual(names,
                         ["Greenfield Target", "Qualifying Target",
                          "Dropped Target"])

    def test_overview_totals_by_status(self):
        import live_projects_store, expansion_targets_store
        live_projects_store.create("a", "A")
        # 2 greenfield, 1 qualifying, 1 researching, 1 converted, 1 dropped.
        expansion_targets_store.create("a", "G1")
        expansion_targets_store.create("a", "G2")
        q = expansion_targets_store.create("a", "Q")
        expansion_targets_store.update(q["id"], status="qualifying")
        r = expansion_targets_store.create("a", "R")
        expansion_targets_store.update(r["id"], status="researching")
        c = expansion_targets_store.create("a", "C")
        expansion_targets_store.mark_converted(c["id"], "new-lead")
        d = expansion_targets_store.create("a", "D")
        expansion_targets_store.update(d["id"], status="dropped")
        body = self._overview(pipeline_rows=[{"id": "a", "company": "A"}])
        totals = body["totals"]
        self.assertEqual(totals["greenfield"], 2)
        self.assertEqual(totals["in_progress"], 2)  # qualifying + researching
        self.assertEqual(totals["converted"], 1)
        self.assertEqual(totals["targets"], 6)

    def test_overview_anchor_with_no_targets_sorts_last(self):
        """Anchors with targets surface first (more work to do).
        Empty anchors stay visible but sink to the bottom."""
        import live_projects_store, expansion_targets_store
        live_projects_store.create("empty", "Empty Co")
        live_projects_store.create("busy", "Busy Co")
        expansion_targets_store.create("busy", "Target")
        body = self._overview(pipeline_rows=[
            {"id": "empty", "company": "Empty Co"},
            {"id": "busy", "company": "Busy Co"},
        ])
        leads = [a["lead_id"] for a in body["anchors"]]
        # busy (has targets) should come first.
        self.assertEqual(leads, ["busy", "empty"])


if __name__ == "__main__":
    unittest.main()
