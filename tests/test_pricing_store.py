"""v0.9.1 — pricing config persistence per lead."""
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


class PricingStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["PRICING_STORE_DIR"] = self.tmp
        for mod in ("pricing_store", "project_store"):
            sys.modules.pop(mod, None)

    def tearDown(self):
        os.environ.pop("PRICING_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load_missing_returns_none(self):
        import pricing_store
        self.assertIsNone(pricing_store.load("nobody"))

    def test_save_then_load_roundtrip(self):
        import pricing_store
        saved = pricing_store.save("lead-a", {
            "currency": "GBP",
            "rate_card": "Yum Thailand!",
            "months": 18,
            "project_ops_pct": 0.10,
            "contingency_pct": 0.05,
            "discount_first_half_pct": 0.15,
            "role_overrides": {"CRM Strategist": {"Execute": 0.75}},
            "role_staffing": {"CRM Consultant": {"region": "India", "seniority": "Senior"}},
            "selected_package": "Customer 360",
        })
        self.assertIn("updated_at", saved)
        loaded = pricing_store.load("lead-a")
        self.assertEqual(loaded["currency"], "GBP")
        self.assertEqual(loaded["rate_card"], "Yum Thailand!")
        self.assertEqual(loaded["months"], 18)
        self.assertEqual(loaded["role_overrides"]["CRM Strategist"]["Execute"], 0.75)
        self.assertEqual(loaded["role_staffing"]["CRM Consultant"]["region"], "India")
        self.assertEqual(loaded["selected_package"], "Customer 360")

    def test_save_filters_unknown_keys(self):
        """Stale fields from older clients shouldn't accumulate."""
        import pricing_store
        saved = pricing_store.save("lead-b", {
            "currency": "USD",
            "bogus_field": "nope",
            "another_old_thing": 42,
        })
        self.assertNotIn("bogus_field", saved)
        self.assertNotIn("another_old_thing", saved)
        self.assertEqual(saved["currency"], "USD")

    def test_save_stamps_updated_at(self):
        import pricing_store, time
        saved1 = pricing_store.save("lead-c", {"currency": "USD"})
        time.sleep(1.01)
        saved2 = pricing_store.save("lead-c", {"currency": "GBP"})
        self.assertNotEqual(saved1["updated_at"], saved2["updated_at"])

    def test_delete(self):
        import pricing_store
        pricing_store.save("lead-d", {"currency": "EUR"})
        self.assertTrue(pricing_store.delete("lead-d"))
        self.assertIsNone(pricing_store.load("lead-d"))
        # Second delete returns False (already gone)
        self.assertFalse(pricing_store.delete("lead-d"))


class PricingConfigEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["PRICING_STORE_DIR"] = cls.tmp
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "pricing_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("PRICING_STORE_DIR", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_get_when_no_config_returns_null(self):
        r = self.client.get("/api/pricing/config/no-such-lead")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.get_json()["config"])

    def test_post_then_get_round_trip(self):
        body = {
            "currency": "GBP",
            "rate_card": "Staff Augmentation",
            "project_ops_pct": 0.10,
            "contingency_pct": 0.05,
            "role_overrides": {"CRM Architect": {"Execute": 1.0}},
            "role_staffing": {"CRM Architect": {"region": "UK", "seniority": "Senior"}},
        }
        r = self.client.post("/api/pricing/config/lead-z", json=body)
        self.assertEqual(r.status_code, 200)
        got = self.client.get("/api/pricing/config/lead-z").get_json()
        self.assertEqual(got["config"]["currency"], "GBP")
        self.assertEqual(got["config"]["rate_card"], "Staff Augmentation")
        self.assertEqual(got["config"]["role_overrides"]["CRM Architect"]["Execute"], 1.0)


if __name__ == "__main__":
    unittest.main()
