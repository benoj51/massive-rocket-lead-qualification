"""v1.0.0do - in-process rate limiter (rate_limit.py) + endpoint wiring."""
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

import rate_limit


class CheckLogicTests(unittest.TestCase):
    def setUp(self):
        rate_limit.reset()

    def tearDown(self):
        rate_limit.reset()

    def test_allows_up_to_limit_then_blocks(self):
        ok1, _ = rate_limit._check("k", 2, 60.0)
        ok2, _ = rate_limit._check("k", 2, 60.0)
        ok3, retry = rate_limit._check("k", 2, 60.0)
        self.assertTrue(ok1)
        self.assertTrue(ok2)
        self.assertFalse(ok3)
        self.assertGreater(retry, 0)
        self.assertLessEqual(retry, 60.0)

    def test_separate_keys_are_independent(self):
        self.assertTrue(rate_limit._check("a", 1, 60.0)[0])
        # 'a' is now full, but 'b' is untouched.
        self.assertFalse(rate_limit._check("a", 1, 60.0)[0])
        self.assertTrue(rate_limit._check("b", 1, 60.0)[0])

    def test_expired_hits_age_out(self):
        # A zero-length window means every prior hit is already expired,
        # so the bucket never fills.
        for _ in range(5):
            ok, _ = rate_limit._check("k", 1, 0.0)
            self.assertTrue(ok)

    def test_reset_clears_counters(self):
        rate_limit._check("k", 1, 60.0)
        self.assertFalse(rate_limit._check("k", 1, 60.0)[0])
        rate_limit.reset()
        self.assertTrue(rate_limit._check("k", 1, 60.0)[0])

    def test_limit_from_env(self):
        with patch.dict(os.environ, {"RL_TEST": "5"}):
            self.assertEqual(rate_limit._limit_from_env("RL_TEST", 99), 5)
        with patch.dict(os.environ, {"RL_TEST": "  "}):
            self.assertEqual(rate_limit._limit_from_env("RL_TEST", 99), 99)
        with patch.dict(os.environ, {"RL_TEST": "garbage"}):
            self.assertEqual(rate_limit._limit_from_env("RL_TEST", 99), 99)


class EndpointTests(unittest.TestCase):
    """The decorator returns 429 once the per-client window is full, and
    is a no-op when the limit is 0 (disabled)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["AUDIT_LOG_PATH"] = os.path.join(cls.tmp, "audit.jsonl")
        os.environ.pop("APP_AUTH_TOKEN", None)
        for m in ("server",):
            sys.modules.pop(m, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("AUDIT_LOG_PATH", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        rate_limit.reset()

    def _hit_sweep(self):
        import watchlist_sweep
        with patch.object(watchlist_sweep, "run_sweep",
                          return_value={"leads_scanned": 0, "items_added": 0,
                                        "notifications_fired": 0,
                                        "errors": []}):
            return self.client.post("/api/admin/watchlist/sweep")

    def test_sweep_429_after_limit(self):
        with patch.dict(os.environ, {"RATE_LIMIT_SWEEP_PER_MIN": "2"}):
            self.assertEqual(self._hit_sweep().status_code, 200)
            self.assertEqual(self._hit_sweep().status_code, 200)
            blocked = self._hit_sweep()
            self.assertEqual(blocked.status_code, 429)
            self.assertEqual(blocked.get_json()["code"], "rate_limited")
            self.assertIn("Retry-After", blocked.headers)

    def test_disabled_when_limit_zero(self):
        with patch.dict(os.environ, {"RATE_LIMIT_SWEEP_PER_MIN": "0"}):
            for _ in range(6):
                self.assertEqual(self._hit_sweep().status_code, 200)


if __name__ == "__main__":
    unittest.main()
