"""Editable criteria store tests."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class CriteriaStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "criteria.json")
        os.environ["CRITERIA_STORE_PATH"] = self.path

    def tearDown(self):
        os.environ.pop("CRITERIA_STORE_PATH", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_first_load_seeds_defaults(self):
        import criteria_store, scope
        lib = criteria_store.load()
        self.assertIn("crm_build", lib)
        # Same keys as the immutable defaults baseline.
        default_keys = {c["key"] for c in scope.DEFAULT_CRITERIA_LIBRARY["crm_build"]}
        loaded_keys = {c["key"] for c in lib["crm_build"]}
        self.assertEqual(default_keys, loaded_keys)
        # File was created
        self.assertTrue(os.path.exists(self.path))

    def test_upsert_new_criterion(self):
        import criteria_store
        criteria_store.load()  # seed
        criteria_store.upsert_criterion("crm_build", {
            "key": "custom_thing",
            "label": "Custom thing",
            "hint": "Just for this test",
            "role_driver": "CRM Developer",
            "scale_factor": 0.3,
        })
        lib = criteria_store.load()
        keys = [c["key"] for c in lib["crm_build"]]
        self.assertIn("custom_thing", keys)

    def test_upsert_replaces_existing(self):
        import criteria_store
        criteria_store.load()
        criteria_store.upsert_criterion("crm_build", {
            "key": "migrating_campaigns",
            "label": "Renamed label",
        })
        lib = criteria_store.load()
        renamed = next(c for c in lib["crm_build"] if c["key"] == "migrating_campaigns")
        self.assertEqual(renamed["label"], "Renamed label")

    def test_validate_requires_key_and_label(self):
        import criteria_store
        with self.assertRaises(criteria_store.CriteriaStoreError):
            criteria_store.upsert_criterion("crm_build", {"key": "x"})
        with self.assertRaises(criteria_store.CriteriaStoreError):
            criteria_store.upsert_criterion("crm_build", {"label": "x"})

    def test_delete_criterion(self):
        import criteria_store
        criteria_store.load()
        ok = criteria_store.delete_criterion("crm_build", "migrating_campaigns")
        self.assertTrue(ok)
        lib = criteria_store.load()
        keys = {c["key"] for c in lib["crm_build"]}
        self.assertNotIn("migrating_campaigns", keys)

    def test_delete_missing_returns_false(self):
        import criteria_store
        criteria_store.load()
        ok = criteria_store.delete_criterion("crm_build", "no_such_key")
        self.assertFalse(ok)

    def test_reset_project_type(self):
        import criteria_store, scope
        criteria_store.load()
        criteria_store.delete_criterion("crm_build", "migrating_campaigns")
        criteria_store.reset_project_type("crm_build")
        lib = criteria_store.load()
        # Defaults restored
        default_keys = {c["key"] for c in scope.DEFAULT_CRITERIA_LIBRARY["crm_build"]}
        loaded_keys = {c["key"] for c in lib["crm_build"]}
        self.assertEqual(default_keys, loaded_keys)

    def test_reset_all(self):
        import criteria_store, scope
        criteria_store.load()
        criteria_store.upsert_criterion("crm_build", {"key": "xx", "label": "xx"})
        criteria_store.reset_all()
        lib = criteria_store.load()
        keys = {c["key"] for c in lib["crm_build"]}
        self.assertNotIn("xx", keys)

    def test_reorder(self):
        import criteria_store
        lib = criteria_store.load()
        first_two = [c["key"] for c in lib["crm_build"][:2]]
        criteria_store.reorder("crm_build", list(reversed(first_two)))
        lib2 = criteria_store.load()
        new_first_two = [c["key"] for c in lib2["crm_build"][:2]]
        self.assertEqual(new_first_two, list(reversed(first_two)))

    def test_reorder_unknown_key_raises(self):
        import criteria_store
        criteria_store.load()
        with self.assertRaises(criteria_store.CriteriaStoreError):
            criteria_store.reorder("crm_build", ["no_such_key"])

    def test_scope_criteria_library_reads_from_store(self):
        import criteria_store, scope
        criteria_store.load()
        criteria_store.upsert_criterion("crm_build", {
            "key": "live_test_criterion",
            "label": "Live test",
        })
        lib = scope.criteria_library()
        keys = {c["key"] for c in lib["crm_build"]}
        self.assertIn("live_test_criterion", keys)


if __name__ == "__main__":
    unittest.main()
