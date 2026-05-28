"""v1.0.0dj - unified agentic tool registry (mr_tools)."""
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


class RegistryShapeTests(unittest.TestCase):
    def setUp(self):
        sys.modules.pop("mr_tools", None)
        import mr_tools
        self.mr = mr_tools

    def test_tool_names_unique_and_schemas_valid(self):
        tools = self.mr.all_tools()
        names = [t.name for t in tools]
        self.assertEqual(len(names), len(set(names)), "duplicate tool names")
        for t in tools:
            self.assertTrue(t.description.strip(), f"{t.name} missing desc")
            self.assertIsInstance(t.input_schema, dict)
            self.assertEqual(t.input_schema.get("type"), "object",
                             f"{t.name} schema must be an object")

    def test_expected_tools_present(self):
        names = {t.name for t in self.mr.all_tools()}
        for want in ("list_leads", "get_lead", "get_engagement_score",
                     "list_partner_contacts", "get_overdue_contacts",
                     "get_stakeholder_coverage", "get_quarterly_progress",
                     "list_use_cases", "match_proof_points",
                     "draft_outreach", "log_call"):
            self.assertIn(want, names)

    def test_anthropic_tools_format(self):
        defs = self.mr.anthropic_tools()
        self.assertTrue(defs)
        for d in defs:
            self.assertEqual(set(d.keys()),
                             {"name", "description", "input_schema"})

    def test_include_writes_filter(self):
        with_writes = {t.name for t in self.mr.all_tools(include_writes=True)}
        no_writes = {t.name for t in self.mr.all_tools(include_writes=False)}
        self.assertIn("log_call", with_writes)
        self.assertNotIn("log_call", no_writes)

    def test_call_unknown_tool_returns_error(self):
        out = self.mr.call_tool("does_not_exist", {})
        self.assertIn("error", out)
        self.assertIn("available", out)

    def test_call_tool_never_raises_on_handler_error(self):
        # draft_outreach with no contact -> handled error, not exception
        out = self.mr.call_tool("draft_outreach", {"channel": "email"})
        self.assertIn("error", out)

    def test_tag_filtering(self):
        partner_tools = {t.name for t in self.mr.all_tools(tags=("partners",))}
        self.assertIn("get_stakeholder_coverage", partner_tools)
        self.assertNotIn("list_leads", partner_tools)


class HandlerTests(unittest.TestCase):
    """Exercise handlers against temp stores so we touch real code paths
    without Notion / Postgres / Anthropic."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["PARTNERS_STORE_PATH"] = os.path.join(cls.tmp, "p.json")
        os.environ["PARTNER_CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "pc")
        os.environ["CALLS_STORE_DIR"] = os.path.join(cls.tmp, "calls")
        os.environ["QUARTERLY_TARGETS_STORE_PATH"] = os.path.join(
            cls.tmp, "qt.json")
        # Make sure use-cases DB is treated as unconfigured.
        os.environ.pop("DATABASE_URL_USECASES", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        for m in ("mr_tools", "partners_store", "partner_contacts_store",
                  "calls_store", "quarterly_targets_store",
                  "stakeholder_coverage", "usecases_db", "outreach"):
            sys.modules.pop(m, None)
        import mr_tools
        cls.mr = mr_tools

    @classmethod
    def tearDownClass(cls):
        for k in ("PARTNERS_STORE_PATH", "PARTNER_CONTACTS_STORE_DIR",
                  "CALLS_STORE_DIR", "QUARTERLY_TARGETS_STORE_PATH"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_list_partner_contacts_and_coverage(self):
        import partners_store
        import partner_contacts_store
        partners_store.save_partner({"name": "Braze"})
        partner_contacts_store.save_contact("braze", {
            "name": "Marina Klusas", "title": "Strategic AE",
            "is_key_stakeholder": True,
        })
        out = self.mr.call_tool("list_partner_contacts", {"partner_id": "braze"})
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["contacts"][0]["name"], "Marina Klusas")

        cov = self.mr.call_tool("get_stakeholder_coverage", {"window_days": 30})
        self.assertIn("totals", cov)
        self.assertEqual(cov["totals"]["key_total"], 1)
        # Never touched -> not covered
        self.assertEqual(cov["totals"]["never_touched"], 1)

    def test_get_overdue_contacts(self):
        out = self.mr.call_tool("get_overdue_contacts", {})
        self.assertIn("overdue", out)
        self.assertIsInstance(out["overdue"], list)

    def test_quarterly_progress_attainment(self):
        import quarterly_targets_store as qt
        qt.upsert_quarter({"id": "2026-Q2", "label": "Q2 2026"})
        qt.set_cell("2026-Q2", "qls", "plan", None, 100)
        qt.set_cell("2026-Q2", "qls", "actual", None, 25)
        out = self.mr.call_tool("get_quarterly_progress", {"quarter_id": "2026-Q2"})
        self.assertEqual(out["quarter_id"], "2026-Q2")
        qls = next(m for m in out["metrics"] if m["metric"] == "qls")
        self.assertEqual(qls["plan"], 100)
        self.assertEqual(qls["actual"], 25)
        self.assertEqual(qls["attainment_pct"], 25)

    def test_quarterly_progress_unknown_quarter(self):
        out = self.mr.call_tool("get_quarterly_progress",
                                {"quarter_id": "1999-Q9"})
        self.assertIn("error", out)
        self.assertIn("available", out)

    def test_use_cases_graceful_without_db(self):
        out = self.mr.call_tool("list_use_cases", {})
        self.assertEqual(out["use_cases"], [])
        self.assertIn("error", out)
        m = self.mr.call_tool("match_proof_points",
                              {"industry": "qsr", "tech_stack": ["braze"]})
        self.assertEqual(m["matches"], [])

    def test_draft_outreach_not_configured(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        out = self.mr.call_tool("draft_outreach", {
            "contact": {"name": "Marina", "email": "m@braze.com"},
            "channel": "email",
        })
        # outreach.draft returns an error payload (no raise) when no key
        self.assertEqual(out["channel"], "email")
        self.assertIn("API key", out.get("error", ""))

    def test_draft_outreach_bad_channel(self):
        out = self.mr.call_tool("draft_outreach", {
            "contact": {"name": "X"}, "channel": "fax",
        })
        self.assertIn("error", out)

    def test_draft_outreach_full_path_with_mock(self):
        os.environ["ANTHROPIC_API_KEY"] = "test"
        try:
            class _Block:
                def __init__(self, text): self.text = text
            class _Msg:
                def __init__(self, text): self.content = [_Block(text)]
            class _Messages:
                def create(self, **kwargs):
                    return _Msg("Subject: Quick hello\n\nHi Marina,\n\nLet's "
                                "talk.\n\nBen")
            class _Fake:
                def __init__(self, **kw): self.messages = _Messages()
            import anthropic
            with patch.object(anthropic, "Anthropic", _Fake):
                out = self.mr.call_tool("draft_outreach", {
                    "contact": {"name": "Marina", "email": "m@braze.com"},
                    "channel": "email", "sender_name": "Ben",
                })
            self.assertEqual(out["subject"], "Quick hello")
            self.assertIn("Marina", out["body"])
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)

    def test_log_call_writes_record(self):
        out = self.mr.call_tool("log_call", {
            "lead_id": "lead-123",
            "content": "Spoke with the VP. They want a Q3 pilot.",
            "type": "call",
            "title": "Discovery",
        })
        self.assertTrue(out["logged"])
        self.assertEqual(out["record"]["type"], "call")
        # And it persisted
        import calls_store
        calls = calls_store.list_calls("lead-123")
        self.assertEqual(len(calls), 1)

    def test_log_call_requires_content(self):
        out = self.mr.call_tool("log_call", {"lead_id": "x", "content": ""})
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()
