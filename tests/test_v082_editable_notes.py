"""v0.8.2 — editable call notes + synthesised note format + JS hotfix coverage."""
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


class JsSyntaxRegressionTest(unittest.TestCase):
    """The hotfix that landed this version: duplicate `const ccy` declarations
    broke the entire script. Lock that down so it doesn't regress."""

    def test_no_duplicate_const_ccy_in_renderpricing(self):
        with open(ROOT / "qualify.html") as f:
            html = f.read()
        # Extract the JS block
        start = html.find("<script>", html.find("</style>"))
        end = html.rfind("</script>")
        js = html[start:end]
        # Find the renderPricing function body. Count `const ccy =` occurrences
        # inside it.
        import re
        # Look at renderPricing function specifically
        m = re.search(r"function renderPricing\b.*?\n  \}", js, re.DOTALL)
        self.assertIsNotNone(m, "renderPricing function not found in qualify.html")
        body = m.group(0)
        # The body should declare `const ccy` at most once
        # (we share the value with the editable team table block below).
        ccy_decls = re.findall(r"\bconst\s+ccy\s*=", body)
        self.assertLessEqual(len(ccy_decls), 1,
                             f"Duplicate const ccy in renderPricing — breaks the script. "
                             f"Found {len(ccy_decls)} declarations.")


class CallsStoreEditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["CALLS_STORE_DIR"] = self.tmp
        for mod in ("calls_store", "project_store"):
            sys.modules.pop(mod, None)

    def tearDown(self):
        os.environ.pop("CALLS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_add_call_seeds_note_from_extracted_synthesised_note(self):
        import calls_store
        rec = calls_store.add_call("lead-a", {
            "content": "raw transcript",
            "extracted": {
                "synthesised_note": "## Headline\nGood call.",
                "meddpicc": {},
            },
        })
        self.assertEqual(rec["note"], "## Headline\nGood call.")

    def test_add_call_with_explicit_note_wins_over_extracted(self):
        import calls_store
        rec = calls_store.add_call("lead-a", {
            "content": "raw",
            "note": "AE wrote this directly.",
            "extracted": {"synthesised_note": "AI version"},
        })
        self.assertEqual(rec["note"], "AE wrote this directly.")

    def test_update_call_sets_note(self):
        import calls_store
        rec = calls_store.add_call("l", {"content": "x"})
        updated = calls_store.update_call("l", rec["id"],
                                          {"note": "Edited version."})
        self.assertEqual(updated["note"], "Edited version.")
        # Round-trip via list
        rows = calls_store.list_calls("l")
        self.assertEqual(rows[0]["note"], "Edited version.")

    def test_update_call_preserves_content_and_extracted(self):
        import calls_store
        rec = calls_store.add_call("l", {
            "content": "raw",
            "extracted": {"synthesised_note": "AI"},
        })
        calls_store.update_call("l", rec["id"], {"note": "Manual"})
        rows = calls_store.list_calls("l")
        self.assertEqual(rows[0]["content"], "raw")
        self.assertEqual(rows[0]["extracted"]["synthesised_note"], "AI")
        self.assertEqual(rows[0]["note"], "Manual")

    def test_update_unknown_returns_none(self):
        import calls_store
        self.assertIsNone(calls_store.update_call("l", "no-such-id", {"note": "x"}))


class CallsEditEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["CALLS_STORE_DIR"] = cls.tmp
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        for mod in ("server", "calls_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("CALLS_STORE_DIR", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_patch_call_endpoint_updates_note(self):
        r = self.client.post("/api/calls/lead-x", json={
            "content": "raw transcript here",
        })
        self.assertEqual(r.status_code, 200)
        call_id = r.get_json()["call"]["id"]
        # Patch it
        p = self.client.patch(f"/api/calls/lead-x/{call_id}",
                              json={"note": "## Headline\nWent well."})
        self.assertEqual(p.status_code, 200)
        self.assertEqual(p.get_json()["call"]["note"], "## Headline\nWent well.")

    def test_patch_call_unknown_returns_404(self):
        r = self.client.patch("/api/calls/lead-x/nope", json={"note": "x"})
        self.assertEqual(r.status_code, 404)

    def test_patch_call_empty_body_returns_400(self):
        r = self.client.post("/api/calls/lead-y", json={"content": "x"})
        call_id = r.get_json()["call"]["id"]
        p = self.client.patch(f"/api/calls/lead-y/{call_id}", json={})
        self.assertEqual(p.status_code, 400)


class AiPromptSchemaTests(unittest.TestCase):
    """The AI prompt now asks for a synthesised_note in markdown."""

    def test_prompt_documents_synthesised_note(self):
        import ai_summary
        self.assertIn("synthesised_note", ai_summary._EXTRACT_SYSTEM_PROMPT)
        # Must mention the section structure
        for section in ("Headline", "Attendees", "Discovery",
                         "Action items", "Project shaping"):
            self.assertIn(section, ai_summary._EXTRACT_SYSTEM_PROMPT)

    def test_extract_without_api_key_returns_none(self):
        import ai_summary
        os.environ.pop("ANTHROPIC_API_KEY", None)
        self.assertIsNone(ai_summary.extract_from_notes("Some sample notes"))


if __name__ == "__main__":
    unittest.main()
