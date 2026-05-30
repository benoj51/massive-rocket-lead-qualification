"""v1.0.0dg - use-cases DB read layer.

We mock the psycopg pool + cursor so the tests don't need a live
Postgres. The cursor mock simulates the description + fetchall
contract we rely on in usecases_db._row_to_dict.
"""
from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _FakeColumn:
    """Minimal stand-in for psycopg3's cursor.description entry."""
    def __init__(self, name): self.name = name


class _FakeCursor:
    def __init__(self):
        self._rows = []
        self.description = []
        self._last_sql = None
        self._last_params = None

    def __enter__(self): return self
    def __exit__(self, *a): pass

    def queue(self, columns: list[str], rows: list[tuple]):
        self.description = [_FakeColumn(c) for c in columns]
        self._rows = list(rows)

    def execute(self, sql, params=None):
        self._last_sql = sql
        self._last_params = params

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    def __init__(self, cursor): self._cur = cursor
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def cursor(self): return self._cur


class _FakePool:
    def __init__(self, cursor):
        self._cur = cursor
    def open(self): pass
    def connection(self):
        return _FakeConn(self._cur)


class UseCasesDbTests(unittest.TestCase):
    def setUp(self):
        os.environ["DATABASE_URL_USECASES"] = (
            "postgresql://u:p@localhost:5432/test")
        sys.modules.pop("usecases_db", None)
        import usecases_db
        self.uc = usecases_db
        # Reset pool singleton between tests
        self.uc._pool = None
        self.uc._POOL_INIT_TRIED = False
        # Install a fake cursor + pool
        self.cur = _FakeCursor()
        self.uc._pool = _FakePool(self.cur)

    def tearDown(self):
        os.environ.pop("DATABASE_URL_USECASES", None)

    def test_unconfigured_returns_empty_lists(self):
        # Wipe pool + env
        self.uc._pool = None
        self.uc._POOL_INIT_TRIED = True
        os.environ.pop("DATABASE_URL_USECASES", None)
        self.assertFalse(self.uc.is_configured())
        self.assertEqual(self.uc.list_use_cases(), [])
        self.assertEqual(self.uc.list_industries(), [])
        self.assertEqual(self.uc.list_platforms(), [])
        self.assertIsNone(self.uc.get_use_case(1))
        self.assertEqual(self.uc.match_for_lead(industry="QSR"), [])

    def test_healthcheck_unconfigured(self):
        self.uc._pool = None
        self.uc._POOL_INIT_TRIED = True
        os.environ.pop("DATABASE_URL_USECASES", None)
        h = self.uc.healthcheck()
        self.assertFalse(h["configured"])
        self.assertFalse(h["reachable"])

    def test_list_industries_returns_rows(self):
        self.cur.queue(
            ["id", "name", "slug"],
            [(1, "QSR", "qsr"), (2, "Retail", "retail")],
        )
        out = self.uc.list_industries()
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0], {"id": 1, "name": "QSR", "slug": "qsr"})

    def test_list_use_cases_applies_status_filter(self):
        self.cur.queue(
            ["id", "title", "slug", "client_name", "is_anonymised",
              "problem", "solution", "outcome", "metrics", "delivered_at",
              "status", "industry_name", "industry_slug",
              "platform_slugs", "feature_area_slugs"],
            [(1, "Braze SDK launch", "braze-sdk-launch",
              "KFC US", False, "p", "s", "o",
              [{"label": "Engagement", "value": 12, "unit": "%"}],
              "2026-02-01", "published",
              "QSR", "qsr", ["braze"], ["canvas"])],
        )
        out = self.uc.list_use_cases(status="published")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["title"], "Braze SDK launch")
        # Verify the SQL bound 'published' as a param
        self.assertIn("u.status = %s", self.cur._last_sql)
        self.assertIn("published", self.cur._last_params)

    def test_list_use_cases_with_platform_filter(self):
        self.cur.queue(
            ["id", "title", "slug", "client_name", "is_anonymised",
              "problem", "solution", "outcome", "metrics", "delivered_at",
              "status", "industry_name", "industry_slug",
              "platform_slugs", "feature_area_slugs"],
            [],
        )
        self.uc.list_use_cases(platform_slug="braze")
        # The platform_slug filter should add an EXISTS clause + param
        self.assertIn("EXISTS", self.cur._last_sql)
        self.assertIn("braze", self.cur._last_params)

    def test_get_use_case_by_id(self):
        self.cur.queue(
            ["id", "title", "slug", "client_name", "is_anonymised",
              "problem", "solution", "outcome", "metrics",
              "delivered_at", "status", "source_doc", "source_text",
              "industry_name", "industry_slug",
              "platform_slugs", "feature_area_slugs", "agent_slugs"],
            [(42, "Use case 42", "uc-42", "Acme", True,
              "problem text", "solution text", "outcome text",
              [], None, "published", None, "src",
              "Retail", "retail", ["braze"], ["canvas"], ["winback"])],
        )
        uc = self.uc.get_use_case(42)
        self.assertIsNotNone(uc)
        self.assertEqual(uc["id"], 42)
        self.assertEqual(uc["agent_slugs"], ["winback"])

    def test_match_for_lead_scores_industry_and_platform(self):
        # Three use cases - varying matches against industry=QSR + stack=Braze
        self.cur.queue(
            ["id", "title", "slug", "client_name", "is_anonymised", "outcome",
              "metrics", "delivered_at",
              "industry_name_lc", "industry_slug_lc",
              "platform_slugs_lc", "platform_names_lc"],
            [
                (1, "Best match", "best", "KFC", False, "Up 12%",
                 [], None, "qsr", "qsr",
                 ["braze"], ["braze"]),  # industry + platform => 3 + 2 = 5
                (2, "Industry only", "indo", "Subway", False, "Up 3",
                 [], None, "qsr", "qsr",
                 ["hightouch"], ["hightouch"]),  # industry only => 3
                (3, "Platform only", "ponly", "Acme", True, "Up 4",
                 [], None, "retail", "retail",
                 ["braze"], ["braze"]),  # platform only => 2
                (4, "No match", "nm", "OtherCo", True, "Up 5",
                 [], None, "media", "media",
                 ["mparticle"], ["mparticle"]),  # no match
            ],
        )
        out = self.uc.match_for_lead(industry="qsr", tech_stack=["Braze"])
        self.assertEqual(len(out), 3)
        # Sorted by match_score desc
        self.assertEqual(out[0]["slug"], "best")
        self.assertEqual(out[0]["match_score"], 5)
        self.assertEqual(out[1]["match_score"], 3)
        self.assertEqual(out[2]["match_score"], 2)
        # Internal lowercase fields stripped from output
        self.assertNotIn("industry_name_lc", out[0])
        self.assertNotIn("platform_names_lc", out[0])

    def test_match_for_lead_returns_empty_when_no_overlap(self):
        self.cur.queue(
            ["id", "title", "slug", "client_name", "is_anonymised", "outcome",
              "metrics", "delivered_at",
              "industry_name_lc", "industry_slug_lc",
              "platform_slugs_lc", "platform_names_lc"],
            [(1, "x", "x", "x", False, "", [], None,
              "qsr", "qsr", ["braze"], ["braze"])],
        )
        out = self.uc.match_for_lead(industry="financial-services",
                                       tech_stack=["Iterable"])
        self.assertEqual(out, [])


class RankMatchesSortTests(unittest.TestCase):
    """v1.0.0dv: the Python-side ranking must not crash when two equally
    scored rows carry a mix of date and None delivered_at. The previous
    implementation had a secondary sort keyed on `delivered_at or ""`,
    which raised TypeError comparing a date against an empty string."""

    def setUp(self):
        sys.modules.pop("usecases_db", None)
        import usecases_db
        self.uc = usecases_db

    def test_equal_scores_mixed_delivered_at_does_not_crash(self):
        import datetime
        rows = [
            {"id": 1, "slug": "a", "industry_slug_lc": "qsr",
             "platform_slugs_lc": ["braze"], "platform_names_lc": ["braze"],
             "delivered_at": datetime.date(2025, 1, 1)},
            {"id": 2, "slug": "b", "industry_slug_lc": "qsr",
             "platform_slugs_lc": ["braze"], "platform_names_lc": ["braze"],
             "delivered_at": None},
        ]
        out = self.uc._rank_matches(rows, industry="qsr",
                                     tech_stack=["Braze"], limit=6)
        self.assertEqual(len(out), 2)
        self.assertTrue(all(r["match_score"] == 5 for r in out))
        # Stable order: the SQL delivered_at-desc order is preserved on a
        # score tie because Python's sort is stable.
        self.assertEqual([r["id"] for r in out], [1, 2])
        self.assertNotIn("industry_slug_lc", out[0])

    def test_limit_is_applied(self):
        rows = [{"id": i, "slug": str(i), "industry_slug_lc": "qsr",
                  "platform_slugs_lc": [], "platform_names_lc": [],
                  "delivered_at": None} for i in range(10)]
        out = self.uc._rank_matches(rows, industry="qsr",
                                     tech_stack=None, limit=3)
        self.assertEqual(len(out), 3)


class UseCasesEndpointTests(unittest.TestCase):
    """End-to-end via Flask test client - the endpoint itself."""

    @classmethod
    def setUpClass(cls):
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        os.environ["DATABASE_URL_USECASES"] = (
            "postgresql://u:p@localhost:5432/test")
        for m in ("server", "usecases_db"):
            sys.modules.pop(m, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("DATABASE_URL_USECASES", None)

    def _install_fake_cursor(self, columns, rows):
        # Patch the module-global pool with a fake.
        import usecases_db
        usecases_db._pool = _FakePool(_FakeCursor())
        usecases_db._POOL_INIT_TRIED = True
        usecases_db._pool._cur.queue(columns, rows)
        return usecases_db

    def test_list_endpoint_returns_use_cases(self):
        self._install_fake_cursor(
            ["id", "title", "slug", "client_name", "is_anonymised",
              "problem", "solution", "outcome", "metrics", "delivered_at",
              "status", "industry_name", "industry_slug",
              "platform_slugs", "feature_area_slugs"],
            [(1, "Test UC", "test-uc", "KFC", False,
              "p", "s", "o", [], "2026-02-01",
              "published", "QSR", "qsr", ["braze"], [])],
        )
        r = self.client.get("/api/use-cases?industry=qsr")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(len(body["use_cases"]), 1)

    def test_match_endpoint(self):
        self._install_fake_cursor(
            ["id", "title", "slug", "client_name", "is_anonymised", "outcome",
              "metrics", "delivered_at",
              "industry_name_lc", "industry_slug_lc",
              "platform_slugs_lc", "platform_names_lc"],
            [(1, "Match", "match", "KFC", False, "", [], None,
              "qsr", "qsr", ["braze"], ["braze"])],
        )
        r = self.client.get(
            "/api/use-cases/match?industry=qsr&tech_stack=Braze")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(len(body["matches"]), 1)
        self.assertEqual(body["matches"][0]["match_score"], 5)

    def test_endpoint_returns_unconfigured_when_no_db(self):
        import usecases_db
        usecases_db._pool = None
        usecases_db._POOL_INIT_TRIED = True
        original = os.environ.pop("DATABASE_URL_USECASES", None)
        try:
            r = self.client.get("/api/use-cases")
            self.assertEqual(r.status_code, 200)
            body = r.get_json()
            self.assertFalse(body["configured"])
            self.assertEqual(body["use_cases"], [])
        finally:
            if original:
                os.environ["DATABASE_URL_USECASES"] = original


if __name__ == "__main__":
    unittest.main()
