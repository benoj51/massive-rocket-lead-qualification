"""v1.0.0ay — saved filter presets store + endpoint tests."""
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


class FilterPresetsStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["FILTER_PRESETS_STORE_DIR"] = self.tmp
        sys.modules.pop("filter_presets_store", None)
        import filter_presets_store
        self.store = filter_presets_store

    def tearDown(self):
        os.environ.pop("FILTER_PRESETS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_create_and_list(self):
        p = self.store.create("Ben", "EU champions",
                                {"region": "EMEA",
                                 "partner_sentiment": "Champion"})
        self.assertEqual(p["name"], "EU champions")
        self.assertEqual(p["filters"]["region"], "EMEA")
        items = self.store.list_for("Ben")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], p["id"])

    def test_list_sorted_alphabetically(self):
        self.store.create("Ben", "Zenith preset", {})
        self.store.create("Ben", "Alpha preset", {})
        self.store.create("Ben", "Mid preset", {})
        names = [p["name"] for p in self.store.list_for("Ben")]
        self.assertEqual(names, ["Alpha preset", "Mid preset", "Zenith preset"])

    def test_duplicate_name_in_same_scope_raises(self):
        self.store.create("Ben", "EU champions", {"region": "EMEA"})
        with self.assertRaises(self.store.PresetExists):
            self.store.create("Ben", "EU champions", {"region": "EMEA"})

    def test_duplicate_name_case_insensitive(self):
        self.store.create("Ben", "EU champions", {})
        with self.assertRaises(self.store.PresetExists):
            self.store.create("Ben", "eu CHAMPIONS", {})

    def test_same_name_different_scopes_ok(self):
        """Uniqueness is per (user, scope) — same name in two scopes OK."""
        self.store.create("Ben", "Default", {}, scope="partner_contacts")
        # Should NOT raise — different scope.
        p = self.store.create("Ben", "Default", {}, scope="pipeline")
        self.assertEqual(p["scope"], "pipeline")

    def test_per_user_isolation(self):
        self.store.create("Ben", "Mine", {})
        self.store.create("Glenn", "His", {})
        self.assertEqual([p["name"] for p in self.store.list_for("Ben")],
                         ["Mine"])
        self.assertEqual([p["name"] for p in self.store.list_for("Glenn")],
                         ["His"])

    def test_get_returns_normalised_row(self):
        p = self.store.create("Ben", "x", {"a": 1})
        fetched = self.store.get("Ben", p["id"])
        self.assertEqual(fetched["filters"], {"a": 1})
        self.assertTrue(fetched["created_at"])

    def test_get_returns_none_for_missing(self):
        self.assertIsNone(self.store.get("Ben", "no-such-id"))

    def test_update_name(self):
        p = self.store.create("Ben", "Old name", {})
        u = self.store.update("Ben", p["id"], name="New name")
        self.assertEqual(u["name"], "New name")
        # updated_at advanced; created_at preserved.
        self.assertEqual(u["created_at"], p["created_at"])

    def test_update_filters_replaces(self):
        p = self.store.create("Ben", "x", {"region": "EMEA"})
        u = self.store.update("Ben", p["id"], filters={"region": "APAC"})
        self.assertEqual(u["filters"], {"region": "APAC"})

    def test_update_rejects_duplicate_name(self):
        a = self.store.create("Ben", "A", {})
        self.store.create("Ben", "B", {})
        with self.assertRaises(self.store.PresetExists):
            self.store.update("Ben", a["id"], name="B")

    def test_update_to_same_name_ok(self):
        """Renaming to the SAME name (no-op) shouldn't trip the unique-
        ness check — that would block harmless edits."""
        p = self.store.create("Ben", "Same", {})
        u = self.store.update("Ben", p["id"], name="Same")
        self.assertEqual(u["name"], "Same")

    def test_update_rejects_unknown_field(self):
        p = self.store.create("Ben", "x", {})
        with self.assertRaises(self.store.FilterPresetsStoreError):
            self.store.update("Ben", p["id"], scope="pipeline")

    def test_update_missing_returns_none(self):
        self.assertIsNone(self.store.update("Ben", "no-such-id", name="x"))

    def test_delete(self):
        p = self.store.create("Ben", "x", {})
        self.assertTrue(self.store.delete("Ben", p["id"]))
        self.assertEqual(self.store.list_for("Ben"), [])
        self.assertFalse(self.store.delete("Ben", p["id"]))

    def test_validation_empty_name(self):
        with self.assertRaises(self.store.FilterPresetsStoreError):
            self.store.create("Ben", "   ", {})

    def test_validation_overlong_name(self):
        with self.assertRaises(self.store.FilterPresetsStoreError):
            self.store.create("Ben", "x" * 81, {})

    def test_validation_filters_must_be_dict(self):
        with self.assertRaises(self.store.FilterPresetsStoreError):
            self.store.create("Ben", "x", "not a dict")

    def test_validation_user_required(self):
        with self.assertRaises(self.store.FilterPresetsStoreError):
            self.store.create("", "x", {})

    def test_scope_filter_in_list(self):
        self.store.create("Ben", "Partners", {}, scope="partner_contacts")
        self.store.create("Ben", "Leads",    {}, scope="pipeline")
        scoped = self.store.list_for("Ben", scope="pipeline")
        self.assertEqual([p["name"] for p in scoped], ["Leads"])


class FilterPresetsEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["FILTER_PRESETS_STORE_DIR"] = os.path.join(cls.tmp, "fp")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "filter_presets_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("FILTER_PRESETS_STORE_DIR", "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        # Each test wipes Ben's file so they're independent.
        import filter_presets_store
        for p in filter_presets_store.list_for("Ben Ojuolape"):
            filter_presets_store.delete("Ben Ojuolape", p["id"])

    def test_list_requires_user(self):
        r = self.client.get("/api/filter-presets")
        self.assertEqual(r.status_code, 400)

    def test_create_then_list(self):
        r = self.client.post("/api/filter-presets",
                              json={"user": "Ben Ojuolape",
                                    "name": "EU Champions",
                                    "filters": {"region": "EMEA"}})
        self.assertEqual(r.status_code, 201)
        items = self.client.get(
            "/api/filter-presets?user=Ben%20Ojuolape").get_json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "EU Champions")

    def test_duplicate_create_returns_409(self):
        self.client.post("/api/filter-presets",
                          json={"user": "Ben Ojuolape", "name": "X",
                                "filters": {}})
        r = self.client.post("/api/filter-presets",
                              json={"user": "Ben Ojuolape", "name": "X",
                                    "filters": {}})
        self.assertEqual(r.status_code, 409)

    def test_update_endpoint(self):
        r = self.client.post("/api/filter-presets",
                              json={"user": "Ben Ojuolape", "name": "Old",
                                    "filters": {}})
        pid = r.get_json()["preset"]["id"]
        r = self.client.patch(f"/api/filter-presets/{pid}",
                                json={"user": "Ben Ojuolape",
                                      "name": "New"})
        self.assertEqual(r.get_json()["preset"]["name"], "New")

    def test_delete_endpoint(self):
        r = self.client.post("/api/filter-presets",
                              json={"user": "Ben Ojuolape", "name": "X",
                                    "filters": {}})
        pid = r.get_json()["preset"]["id"]
        r = self.client.delete(
            f"/api/filter-presets/{pid}?user=Ben%20Ojuolape")
        self.assertTrue(r.get_json()["deleted"])
        items = self.client.get(
            "/api/filter-presets?user=Ben%20Ojuolape").get_json()["items"]
        self.assertEqual(items, [])

    def test_create_missing_name_400(self):
        r = self.client.post("/api/filter-presets",
                              json={"user": "Ben Ojuolape", "filters": {}})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
