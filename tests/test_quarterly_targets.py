"""v1.0.0db - quarterly targets store + endpoints."""
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


class QuarterlyTargetsStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["QUARTERLY_TARGETS_STORE_PATH"] = os.path.join(
            self.tmp, "qt.json")
        sys.modules.pop("quarterly_targets_store", None)
        import quarterly_targets_store
        self.qt = quarterly_targets_store

    def tearDown(self):
        os.environ.pop("QUARTERLY_TARGETS_STORE_PATH", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_list_returns_empty(self):
        self.assertEqual(self.qt.list_quarters(), [])

    def test_default_metrics_includes_opps_and_reengage(self):
        keys = {m["key"] for m in self.qt.default_metrics()}
        self.assertIn("opportunities", keys)
        self.assertIn("re_engagements", keys)

    def test_upsert_quarter_minimal(self):
        q = self.qt.upsert_quarter({
            "year": 2026, "quarter": 2,
            "metrics": {
                "opportunities": {
                    "team": {"plan": 25, "actual": 18},
                },
            },
        })
        self.assertEqual(q["id"], "2026-Q2")
        self.assertEqual(q["metrics"]["opportunities"]["team"]["plan"], 25)
        self.assertEqual(q["metrics"]["opportunities"]["team"]["actual"], 18)

    def test_upsert_explicit_id_overrides_year_quarter(self):
        q = self.qt.upsert_quarter({"id": "2026-Q3"})
        self.assertEqual(q["year"], 2026)
        self.assertEqual(q["quarter"], 3)

    def test_bad_id_format_raises(self):
        with self.assertRaises(self.qt.QuarterlyTargetsStoreError):
            self.qt.upsert_quarter({"id": "Q2-2026"})

    def test_missing_id_and_year_raises(self):
        with self.assertRaises(self.qt.QuarterlyTargetsStoreError):
            self.qt.upsert_quarter({})

    def test_list_sorts_newest_first(self):
        self.qt.upsert_quarter({"year": 2025, "quarter": 4})
        self.qt.upsert_quarter({"year": 2026, "quarter": 2})
        self.qt.upsert_quarter({"year": 2026, "quarter": 1})
        ids = [q["id"] for q in self.qt.list_quarters()]
        self.assertEqual(ids, ["2026-Q2", "2026-Q1", "2025-Q4"])

    def test_set_cell_creates_quarter_if_missing(self):
        self.qt.set_cell("2026-Q2", "opportunities", "plan",
                          owner=None, value=30)
        q = self.qt.get_quarter("2026-Q2")
        self.assertIsNotNone(q)
        self.assertEqual(q["metrics"]["opportunities"]["team"]["plan"], 30)

    def test_set_cell_per_owner(self):
        self.qt.set_cell("2026-Q2", "opportunities", "plan",
                          owner="Ben Ojuolape", value=10)
        self.qt.set_cell("2026-Q2", "opportunities", "actual",
                          owner="Ben Ojuolape", value=7)
        q = self.qt.get_quarter("2026-Q2")
        cell = q["metrics"]["opportunities"]["by_owner"]["Ben Ojuolape"]
        self.assertEqual(cell, {"plan": 10, "actual": 7})

    def test_set_cell_coerces_strings_to_int(self):
        self.qt.set_cell("2026-Q2", "opportunities", "plan",
                          owner=None, value="25")
        q = self.qt.get_quarter("2026-Q2")
        self.assertEqual(q["metrics"]["opportunities"]["team"]["plan"], 25)

    def test_set_cell_clamps_negative_to_zero(self):
        self.qt.set_cell("2026-Q2", "opportunities", "plan",
                          owner=None, value=-5)
        q = self.qt.get_quarter("2026-Q2")
        self.assertEqual(q["metrics"]["opportunities"]["team"]["plan"], 0)

    def test_set_cell_invalid_kind_raises(self):
        with self.assertRaises(self.qt.QuarterlyTargetsStoreError):
            self.qt.set_cell("2026-Q2", "opportunities", "estimate",
                              owner=None, value=10)

    def test_delete_quarter(self):
        self.qt.upsert_quarter({"id": "2026-Q2"})
        self.assertTrue(self.qt.delete_quarter("2026-Q2"))
        self.assertIsNone(self.qt.get_quarter("2026-Q2"))
        self.assertFalse(self.qt.delete_quarter("2026-Q2"))

    def test_arbitrary_metric_key_supported(self):
        """Editor lets admins add new metrics like 'revenue'."""
        self.qt.set_cell("2026-Q2", "revenue", "plan", owner=None, value=500000)
        q = self.qt.get_quarter("2026-Q2")
        self.assertEqual(q["metrics"]["revenue"]["team"]["plan"], 500000)


class QuarterlyTargetsEndpointsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["QUARTERLY_TARGETS_STORE_PATH"] = os.path.join(
            cls.tmp, "qt.json")
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        sys.modules.pop("server", None)
        sys.modules.pop("quarterly_targets_store", None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("QUARTERLY_TARGETS_STORE_PATH", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_list_empty_returns_empty_array(self):
        r = self.client.get("/api/quarterly-targets")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["quarters"], [])
        # Default metrics surfaced for the UI seed.
        self.assertEqual(
            [m["key"] for m in body["default_metrics"]],
            ["opportunities", "re_engagements"])

    def test_upsert_via_post(self):
        r = self.client.post("/api/quarterly-targets", json={
            "year": 2026, "quarter": 2,
            "metrics": {
                "opportunities": {
                    "team": {"plan": 25, "actual": 18},
                    "by_owner": {"Ben Ojuolape": {"plan": 10, "actual": 7}},
                },
            },
        })
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["quarter"]["id"], "2026-Q2")

    def test_set_cell_via_patch(self):
        r = self.client.patch("/api/quarterly-targets/2026-Q3", json={
            "metric": "opportunities",
            "kind":   "plan",
            "owner":  "Ben Ojuolape",
            "value":  15,
        })
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(
            body["quarter"]["metrics"]["opportunities"]["by_owner"]
                ["Ben Ojuolape"]["plan"],
            15)

    def test_delete_quarter(self):
        self.client.post("/api/quarterly-targets", json={"id": "2026-Q4"})
        r = self.client.delete("/api/quarterly-targets/2026-Q4")
        self.assertEqual(r.status_code, 200)
        # Second delete: 404
        r2 = self.client.delete("/api/quarterly-targets/2026-Q4")
        self.assertEqual(r2.status_code, 404)

    def test_bad_id_rejected(self):
        r = self.client.post("/api/quarterly-targets", json={"id": "not-a-q"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
