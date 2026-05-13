"""Flask API tests against the test client.

Asserts the auth middleware behaviour and the qualify endpoint contract.
"""
from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _import_server(*, auth_token: str = ""):
    """Re-import server.py with a chosen APP_AUTH_TOKEN env state."""
    os.environ["APOLLO_USE_FIXTURES"] = "1"
    if auth_token:
        os.environ["APP_AUTH_TOKEN"] = auth_token
    else:
        os.environ.pop("APP_AUTH_TOKEN", None)
    if "server" in sys.modules:
        del sys.modules["server"]
    return importlib.import_module("server")


class AuthDisabledTests(unittest.TestCase):
    """When APP_AUTH_TOKEN is unset, the API is open."""

    @classmethod
    def setUpClass(cls):
        cls.server = _import_server()
        cls.client = cls.server.app.test_client()

    def test_health_open(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertFalse(body["auth"]["required"])

    def test_qualify_open(self):
        r = self.client.post("/api/qualify", json={"name": "Deliveroo", "url": "deliveroo.co.uk"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["score"]["status"], "qualify_in")


class AuthEnabledTests(unittest.TestCase):
    """With APP_AUTH_TOKEN set, /api/* requires the bearer."""

    @classmethod
    def setUpClass(cls):
        cls.token = "test-secret-token-abc"
        cls.server = _import_server(auth_token=cls.token)
        cls.client = cls.server.app.test_client()

    def test_health_is_always_open(self):
        # Health stays accessible so the UI can detect the auth requirement.
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["auth"]["required"])

    def test_html_is_open(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Massive Rocket", r.data)

    def test_qualify_rejected_without_token(self):
        r = self.client.post("/api/qualify", json={"name": "Deliveroo", "url": "deliveroo.co.uk"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.get_json()["code"], "auth_required")

    def test_qualify_rejected_with_wrong_token(self):
        r = self.client.post(
            "/api/qualify",
            json={"name": "Deliveroo", "url": "deliveroo.co.uk"},
            headers={"Authorization": "Bearer wrong"},
        )
        self.assertEqual(r.status_code, 401)

    def test_qualify_accepted_with_correct_token(self):
        r = self.client.post(
            "/api/qualify",
            json={"name": "Deliveroo", "url": "deliveroo.co.uk"},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
