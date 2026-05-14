"""HubSpot scaffolding tests. No live calls — the feature flag blocks them."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FeatureFlagTests(unittest.TestCase):
    def setUp(self):
        # Clean slate per test.
        for k in ("HUBSPOT_API_KEY", "HUBSPOT_SYNC_ENABLED"):
            os.environ.pop(k, None)

    def test_is_enabled_requires_both_flags(self):
        import hubspot_sync
        self.assertFalse(hubspot_sync.is_enabled())
        os.environ["HUBSPOT_API_KEY"] = "fake-key"
        self.assertFalse(hubspot_sync.is_enabled(), "API key alone should not enable")
        os.environ["HUBSPOT_SYNC_ENABLED"] = "1"
        self.assertTrue(hubspot_sync.is_enabled())
        os.environ["HUBSPOT_SYNC_ENABLED"] = "0"
        self.assertFalse(hubspot_sync.is_enabled(), "Flag must be exactly '1'")

    def test_construct_raises_when_disabled(self):
        import hubspot_sync
        with self.assertRaises(hubspot_sync.HubSpotSyncDisabled):
            hubspot_sync.HubSpotSync()

    def test_construct_requires_api_key_even_when_enforce_false(self):
        import hubspot_sync
        with self.assertRaises(hubspot_sync.HubSpotSyncDisabled):
            hubspot_sync.HubSpotSync(enforce_enabled=False)

    def test_status_payload(self):
        import hubspot_sync
        s = hubspot_sync.status()
        self.assertFalse(s["enabled"])
        self.assertFalse(s["api_key_present"])
        self.assertFalse(s["sync_flag"])


class PayloadMappingTests(unittest.TestCase):
    def test_qualify_payload_to_props(self):
        import hubspot_sync
        payload = {
            "company": {"name": "Deliveroo", "url": "https://deliveroo.co.uk"},
            "score": {
                "status": "qualify_in", "status_display": "QUALIFY IN",
                "normalized_score": 9.4,
            },
            "opportunity": {"label": "Retention"},
            "discovered": {
                "vertical": "Food Delivery",
                "employees": 4200,
                "revenue_numeric": 2_400_000_000,
            },
            "fit_summary": "Strong retention play. Braze + Snowflake confirmed.",
        }
        props = hubspot_sync._qualify_payload_to_props(payload)
        self.assertEqual(props["name"], "Deliveroo")
        self.assertEqual(props["domain"], "deliveroo.co.uk")
        self.assertEqual(props["lifecyclestage"], "marketingqualifiedlead")
        self.assertEqual(props["mr_icp_status"], "QUALIFY IN")
        self.assertEqual(props["mr_icp_score"], "9.4")
        self.assertEqual(props["industry"], "Food Delivery")
        self.assertIn("mr_fit_summary", props)


class ServerEndpointTests(unittest.TestCase):
    """The /api/hubspot/sync endpoint must 503 when disabled."""

    @classmethod
    def setUpClass(cls):
        for k in ("HUBSPOT_API_KEY", "HUBSPOT_SYNC_ENABLED", "APP_AUTH_TOKEN"):
            os.environ.pop(k, None)
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        if "server" in sys.modules:
            del sys.modules["server"]
        import server
        cls.client = server.app.test_client()

    def test_disabled_returns_503(self):
        body = {"company": {"name": "Deliveroo", "url": "deliveroo.co.uk"}}
        r = self.client.post("/api/hubspot/sync", json=body)
        self.assertEqual(r.status_code, 503)
        data = r.get_json()
        self.assertEqual(data["code"], "hubspot_disabled")
        self.assertIn("how_to_enable", data)


if __name__ == "__main__":
    unittest.main()
