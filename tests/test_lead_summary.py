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
                    "next_action", "risks", "qualification", "coaching"):
            self.assertIn(key, ai_summary._LEAD_SUMMARY_SYSTEM_PROMPT)

    def test_prompt_documents_rag_verdict(self):
        """v1.0.0dt: qualification RAG verdict + AE coaching folded in."""
        import ai_summary
        prompt = ai_summary._LEAD_SUMMARY_SYSTEM_PROMPT
        # The three RAG colours must be named so the model emits a value
        # the UI badge can map.
        for colour in ("green", "amber", "red"):
            self.assertIn(colour, prompt)
        # House voice: UK English + no em-dashes.
        self.assertIn("UK English", prompt)

    def test_prompt_documents_group_context(self):
        """v0.10.0d: prompt teaches Claude about parent/sibling context."""
        import ai_summary
        prompt = ai_summary._LEAD_SUMMARY_SYSTEM_PROMPT
        # Must explain what to do when the lead is a child or parent.
        self.assertIn("group", prompt.lower())
        self.assertIn("sibling", prompt.lower())
        # Must mention both roles.
        self.assertIn('"child"', prompt)
        self.assertIn('"parent"', prompt)

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


class GatherLeadContextNoneExtractedTests(unittest.TestCase):
    """v0.9.4 regression: _gather_lead_context crashed with
    AttributeError when a call had extracted=None (which happens when
    Claude extraction fails mid-save and the call is stored with the
    raw transcript only). Reproduces the trace from the 2026-05-17 prod
    incident."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["CALLS_STORE_DIR"] = os.path.join(cls.tmp, "calls")
        os.environ["LEAD_SUMMARY_STORE_DIR"] = os.path.join(cls.tmp, "summaries")
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        for mod in ("server", "calls_store", "lead_summary_store", "ai_summary"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("CALLS_STORE_DIR", None)
        os.environ.pop("LEAD_SUMMARY_STORE_DIR", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_group_context_none_for_standalone(self):
        """v0.10.0d: standalone leads get group=None in the context."""
        import calls_store
        calls_store.add_call("solo-lead", {
            "type": "note", "content": "isolated", "extracted": {},
        })
        ctx = self.server._gather_lead_context("solo-lead")
        self.assertIsNone(ctx.get("group"))

    def test_gather_context_handles_none_extracted(self):
        # Write a call with extracted=None directly (mirrors what
        # calls_store.add does when payload.get("extracted") is falsy).
        import calls_store
        calls_store.add_call("lead-xyz", {
            "type": "transcript",
            "title": "Discovery #2",
            "content": "long raw transcript " * 200,
            "extracted": None,  # the bug-triggering shape
        })
        # _gather_lead_context should not raise.
        ctx = self.server._gather_lead_context("lead-xyz")
        self.assertEqual(len(ctx["calls"]), 1)
        self.assertIsNone(ctx["calls"][0]["extracted_meddpicc"])


class FormatSummaryForNotionTests(unittest.TestCase):
    """v0.10.0f: structured summary → single rich-text block for Notion."""

    @classmethod
    def setUpClass(cls):
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        for mod in ("server", "lead_summary_store", "ai_summary"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")

    def test_full_summary_renders_all_sections(self):
        out = self.server._format_summary_for_notion({
            "state_of_play": "Mid-discovery on CDP build, fit is strong.",
            "key_facts": ["Braze in stack", "Champion identified"],
            "open_questions": ["Budget cycle?", "Decision criteria?"],
            "next_action": "Book economic buyer call",
            "risks": ["No procurement engagement"],
            "generated_at": "2026-05-17T12:00:00Z",
        })
        self.assertIn("Mid-discovery on CDP build", out)
        self.assertIn("KEY FACTS:", out)
        self.assertIn("• Braze in stack", out)
        self.assertIn("OPEN QUESTIONS:", out)
        self.assertIn("NEXT ACTION: Book economic buyer call", out)
        self.assertIn("RISKS:", out)
        self.assertIn("• No procurement engagement", out)
        self.assertIn("Generated 2026-05-17", out)

    def test_minimal_summary_omits_empty_sections(self):
        out = self.server._format_summary_for_notion({
            "state_of_play": "Just one note in.",
        })
        self.assertIn("Just one note in.", out)
        self.assertNotIn("KEY FACTS:", out)
        self.assertNotIn("OPEN QUESTIONS:", out)
        self.assertNotIn("RISKS:", out)
        self.assertNotIn("QUALIFICATION:", out)
        self.assertNotIn("COACHING:", out)

    def test_qualification_and_coaching_render(self):
        """v1.0.0dt: the RAG verdict + coaching points flow into Notion."""
        out = self.server._format_summary_for_notion({
            "qualification": {"rag": "amber",
                              "rationale": "Strong fit but no Economic Buyer yet."},
            "state_of_play": "Mid-discovery on a CDP build.",
            "coaching": ["Multi-thread to the CFO",
                         "Arm the champion with the ROI deck"],
        })
        self.assertIn("QUALIFICATION: AMBER", out)
        self.assertIn("Strong fit but no Economic Buyer yet.", out)
        self.assertIn("COACHING:", out)
        self.assertIn("• Multi-thread to the CFO", out)
        self.assertIn("• Arm the champion with the ROI deck", out)


if __name__ == "__main__":
    unittest.main()
