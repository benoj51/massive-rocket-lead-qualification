"""v0.9.2 — Claude-driven aggregated lead summary."""
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


class LeadSummaryStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["LEAD_SUMMARY_STORE_DIR"] = self.tmp
        for mod in ("lead_summary_store", "project_store"):
            sys.modules.pop(mod, None)

    def tearDown(self):
        os.environ.pop("LEAD_SUMMARY_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load_missing_returns_none(self):
        import lead_summary_store
        self.assertIsNone(lead_summary_store.load("nobody"))

    def test_save_load_roundtrip(self):
        import lead_summary_store
        saved = lead_summary_store.save("lead-a", {
            "state_of_play": "Mid-discovery, strong fit.",
            "key_facts": ["Braze in stack", "Champion identified"],
            "open_questions": ["Budget cycle?"],
            "next_action": "Book economic buyer call",
            "risks": [],
        })
        self.assertIn("generated_at", saved)
        loaded = lead_summary_store.load("lead-a")
        self.assertEqual(loaded["state_of_play"], "Mid-discovery, strong fit.")
        self.assertEqual(len(loaded["key_facts"]), 2)


class AiSynthesisPromptSchemaTests(unittest.TestCase):
    def test_prompt_documents_full_schema(self):
        import ai_summary
        for key in ("state_of_play", "key_facts", "open_questions",
                    "next_action", "risks"):
            self.assertIn(key, ai_summary._LEAD_SUMMARY_SYSTEM_PROMPT)

    def test_synthesise_lead_without_anthropic_returns_none(self):
        import ai_summary
        os.environ.pop("ANTHROPIC_API_KEY", None)
        self.assertIsNone(ai_summary.synthesise_lead({"lead_id": "x"}))


class LeadSummaryEndpointsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["LEAD_SUMMARY_STORE_DIR"] = os.path.join(cls.tmp, "summaries")
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        for mod in ("server", "lead_summary_store", "ai_summary"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("LEAD_SUMMARY_STORE_DIR", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_get_no_cached_summary_returns_null(self):
        r = self.client.get("/api/lead/no-such-lead/summary")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.get_json()["summary"])

    def test_post_without_anthropic_returns_503(self):
        r = self.client.post("/api/lead/x/summary", json={})
        self.assertEqual(r.status_code, 503)
        self.assertIn("ANTHROPIC_API_KEY", r.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
