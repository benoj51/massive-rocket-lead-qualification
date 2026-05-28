"""v1.0.0dm - scheduled agents (cron-style recurring jobs)."""
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


# --- Fake Anthropic client (mirrors tests/test_agent.py) -------------

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
        return _Resp([_Text("done")], "end_turn")

class _FakeAnthropic:
    script: list = []
    recorder: list = []
    def __init__(self, **kw):
        self.messages = _Messages(type(self).script, type(self).recorder)


def _make_fake(script):
    recorder: list = []
    cls = type("BoundFake", (_FakeAnthropic,),
               {"script": script, "recorder": recorder})
    return cls, recorder


class _Env:
    """Shared temp-dir + env setup so jobs read/write isolated stores."""
    @classmethod
    def setup(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["SCHEDULED_RUNS_STORE_DIR"] = os.path.join(cls.tmp, "runs")
        os.environ["PARTNERS_STORE_PATH"] = os.path.join(cls.tmp, "p.json")
        os.environ["PARTNER_CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "pc")
        os.environ["QUARTERLY_TARGETS_STORE_PATH"] = os.path.join(cls.tmp, "q.json")
        os.environ["AUDIT_LOG_PATH"] = os.path.join(cls.tmp, "audit.jsonl")
        os.environ["ANTHROPIC_API_KEY"] = "test"
        for m in ("scheduled_agents", "agent", "mr_tools", "watchlist_sweep",
                  "partners_store", "partner_contacts_store",
                  "stakeholder_coverage"):
            sys.modules.pop(m, None)

    @classmethod
    def teardown(cls):
        for k in ("SCHEDULED_RUNS_STORE_DIR", "PARTNERS_STORE_PATH",
                  "PARTNER_CONTACTS_STORE_DIR", "QUARTERLY_TARGETS_STORE_PATH",
                  "AUDIT_LOG_PATH", "ANTHROPIC_API_KEY"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)


class RegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Env.setup()
        import scheduled_agents
        cls.sa = scheduled_agents

    @classmethod
    def tearDownClass(cls):
        _Env.teardown()

    def test_jobs_present(self):
        keys = {j["key"] for j in self.sa.list_jobs()}
        for want in ("monday_pipeline_digest", "wednesday_news_sweep",
                     "friday_stale_stakeholders"):
            self.assertIn(want, keys)

    def test_job_shape(self):
        jobs = {j["key"]: j for j in self.sa.list_jobs()}
        mon = jobs["monday_pipeline_digest"]
        self.assertEqual(mon["kind"], "agent")
        self.assertEqual(mon["persona"], "pipeline_analyst")
        self.assertEqual(mon["weekday"], 0)
        self.assertIsNone(mon["last_run"])  # not run yet
        self.assertEqual(jobs["wednesday_news_sweep"]["kind"], "sweep")

    def test_jobs_for_weekday(self):
        mon = self.sa.jobs_for_weekday(0)
        self.assertEqual([j.key for j in mon], ["monday_pipeline_digest"])
        self.assertEqual(self.sa.jobs_for_weekday(1), [])  # Tuesday: none

    def test_unknown_job(self):
        out = self.sa.run_job("nope")
        self.assertEqual(out["code"], "unknown_job")


class RunAgentJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Env.setup()
        import scheduled_agents
        cls.sa = scheduled_agents

    @classmethod
    def tearDownClass(cls):
        _Env.teardown()

    def test_agent_job_runs_persists_and_audits(self):
        # Turn 1: model calls a tool. Turn 2: it answers.
        script = [
            _Resp([
                _Text("Checking attainment."),
                _ToolUse("t1", "get_quarterly_progress", {}),
            ], "tool_use"),
            _Resp([_Text("Here is the Monday digest.")], "end_turn"),
        ]
        Fake, _ = _make_fake(script)
        import anthropic
        with patch.object(anthropic, "Anthropic", Fake):
            rec = self.sa.run_job("monday_pipeline_digest", actor="cron")
        self.assertTrue(rec["ok"])
        self.assertIn("Monday digest", rec["message"])
        self.assertEqual(rec["kind"], "agent")
        self.assertEqual(rec["actor"], "cron")
        self.assertEqual(len(rec["steps"]), 1)
        self.assertEqual(rec["steps"][0]["tool"], "get_quarterly_progress")
        # Persisted: latest_run returns the same record.
        saved = self.sa.latest_run("monday_pipeline_digest")
        self.assertIsNotNone(saved)
        self.assertEqual(saved["ran_at"], rec["ran_at"])
        # list_jobs now surfaces the last run.
        mon = {j["key"]: j for j in self.sa.list_jobs()}["monday_pipeline_digest"]
        self.assertIsNotNone(mon["last_run"])
        # Audit event written.
        import audit
        types = {e["type"] for e in audit.read_events(limit=20)}
        self.assertIn("scheduled_job_ran", types)

    def test_agent_job_offline_when_not_configured(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            rec = self.sa.run_job("friday_stale_stakeholders")
        finally:
            os.environ["ANTHROPIC_API_KEY"] = "test"
        self.assertFalse(rec["ok"])
        self.assertEqual(rec.get("error_code"), "agent_disabled")


class RunSweepJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Env.setup()
        import scheduled_agents
        cls.sa = scheduled_agents

    @classmethod
    def tearDownClass(cls):
        _Env.teardown()

    def test_sweep_job_summarises_and_attaches_data(self):
        fake_summary = {
            "leads_scanned": 3,
            "items_added": 5,
            "notifications_fired": 2,
            "errors": [],
        }
        import watchlist_sweep
        with patch.object(watchlist_sweep, "run_sweep",
                          return_value=fake_summary):
            rec = self.sa.run_job("wednesday_news_sweep", actor="cron")
        self.assertTrue(rec["ok"])
        self.assertEqual(rec["kind"], "sweep")
        self.assertEqual(rec["steps"], [])
        self.assertEqual(rec["data"], fake_summary)
        self.assertIn("3 watched", rec["message"])
        self.assertIn("5 new news items", rec["message"])

    def test_sweep_job_ok_false_on_errors(self):
        import watchlist_sweep
        with patch.object(watchlist_sweep, "run_sweep",
                          return_value={"leads_scanned": 1, "items_added": 0,
                                        "notifications_fired": 0,
                                        "errors": ["boom"]}):
            rec = self.sa.run_job("wednesday_news_sweep")
        self.assertFalse(rec["ok"])
        self.assertIn("error", rec["message"].lower())


class EndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib
        _Env.setup()
        os.environ.pop("APP_AUTH_TOKEN", None)
        for m in ("server",):
            sys.modules.pop(m, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        _Env.teardown()

    def test_list_endpoint(self):
        r = self.client.get("/api/agent/scheduled")
        self.assertEqual(r.status_code, 200)
        keys = {j["key"] for j in r.get_json()["jobs"]}
        self.assertIn("monday_pipeline_digest", keys)

    def test_run_endpoint_sweep(self):
        import watchlist_sweep
        with patch.object(watchlist_sweep, "run_sweep",
                          return_value={"leads_scanned": 0, "items_added": 0,
                                        "notifications_fired": 0,
                                        "errors": []}):
            r = self.client.post("/api/agent/scheduled/wednesday_news_sweep/run")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["ok"])

    def test_run_endpoint_unknown(self):
        r = self.client.post("/api/agent/scheduled/ghost/run")
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
