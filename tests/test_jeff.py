"""v1.0.0bs — Jeff (in-app pricing assistant) tests.

Covers:
1. jeff_knowledge.build_system_prompt: skill-level framing,
   context-block rendering, pricing-facts inclusion, KB doc merge.
2. /api/jeff/chat: payload validation, skill normalisation,
   Anthropic call wiring (mocked), graceful disabled-mode response.
3. /api/jeff/knowledge GET + PUT: round-trip + audit.
"""
from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# -----------------------------------------------------------------
# Layer 1: jeff_knowledge.build_system_prompt
# -----------------------------------------------------------------

class JeffKnowledgePromptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb_file = Path(self.tmp) / "kb.md"
        os.environ["JEFF_KB_PATH"] = str(self.kb_file)
        sys.modules.pop("jeff_knowledge", None)
        import jeff_knowledge
        self.mod = jeff_knowledge

    def tearDown(self):
        os.environ.pop("JEFF_KB_PATH", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_identity_block_present(self):
        p = self.mod.build_system_prompt()
        self.assertIn("Jeff", p)
        # Identity sets scope expectations — should mention pricing.
        self.assertIn("pricing", p.lower())

    def test_skill_block_beginner_explains(self):
        p = self.mod.build_system_prompt(skill="beginner")
        self.assertIn("BEGINNER", p)
        # Beginner framing should mention explaining terminology.
        self.assertIn("terminology", p.lower())

    def test_skill_block_expert_terse(self):
        p = self.mod.build_system_prompt(skill="expert")
        self.assertIn("EXPERT", p)
        # Expert framing reduces verbosity.
        self.assertIn("terse", p.lower())

    def test_skill_block_intermediate_default(self):
        p = self.mod.build_system_prompt()
        self.assertIn("INTERMEDIATE", p)

    def test_unknown_skill_falls_back_to_intermediate(self):
        p = self.mod.build_system_prompt(skill="ninja")
        # Falls back silently — shouldn't surface the bogus value.
        self.assertIn("INTERMEDIATE", p)
        self.assertNotIn("ninja", p.lower())

    def test_pricing_facts_block_pulls_blended_rate(self):
        p = self.mod.build_system_prompt()
        # Live read from pricing.py — the blended rate should appear.
        self.assertIn("$200", p)
        self.assertIn("160", p)  # hours per FTE-month

    def test_pricing_facts_block_lists_rate_cards(self):
        p = self.mod.build_system_prompt()
        self.assertIn("MR Default", p)
        self.assertIn("Staff Augmentation", p)

    def test_pricing_facts_block_lists_team_templates(self):
        p = self.mod.build_system_prompt()
        # Each template should surface so Jeff knows which project
        # types exist.
        self.assertIn("crm_build", p)
        self.assertIn("data_work", p)

    def test_context_block_renders_view(self):
        p = self.mod.build_system_prompt(context={"view": "build"})
        self.assertIn("build", p)

    def test_context_block_renders_lead(self):
        p = self.mod.build_system_prompt(context={
            "view": "qualify",
            "lead": {"company": "Shell", "vertical": "Energy",
                      "opportunity_type": "crm_build"},
        })
        self.assertIn("Shell", p)
        self.assertIn("Energy", p)

    def test_context_block_renders_pricing(self):
        p = self.mod.build_system_prompt(context={
            "pricing": {"rate_card": "MR Default", "months": 12,
                         "project_ops_pct": 15},
        })
        self.assertIn("MR Default", p)
        self.assertIn("12", p)

    def test_context_block_omitted_when_empty(self):
        p_with = self.mod.build_system_prompt(context={"view": "home"})
        p_without = self.mod.build_system_prompt(context=None)
        # Without context the "User context" heading shouldn't appear.
        self.assertNotIn("User context", p_without)
        self.assertIn("User context", p_with)

    def test_kb_doc_merged_when_present(self):
        self.kb_file.write_text("## Custom guidance\n\nDon't quote on Fridays.")
        p = self.mod.build_system_prompt()
        self.assertIn("Custom guidance", p)
        self.assertIn("Don't quote on Fridays", p)

    def test_kb_doc_optional(self):
        # No file — system prompt still builds (facts only).
        p = self.mod.build_system_prompt()
        self.assertNotIn("Best-practice guidance", p)

    def test_kb_round_trip(self):
        self.mod.save_best_practices("# Hello")
        self.assertEqual(self.mod.load_best_practices(), "# Hello")

    def test_kb_empty_string_clears(self):
        self.mod.save_best_practices("# Stuff")
        self.mod.save_best_practices("")
        self.assertEqual(self.mod.load_best_practices(), "")


# -----------------------------------------------------------------
# Layer 2: jeff_knowledge.is_configured
# -----------------------------------------------------------------

class JeffKnowledgeConfigTests(unittest.TestCase):
    def setUp(self):
        sys.modules.pop("jeff_knowledge", None)
        import jeff_knowledge
        self.mod = jeff_knowledge
        # Snapshot + clear so each test sets explicitly.
        self._prev = os.environ.pop("ANTHROPIC_API_KEY", None)

    def tearDown(self):
        if self._prev is not None:
            os.environ["ANTHROPIC_API_KEY"] = self._prev
        else:
            os.environ.pop("ANTHROPIC_API_KEY", None)

    def test_unconfigured_when_no_key(self):
        self.assertFalse(self.mod.is_configured())

    def test_unconfigured_when_blank_key(self):
        os.environ["ANTHROPIC_API_KEY"] = "   "
        self.assertFalse(self.mod.is_configured())

    def test_configured_when_key_set(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-test"
        self.assertTrue(self.mod.is_configured())


# -----------------------------------------------------------------
# Layer 3: /api/jeff/chat endpoint
# -----------------------------------------------------------------

class JeffChatEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["JEFF_KB_PATH"] = os.path.join(cls.tmp, "kb.md")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "jeff_knowledge"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("JEFF_KB_PATH", "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        # Default to "configured" so the happy path runs without
        # tripping the disabled-mode early return. Individual tests
        # override by popping/setting the env var.
        os.environ["ANTHROPIC_API_KEY"] = "sk-test-fixture"

    def tearDown(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)

    def _mock_anthropic(self, reply_text="Sure thing."):
        """Build a MagicMock that quacks like the Anthropic client +
        returns the supplied text as the assistant reply."""
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = reply_text
        resp = MagicMock()
        resp.content = [text_block]
        client_inst = MagicMock()
        client_inst.messages.create.return_value = resp
        client_factory = MagicMock(return_value=client_inst)
        return client_factory, client_inst

    def test_disabled_when_no_key(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        r = self.client.post("/api/jeff/chat", json={
            "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.get_json()["code"], "jeff_disabled")

    def test_rejects_missing_messages(self):
        r = self.client.post("/api/jeff/chat", json={})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["code"], "invalid_request")

    def test_rejects_empty_content_only(self):
        r = self.client.post("/api/jeff/chat", json={
            "messages": [{"role": "user", "content": "   "}]})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["code"], "invalid_request")

    def test_happy_path_returns_message(self):
        factory, client_inst = self._mock_anthropic("Use MR Default.")
        with patch.dict(sys.modules, {"anthropic": MagicMock(Anthropic=factory)}):
            r = self.client.post("/api/jeff/chat", json={
                "messages": [{"role": "user",
                                "content": "Which rate card for a new client?"}],
                "skill":    "intermediate",
                "context":  {"view": "build"},
            })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["message"], "Use MR Default.")
        # The mock should have been called once.
        self.assertEqual(client_inst.messages.create.call_count, 1)

    def test_system_prompt_includes_skill_framing(self):
        """Verify the right system prompt is sent for the picked skill."""
        factory, client_inst = self._mock_anthropic()
        with patch.dict(sys.modules, {"anthropic": MagicMock(Anthropic=factory)}):
            self.client.post("/api/jeff/chat", json={
                "messages": [{"role": "user", "content": "hi"}],
                "skill":    "expert",
            })
        call = client_inst.messages.create.call_args
        # System prompt is a kwarg.
        self.assertIn("EXPERT", call.kwargs["system"])

    def test_messages_normalised(self):
        """Roles other than user/assistant should be coerced; long
        content should be truncated to 8000 chars."""
        factory, client_inst = self._mock_anthropic()
        with patch.dict(sys.modules, {"anthropic": MagicMock(Anthropic=factory)}):
            self.client.post("/api/jeff/chat", json={
                "messages": [
                    {"role": "system", "content": "ignored"},  # role coerced to "user"
                    {"role": "user", "content": "x" * 10000},  # truncated
                ]})
        sent = client_inst.messages.create.call_args.kwargs["messages"]
        # 2 messages — first one's role normalised to "user" too.
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0]["role"], "user")
        self.assertEqual(len(sent[1]["content"]), 8000)

    def test_context_passed_through_to_system_prompt(self):
        factory, client_inst = self._mock_anthropic()
        with patch.dict(sys.modules, {"anthropic": MagicMock(Anthropic=factory)}):
            self.client.post("/api/jeff/chat", json={
                "messages": [{"role": "user", "content": "hi"}],
                "context":  {"view": "build",
                              "lead": {"company": "TestCo", "vertical": "QSR"}},
            })
        sys_prompt = client_inst.messages.create.call_args.kwargs["system"]
        self.assertIn("TestCo", sys_prompt)
        self.assertIn("QSR", sys_prompt)

    def test_upstream_failure_returns_502(self):
        factory = MagicMock()
        client_inst = MagicMock()
        client_inst.messages.create.side_effect = RuntimeError("Anthropic down")
        factory.return_value = client_inst
        with patch.dict(sys.modules, {"anthropic": MagicMock(Anthropic=factory)}):
            r = self.client.post("/api/jeff/chat", json={
                "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.get_json()["code"], "upstream_error")

    def test_history_capped_at_20(self):
        """Long conversations should only send the last 20 turns
        upstream — keeps context window manageable."""
        factory, client_inst = self._mock_anthropic()
        many = [{"role": "user", "content": f"msg{i}"} for i in range(50)]
        with patch.dict(sys.modules, {"anthropic": MagicMock(Anthropic=factory)}):
            self.client.post("/api/jeff/chat", json={"messages": many})
        sent = client_inst.messages.create.call_args.kwargs["messages"]
        self.assertEqual(len(sent), 20)
        # Should be the LAST 20.
        self.assertEqual(sent[-1]["content"], "msg49")
        self.assertEqual(sent[0]["content"], "msg30")


# -----------------------------------------------------------------
# Layer 4: /api/jeff/knowledge endpoints
# -----------------------------------------------------------------

class JeffKnowledgeEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["JEFF_KB_PATH"] = os.path.join(cls.tmp, "kb.md")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "jeff_knowledge"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("JEFF_KB_PATH", "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        # Reset KB file between tests.
        p = Path(os.environ["JEFF_KB_PATH"])
        if p.exists():
            p.unlink()

    def test_get_empty_when_no_doc(self):
        r = self.client.get("/api/jeff/knowledge")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["body"], "")
        self.assertEqual(body["chars"], 0)
        self.assertIn("configured", body)

    def test_put_and_get_round_trip(self):
        r = self.client.put("/api/jeff/knowledge",
                              json={"body": "# Tips\n\nPush back on Fridays."})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["saved"])
        r = self.client.get("/api/jeff/knowledge")
        self.assertIn("Push back on Fridays", r.get_json()["body"])

    def test_put_rejects_non_string(self):
        r = self.client.put("/api/jeff/knowledge", json={"body": 123})
        self.assertEqual(r.status_code, 400)

    def test_put_empty_clears_doc(self):
        self.client.put("/api/jeff/knowledge", json={"body": "# Stuff"})
        self.client.put("/api/jeff/knowledge", json={"body": ""})
        r = self.client.get("/api/jeff/knowledge")
        self.assertEqual(r.get_json()["body"], "")


if __name__ == "__main__":
    unittest.main()
