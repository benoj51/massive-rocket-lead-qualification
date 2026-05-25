"""v1.0.0bz — security-pack regression tests.

Pins five fixes from the security audit:

1. /api/qualify crash responses must NOT include a Python traceback.
2. /api/pipeline/export.csv must neutralise cells that look like
   spreadsheet formulas (=, +, -, @, tab, CR).
3. Flask MAX_CONTENT_LENGTH must reject oversized request bodies.
4. expansion_targets / live_projects / live_project_okrs stores
   must refuse path-traversal IDs (`../etc/passwd`, slashes, etc.).
5. APP_AUTH_TOKEN must NOT be accepted via the ?token= query
   parameter by default (header only).
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
# 1. Stack traces removed from /api/qualify errors
# -----------------------------------------------------------------

class StackTraceLeakTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        sys.modules.pop("server", None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("SKIP_COMMAND_CENTRE_SEED", None)

    def test_qualify_500_omits_traceback(self):
        """A crashing qualify call used to return traceback.format_exc()
        in the response body. Information disclosure — file paths +
        line numbers + frame locals are exactly what an attacker uses
        to plan follow-on exploits."""
        with patch.object(self.server.qualify_service, "qualify",
                            side_effect=RuntimeError("boom internal detail")):
            r = self.client.post("/api/qualify",
                                  json={"name": "X", "url": "https://x.com"})
        self.assertEqual(r.status_code, 500)
        body = r.get_json()
        self.assertIn("error", body)
        # Error message itself is fine; the trace key is what we
        # don't want.
        self.assertNotIn("trace", body)
        # The error string itself shouldn't contain a stack frame.
        self.assertNotIn("Traceback", str(body))
        self.assertNotIn("File \"", str(body))


# -----------------------------------------------------------------
# 2. CSV-injection guard on pipeline export
# -----------------------------------------------------------------

class CsvInjectionTests(unittest.TestCase):
    def test_csv_safe_helper_prefixes_dangerous_cells(self):
        sys.modules.pop("server", None)
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        import server
        f = server._csv_safe
        # Each formula prefix gets a leading single quote.
        self.assertEqual(f("=cmd|'/c calc'!A1"), "'=cmd|'/c calc'!A1")
        self.assertEqual(f("+SUM(A1)"), "'+SUM(A1)")
        self.assertEqual(f("-1+1"), "'-1+1")
        self.assertEqual(f("@SUM(A1:A2)"), "'@SUM(A1:A2)")
        self.assertEqual(f("\tinject"), "'\tinject")
        self.assertEqual(f("\rinject"), "'\rinject")
        # Safe values pass through untouched.
        self.assertEqual(f("Shell"), "Shell")
        self.assertEqual(f("Ben Ojuolape"), "Ben Ojuolape")
        self.assertEqual(f("https://shell.com"), "https://shell.com")
        # None / non-strings.
        self.assertEqual(f(None), "")
        self.assertEqual(f(42), "42")
        self.assertEqual(f(""), "")

    def test_pipeline_csv_neutralises_lead_names(self):
        sys.modules.pop("server", None)
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        import server
        client = server.app.test_client()
        # A malicious lead name lands in the CSV body — must be
        # prefixed with a single quote before Excel sees it.
        with patch.object(server, "NotionSync") as MockSync:
            MockSync.return_value.list_pipeline.return_value = [
                {"company": "=cmd|'/c calc'!A1", "owner": "Ben"},
                {"company": "Shell", "owner": "@evil_formula"},
            ]
            r = client.get("/api/pipeline/export.csv")
        self.assertEqual(r.status_code, 200)
        body = r.get_data(as_text=True)
        self.assertIn("'=cmd|", body)
        self.assertIn("'@evil_formula", body)
        # Safe cells unchanged.
        self.assertIn("Shell", body)
        self.assertNotIn("'Shell", body)


# -----------------------------------------------------------------
# 3. MAX_CONTENT_LENGTH rejects oversize bodies
# -----------------------------------------------------------------

class MaxContentLengthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Set a small cap BEFORE server import so the config takes.
        os.environ["MAX_CONTENT_LENGTH"] = "1024"
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        sys.modules.pop("server", None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("MAX_CONTENT_LENGTH", None)
        os.environ.pop("SKIP_COMMAND_CENTRE_SEED", None)
        sys.modules.pop("server", None)

    def test_oversize_body_413(self):
        """Flask returns 413 when MAX_CONTENT_LENGTH is exceeded.
        Without the cap, an authenticated abuser could DoS the
        dyno or fill the Railway volume with huge writes."""
        big = "x" * 5000  # well over the 1KB cap
        r = self.client.post("/api/qualify",
                              json={"name": big, "url": big})
        self.assertEqual(r.status_code, 413)

    def test_normal_body_accepted(self):
        # A small body still works (we just verify it's NOT 413 — the
        # actual handler may fail later for other reasons since we're
        # not seeding a full happy path here).
        r = self.client.post("/api/qualify",
                              json={"name": "X", "url": "https://x.com"})
        self.assertNotEqual(r.status_code, 413)


# -----------------------------------------------------------------
# 4. Path-traversal guards on store IDs
# -----------------------------------------------------------------

class PathTraversalGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["EXPANSION_TARGETS_STORE_DIR"] = os.path.join(self.tmp, "ex")
        os.environ["LIVE_PROJECTS_STORE_DIR"] = os.path.join(self.tmp, "lp")
        os.environ["LIVE_PROJECT_OKRS_STORE_DIR"] = os.path.join(self.tmp, "okrs")
        for mod in ("expansion_targets_store", "live_projects_store",
                    "live_project_okrs_store"):
            sys.modules.pop(mod, None)

    def tearDown(self):
        for k in ("EXPANSION_TARGETS_STORE_DIR",
                  "LIVE_PROJECTS_STORE_DIR",
                  "LIVE_PROJECT_OKRS_STORE_DIR"):
            os.environ.pop(k, None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_expansion_targets_rejects_traversal(self):
        import expansion_targets_store as s
        for bad in ("../etc/passwd", "..", "a/b", "a\\b",
                     "a b", "", "a" * 100, None, 42):
            with self.assertRaises((s.ExpansionTargetsStoreError, TypeError)):
                s._path(bad)
        # Valid UUID hex passes.
        ok = "abcd1234ef" * 3  # 30 chars, safe alphabet
        s._path(ok)  # no exception

    def test_live_projects_rejects_traversal(self):
        import live_projects_store as s
        for bad in ("../etc/passwd", "..", "a/b", "a\\b", ""):
            with self.assertRaises(s.LiveProjectsStoreError):
                s._path(bad)
        s._path("project_123")  # passes

    def test_live_project_okrs_rejects_traversal(self):
        import live_project_okrs_store as s
        for bad in ("../etc/passwd", "..", "a/b", "a\\b", ""):
            with self.assertRaises(s.LiveProjectOkrsStoreError):
                s._path(bad)
        s._path("okr-abc-123")  # passes


# -----------------------------------------------------------------
# 5. APP_AUTH_TOKEN no longer accepted via ?token= by default
# -----------------------------------------------------------------

class QueryTokenAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["APP_AUTH_TOKEN"] = "secret-token-fixture"
        os.environ.pop("AUTH_TOKEN_ALLOW_QUERY", None)
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        sys.modules.pop("server", None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("APP_AUTH_TOKEN", "AUTH_TOKEN_ALLOW_QUERY",
                  "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        sys.modules.pop("server", None)

    def test_query_token_rejected_by_default(self):
        """Token in ?token= used to bypass auth. Now header-only.
        Query strings leak via logs / Referer / browser history."""
        r = self.client.get("/api/owners?token=secret-token-fixture")
        self.assertEqual(r.status_code, 401)

    def test_header_token_still_works(self):
        r = self.client.get("/api/owners",
                              headers={"Authorization": "Bearer secret-token-fixture"})
        self.assertEqual(r.status_code, 200)

    def test_opt_in_query_token_when_env_set(self):
        """Set AUTH_TOKEN_ALLOW_QUERY=1 to keep the old behaviour for
        legacy tooling — re-import the module so the env var is picked up."""
        os.environ["AUTH_TOKEN_ALLOW_QUERY"] = "1"
        sys.modules.pop("server", None)
        import server as srv
        client = srv.app.test_client()
        r = client.get("/api/owners?token=secret-token-fixture")
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
