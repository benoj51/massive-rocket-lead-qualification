"""v1.0.0dk - tool-using agent + persona library."""
from __future__ import annotations

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


# --- Fake Anthropic client -------------------------------------------

class _Text:
    type = "text"
    def __init__(self, text): self.text = text

class _ToolUse:
    type = "tool_use"
    def __init__(self, id, name, input):  # noqa: A002
        self.id = id
        self.name = name
        self.input = input

class _Resp:
    def __init__(self, content, stop_reason):
        self.content = content
        self.stop_reason = stop_reason

class _Messages:
    def __init__(self, script, recorder):
        self._script = list(script)
        self._recorder = recorder
    def create(self, **kwargs):
        self._recorder.append(kwargs)
        if self._script:
            return self._script.pop(0)
        # Default terminal response if the script runs dry.
        return _Resp([_Text("done")], "end_turn")

class _FakeAnthropic:
    """Class factory bound to a script + recorder via closures."""
    script: list = []
    recorder: list = []
    def __init__(self, **kw):
        self.messages = _Messages(type(self).script, type(self).recorder)


def _make_fake(script):
    recorder: list = []
    cls = type("BoundFake", (_FakeAnthropic,),
               {"script": script, "recorder": recorder})
    return cls, recorder


class PersonaRegistryTests(unittest.TestCase):
    def setUp(self):
        sys.modules.pop("agent", None)
        import agent
        self.agent = agent

    def test_personas_present(self):
        keys = {p["key"] for p in self.agent.list_personas()}
        for want in ("researcher", "partner_coach", "briefing",
                     "pipeline_analyst", "jeff"):
            self.assertIn(want, keys)

    def test_persona_has_starters_and_label(self):
        p = self.agent.get_persona("researcher")
        self.assertIsNotNone(p)
        self.assertTrue(p.label)
        self.assertTrue(p.starters)

    def test_unknown_persona(self):
        out = self.agent.run_agent("nope", [{"role": "user", "content": "hi"}])
        self.assertEqual(out["code"], "unknown_persona")

    def test_not_configured(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        out = self.agent.run_agent("researcher",
                                   [{"role": "user", "content": "hi"}])
        self.assertEqual(out["code"], "agent_disabled")


class AgentLoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["PARTNERS_STORE_PATH"] = os.path.join(cls.tmp, "p.json")
        os.environ["PARTNER_CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "pc")
        os.environ["ANTHROPIC_API_KEY"] = "test"
        for m in ("agent", "mr_tools", "partners_store",
                  "partner_contacts_store", "stakeholder_coverage"):
            sys.modules.pop(m, None)
        import agent
        cls.agent = agent

    @classmethod
    def tearDownClass(cls):
        for k in ("PARTNERS_STORE_PATH", "PARTNER_CONTACTS_STORE_DIR",
                  "ANTHROPIC_API_KEY"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_tool_loop_runs_and_traces(self):
        # Turn 1: model calls get_stakeholder_coverage. Turn 2: answers.
        script = [
            _Resp([
                _Text("Let me check coverage."),
                _ToolUse("tu1", "get_stakeholder_coverage", {"window_days": 30}),
            ], "tool_use"),
            _Resp([_Text("Coverage looks empty right now.")], "end_turn"),
        ]
        Fake, recorder = _make_fake(script)
        import anthropic
        with patch.object(anthropic, "Anthropic", Fake):
            out = self.agent.run_agent(
                "partner_coach",
                [{"role": "user", "content": "How's coverage?"}],
            )
        self.assertEqual(out["stopped"], "end_turn")
        self.assertIn("Coverage", out["message"])
        self.assertEqual(len(out["steps"]), 1)
        step = out["steps"][0]
        self.assertEqual(step["tool"], "get_stakeholder_coverage")
        self.assertTrue(step["ok"])
        self.assertFalse(step["writes"])
        # The first create call must have been given a tools list.
        self.assertIn("tools", recorder[0])
        self.assertTrue(recorder[0]["tools"])

    def test_write_tools_excluded_without_allow_writes(self):
        # partner_coach can't write anyway; use researcher and confirm
        # log_call never appears in the toolset when allow_writes=False.
        script = [_Resp([_Text("hi")], "end_turn")]
        Fake, recorder = _make_fake(script)
        import anthropic
        with patch.object(anthropic, "Anthropic", Fake):
            self.agent.run_agent(
                "researcher",
                [{"role": "user", "content": "hello"}],
                allow_writes=False,
            )
        tool_names = {t["name"] for t in recorder[0]["tools"]}
        self.assertNotIn("log_call", tool_names)
        # Researcher is scoped: it should NOT get outreach-only tools.
        self.assertIn("get_lead", tool_names)

    def test_max_steps_forces_synthesis(self):
        # Model keeps calling a tool forever; loop must cap and synthesise.
        loop_resp = _Resp([
            _ToolUse("tuX", "get_stakeholder_coverage", {}),
        ], "tool_use")
        # 3 tool turns + 1 final synthesis create call.
        script = [loop_resp, loop_resp, loop_resp,
                  _Resp([_Text("Final synthesis.")], "end_turn")]
        Fake, recorder = _make_fake(script)
        import anthropic
        with patch.object(anthropic, "Anthropic", Fake):
            out = self.agent.run_agent(
                "pipeline_analyst",
                [{"role": "user", "content": "loop"}],
                max_steps=3,
            )
        self.assertEqual(out["stopped"], "max_steps")
        self.assertEqual(len(out["steps"]), 3)
        self.assertIn("Final synthesis", out["message"])

    def test_no_messages_rejected(self):
        out = self.agent.run_agent("researcher", [])
        self.assertEqual(out["code"], "invalid_request")


class AgentEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib
        cls.tmp = tempfile.mkdtemp()
        os.environ["PARTNERS_STORE_PATH"] = os.path.join(cls.tmp, "p.json")
        os.environ["PARTNER_CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "pc")
        os.environ.pop("APP_AUTH_TOKEN", None)
        os.environ["ANTHROPIC_API_KEY"] = "test"
        for m in ("server", "agent", "mr_tools"):
            sys.modules.pop(m, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("PARTNERS_STORE_PATH", "PARTNER_CONTACTS_STORE_DIR",
                  "ANTHROPIC_API_KEY"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_personas_endpoint(self):
        r = self.client.get("/api/agent/personas")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        keys = {p["key"] for p in body["personas"]}
        self.assertIn("researcher", keys)
        self.assertTrue(body["configured"])

    def test_chat_endpoint_runs(self):
        script = [_Resp([_Text("Hello from the agent.")], "end_turn")]
        Fake, _ = _make_fake(script)
        import anthropic
        with patch.object(anthropic, "Anthropic", Fake):
            r = self.client.post("/api/agent/chat", json={
                "persona": "researcher",
                "messages": [{"role": "user", "content": "hi"}],
            })
        self.assertEqual(r.status_code, 200)
        self.assertIn("Hello", r.get_json()["message"])

    def test_chat_endpoint_unknown_persona(self):
        r = self.client.post("/api/agent/chat", json={
            "persona": "ghost",
            "messages": [{"role": "user", "content": "hi"}],
        })
        self.assertEqual(r.status_code, 400)

    def test_chat_endpoint_requires_messages(self):
        r = self.client.post("/api/agent/chat", json={"persona": "researcher"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
