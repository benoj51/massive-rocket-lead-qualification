"""v1.0.0dq — coverage for the CLI / standalone-server modules.

These eight modules are entry points (cron runners, MCP / research / hubspot
servers, qualification CLIs) and were the only first-party files with zero
test coverage. They are not imported by the Flask app, so a syntax error or a
broken top-level import in any of them would ship silently.

This suite does two things:

1. A clean-import smoke test for all eight, so an import-time regression
   (bad syntax, missing dependency, renamed symbol) fails CI instead of only
   surfacing when someone runs the script by hand.

2. Targeted unit tests for the network-free, deterministic pure functions
   inside them — text parsers, query builders, report formatters, env checks,
   and the cron dispatch logic (with `scheduled_agents` mocked). Anything that
   reaches Apollo / Notion / Anthropic / the open web is deliberately not
   exercised here; those paths are covered behind fixtures elsewhere.
"""
from __future__ import annotations

import contextlib
import importlib
import io
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CLI_MODULES = [
    "auto_qualify",
    "qualify_lead",
    "run_scheduled",
    "mr_mcp_server",
    "research_server",
    "research",
    "diagnostics",
    "legacy_hubspot",
]


class ImportSmokeTests(unittest.TestCase):
    """Every entry-point module must import without side effects exploding.

    They are excluded from the app import graph, so this is the only guard
    against a top-level `import`/syntax/symbol regression in them.
    """

    def test_all_cli_modules_import(self):
        for name in CLI_MODULES:
            with self.subTest(module=name):
                mod = importlib.import_module(name)
                self.assertIsNotNone(mod)


# ─────────────────────────────────────────────────────────────────────────
# research.py — pure text-mining helpers
# ─────────────────────────────────────────────────────────────────────────
class ResearchPureFnTests(unittest.TestCase):
    def setUp(self):
        import research
        self.r = research

    def test_extract_domain(self):
        self.assertEqual(self.r.extract_domain(""), "")
        self.assertEqual(self.r.extract_domain("www.foo.com"), "foo.com")
        self.assertEqual(self.r.extract_domain("https://www.bar.io/path?x=1"), "bar.io")
        self.assertEqual(self.r.extract_domain("HTTP://Example.COM"), "example.com")

    def test_clean_company_name(self):
        self.assertEqual(self.r.clean_company_name("Acme Inc"), "Acme")
        self.assertEqual(self.r.clean_company_name("Acme Ltd."), "Acme")
        self.assertEqual(self.r.clean_company_name("Big Bank PLC"), "Big Bank")
        # No suffix -> untouched (besides strip).
        self.assertEqual(self.r.clean_company_name("  Deliveroo  "), "Deliveroo")

    def test_build_search_queries_uses_clean_name(self):
        q = self.r.build_search_queries("Acme Inc", "acme.com")
        self.assertEqual(
            set(q),
            {"overview", "revenue", "employees", "tech_stack", "news",
             "funding", "linkedin", "crunchbase", "industry"},
        )
        # Suffix stripped, so "Inc" should not leak into the query text.
        self.assertIn("Acme company overview", q["overview"])
        self.assertNotIn("Inc", q["overview"])

    def test_parse_revenue_from_text(self):
        self.assertEqual(self.r.parse_revenue_from_text("revenue was $5.2 billion last year"),
                         "$5.2 billion")
        self.assertIsNone(self.r.parse_revenue_from_text("no money figures here"))

    def test_parse_employee_count_from_text(self):
        self.assertEqual(self.r.parse_employee_count_from_text("about 12,000 employees worldwide"),
                         "12,000")
        self.assertEqual(self.r.parse_employee_count_from_text("a team of 50"), "50")
        self.assertIsNone(self.r.parse_employee_count_from_text("no headcount mentioned"))

    def test_identify_vertical_from_text(self):
        self.assertEqual(self.r.identify_vertical_from_text("a quick service restaurant chain"),
                         "QSR / Fast Food")
        self.assertEqual(self.r.identify_vertical_from_text("a leading neobank"), "Fintech")
        self.assertIsNone(self.r.identify_vertical_from_text("something unclassifiable"))

    def test_detect_tech_stack_from_text(self):
        found = self.r.detect_tech_stack_from_text("We run Braze and Snowflake plus BigQuery")
        self.assertEqual(set(found), {"Braze", "Snowflake", "BigQuery"})
        self.assertEqual(self.r.detect_tech_stack_from_text("no tools mentioned"), [])

    def test_detect_complexity_from_text(self):
        self.assertEqual(
            self.r.detect_complexity_from_text("a global multi-brand portfolio of brands"),
            "Multi-Brand + Multi-Market (Global)")
        self.assertEqual(self.r.detect_complexity_from_text("family of brands"), "Multi-Brand")
        self.assertEqual(self.r.detect_complexity_from_text("operates in many countries"),
                         "Multi-Market / International")
        self.assertEqual(self.r.detect_complexity_from_text("a fortune 500 enterprise"), "Enterprise")
        self.assertEqual(self.r.detect_complexity_from_text("a small local shop"), "Standard")

    def test_detect_region_from_text(self):
        self.assertEqual(self.r.detect_region_from_text("headquartered in london, united kingdom"),
                         "EMEA")
        self.assertTrue(self.r.detect_region_from_text(
            "operates across the united states and europe").startswith("Multi-Region"))
        self.assertEqual(self.r.detect_region_from_text("no geography here"), "Unknown")

    def test_aggregate_research_data(self):
        results = {
            "overview": "Acme is a global multi-brand quick service restaurant chain.",
            "revenue": "Acme posted revenue of $3.1 billion.",
            "employees": "Acme employs 25,000 staff.",
            "tech_stack": "Acme uses Braze and Segment.",
        }
        company = self.r.aggregate_research_data("Acme", "acme.com", results)
        self.assertEqual(company.name, "Acme")
        self.assertEqual(company.vertical, "QSR / Fast Food")
        self.assertIn("Braze", company.tech_stack)
        self.assertEqual(company.revenue, "$3.1 billion")
        self.assertEqual(set(company.sources), set(results.keys()))

    def test_company_data_defaults_and_to_dict(self):
        c = self.r.CompanyData(name="X", url="x.com")
        # __post_init__ replaces None list fields with [].
        self.assertEqual(c.news_highlights, [])
        self.assertEqual(c.competitors, [])
        d = c.to_dict()
        self.assertEqual(d["name"], "X")
        self.assertEqual(d["sources"], [])

    def test_format_research_report_contains_key_fields(self):
        c = self.r.CompanyData(name="Acme", url="acme.com", vertical="Retail",
                               tech_stack="Braze", sources=["overview"])
        report = self.r.format_research_report(c)
        self.assertIn("COMPANY RESEARCH REPORT", report)
        self.assertIn("Acme", report)
        self.assertIn("Retail", report)
        self.assertIn("Braze", report)

    def test_create_research_prompt_includes_queries(self):
        prompt = self.r.create_research_prompt("Acme Inc", "acme.com")
        self.assertIn("Acme Inc", prompt)
        self.assertIn("overview:", prompt)
        self.assertIn("Search queries to consider", prompt)


# ─────────────────────────────────────────────────────────────────────────
# auto_qualify.py — HTML / tech-detection pure helpers + report builders
# ─────────────────────────────────────────────────────────────────────────
def _qual_result() -> dict:
    """A fully-populated qualification result, shaped to satisfy both
    generate_analysis() and generate_html_report()."""
    def crit(value, raw, weighted, maxw):
        return {"value": value, "raw_score": raw,
                "weighted": weighted, "max_weighted": maxw}
    return {
        "company": {"name": "Acme <Co>", "url": "acme.com"},
        "data": {
            "revenue": "$3.1 billion", "employees": "25,000",
            "vertical": "Retail", "tech_stack": "Braze",
            "complexity": "Multi-Brand", "region": "EMEA",
            "description": "A retailer.",
        },
        "icp_score": {
            "score": 8,
            "weighted_total": 24, "weighted_max": 30,
            "breakdown": {
                "revenue": crit("$3.1B", 3, 9, 9),
                "vertical": crit("Retail", 2, 6, 6),
                "tech_stack": crit("Braze", 3, 6, 6),
                "complexity": crit("Multi-Brand", 1, 3, 9),
                "employees": crit("25,000", 2, 0, 0),
            },
        },
        "qualification": {
            "status": "qualify_in",
            "status_display": "QUALIFY IN",
            "hard_disqualifiers": [],
            "positive_signals": ["uses Braze"],
        },
        "analysis": {
            "fit_summary": "Strong fit.",
            "next_steps": ["Call them"],
            "stakeholder_targets": [{"role": "CMO", "priority": "High"}],
        },
        "research": {
            "sources": ["Company website (acme.com)"],
            "sources_count": 1,
            "researched_at": "2026-05-28T10:00:00",
        },
    }


class AutoQualifyPureFnTests(unittest.TestCase):
    def setUp(self):
        import auto_qualify
        self.aq = auto_qualify

    def test_detect_tech_from_website(self):
        html = '<script src="https://sdk.iad-01.braze.com/x.js"></script>' \
               '<script src="//cdn.segment.com/analytics.js"></script>'
        found = self.aq.detect_tech_from_website(html)
        self.assertIn("Braze", found)
        self.assertIn("Segment", found)
        self.assertEqual(self.aq.detect_tech_from_website("<html></html>"), [])

    def test_extract_text_from_html_strips_scripts(self):
        html = "<html><body><p>Hello</p><script>var x=1;</script></body></html>"
        text = self.aq.extract_text_from_html(html)
        self.assertIn("Hello", text)
        self.assertNotIn("var x", text)

    def test_extract_meta_info(self):
        html = ('<html><head><title>  Acme  </title>'
                '<meta name="description" content="We sell things">'
                '<meta property="og:type" content="website">'
                '</head><body></body></html>')
        meta = self.aq.extract_meta_info(html)
        self.assertEqual(meta["title"], "Acme")
        self.assertEqual(meta["description"], "We sell things")
        self.assertEqual(meta["og_type"], "website")

    def test_generate_analysis_qualify_in(self):
        analysis = self.aq.generate_analysis(_qual_result())
        self.assertIn("Strong fit", analysis["fit_summary"])
        self.assertTrue(analysis["next_steps"])
        self.assertEqual(analysis["stakeholder_targets"][0]["role"],
                         "Chief Marketing Officer (CMO)")

    def test_generate_analysis_disqualified(self):
        r = _qual_result()
        r["qualification"]["hard_disqualifiers"] = ["agency", "too small"]
        analysis = self.aq.generate_analysis(r)
        self.assertIn("Not a fit", analysis["fit_summary"])
        self.assertIn("Document disqualification reason", analysis["next_steps"])

    def test_generate_html_report_escapes_and_renders(self):
        html = self.aq.generate_html_report(_qual_result())
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        # Company name contains "<Co>" — must be HTML-escaped, not raw.
        self.assertIn("Acme &lt;Co&gt;", html)
        self.assertIn("QUALIFY IN", html)
        self.assertIn("ICP SCORE", html)


# ─────────────────────────────────────────────────────────────────────────
# qualify_lead.py — fit summary / next steps / stakeholder targets
# ─────────────────────────────────────────────────────────────────────────
class QualifyLeadPureFnTests(unittest.TestCase):
    def setUp(self):
        import qualify_lead
        self.ql = qualify_lead

    def _score(self, status, **raw):
        bd = {k: {"raw_score": v} for k, v in raw.items()}
        return {"normalized_score": 7, "status": status, "breakdown": bd}

    def test_generate_next_steps_branches(self):
        self.assertIn("Document disqualification reason",
                      self.ql.generate_next_steps("qualify_in", {}, ["dq"]))
        self.assertIn("Schedule discovery call within 48 hours",
                      self.ql.generate_next_steps("qualify_in", {}, []))
        self.assertIn("Re-score after discovery call",
                      self.ql.generate_next_steps("borderline", {}, []))
        self.assertIn("Add to nurture campaign",
                      self.ql.generate_next_steps("qualify_out", {}, []))

    def test_generate_stakeholder_targets_vertical_specific(self):
        base = self.ql.generate_stakeholder_targets({"vertical": "SaaS"})
        self.assertEqual(len(base), 5)
        retail = self.ql.generate_stakeholder_targets({"vertical": "Retail / Ecommerce"})
        self.assertTrue(any(t["role"] == "VP of E-commerce" for t in retail))
        qsr = self.ql.generate_stakeholder_targets({"vertical": "QSR / Fast Food"})
        self.assertTrue(any("Loyalty" in t["role"] for t in qsr))

    def test_generate_fit_summary_branches(self):
        dq = self.ql.generate_fit_summary({}, self._score("qualify_out"), ["agency"], [])
        self.assertIn("NOT A FIT", dq)

        strong = self.ql.generate_fit_summary(
            {}, self._score("qualify_in", revenue=3, vertical=2, tech_stack=2, complexity=2),
            [], ["signal"])
        self.assertIn("STRONG FIT", strong)
        self.assertIn("positive signal", strong)

        border = self.ql.generate_fit_summary(
            {}, self._score("borderline", revenue=1, tech_stack=1, employees=1), [], [])
        self.assertIn("BORDERLINE", border)

        weak = self.ql.generate_fit_summary({}, self._score("qualify_out"), [], [])
        self.assertIn("WEAK FIT", weak)


# ─────────────────────────────────────────────────────────────────────────
# diagnostics.py — env-driven checks (network-free in fixture mode)
# ─────────────────────────────────────────────────────────────────────────
class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        import diagnostics
        self.d = diagnostics

    def test_check_env(self):
        with mock.patch.dict("os.environ", {"DIAG_X": "value"}, clear=False):
            self.assertEqual(self.d._check_env("DIAG_X"), (True, "set"))
        with mock.patch.dict("os.environ", {"DIAG_X": ""}, clear=False):
            self.assertEqual(self.d._check_env("DIAG_X"), (False, "unset"))

    def test_check_wraps_result_and_exception(self):
        ok = self.d._check("good", True, lambda: (True, "fine"))
        self.assertEqual(ok, {"name": "good", "required": True, "ok": True, "detail": "fine"})

        def boom():
            raise ValueError("kaboom")
        bad = self.d._check("bad", False, boom)
        self.assertFalse(bad["ok"])
        self.assertTrue(bad["detail"].startswith("exception:"))

    def test_run_is_network_free_in_fixture_mode(self):
        env = {"APOLLO_USE_FIXTURES": "1", "APOLLO_API_KEY": "",
               "NOTION_API_KEY": "", "NOTION_DATA_SOURCE_ID": ""}
        with mock.patch.dict("os.environ", env, clear=False):
            report = self.d.run()
        self.assertEqual(len(report["checks"]), 9)
        # Required keys are unset, so overall must be a fail.
        self.assertFalse(report["ok"])
        apollo = next(c for c in report["checks"] if c["name"] == "Apollo live round-trip")
        self.assertTrue(apollo["ok"])
        self.assertIn("fixture mode", apollo["detail"])

    def test_main_json_returns_zero_and_emits_json(self):
        env = {"APOLLO_USE_FIXTURES": "1", "APOLLO_API_KEY": "",
               "NOTION_API_KEY": "", "NOTION_DATA_SOURCE_ID": ""}
        buf = io.StringIO()
        with mock.patch.dict("os.environ", env, clear=False), \
                contextlib.redirect_stdout(buf):
            rc = self.d.main(["--json"])
        self.assertEqual(rc, 0)  # not strict -> always 0
        payload = json.loads(buf.getvalue())
        self.assertIn("checks", payload)

    def test_main_strict_returns_one_when_required_unset(self):
        env = {"APOLLO_USE_FIXTURES": "1", "APOLLO_API_KEY": "",
               "NOTION_API_KEY": "", "NOTION_DATA_SOURCE_ID": ""}
        buf = io.StringIO()
        with mock.patch.dict("os.environ", env, clear=False), \
                contextlib.redirect_stdout(buf):
            rc = self.d.main(["--strict"])
        self.assertEqual(rc, 1)


# ─────────────────────────────────────────────────────────────────────────
# run_scheduled.py — cron dispatch (scheduled_agents mocked out)
# ─────────────────────────────────────────────────────────────────────────
class RunScheduledTests(unittest.TestCase):
    def setUp(self):
        import run_scheduled
        self.rs = run_scheduled

    def _capture(self, fn, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = fn(*args)
        return rc, buf.getvalue()

    def test_print_record_renders_status_and_tools(self):
        rec = {"ok": True, "job": "monday_digest", "kind": "digest",
               "ran_at": "2026-05-28T09:00:00Z", "message": "all good",
               "steps": [{"tool": "notion"}, {"tool": "slack"}]}
        _, out = self._capture(self.rs._print_record, rec)
        self.assertIn("[ok]", out)
        self.assertIn("monday_digest", out)
        self.assertIn("all good", out)
        self.assertIn("notion, slack", out)

    def test_run_keys_empty(self):
        rc, out = self._capture(self.rs._run_keys, [])
        self.assertEqual(rc, 0)
        self.assertIn("Nothing to run.", out)

    def test_run_keys_all_ok(self):
        ok_rec = {"ok": True, "job": "j", "kind": "digest", "ran_at": "t",
                  "message": "", "steps": []}
        with mock.patch.object(self.rs.scheduled_agents, "run_job",
                               return_value=ok_rec):
            rc, _ = self._capture(self.rs._run_keys, ["a", "b"])
        self.assertEqual(rc, 0)

    def test_run_keys_error_returns_one(self):
        with mock.patch.object(self.rs.scheduled_agents, "run_job",
                               return_value={"error": "boom"}):
            rc, out = self._capture(self.rs._run_keys, ["a"])
        self.assertEqual(rc, 1)
        self.assertIn("[ERROR]", out)

    def test_run_keys_job_not_ok_returns_one(self):
        with mock.patch.object(self.rs.scheduled_agents, "run_job",
                               return_value={"ok": False, "job": "j", "kind": "x",
                                             "ran_at": "t", "message": "", "steps": []}):
            rc, _ = self._capture(self.rs._run_keys, ["a"])
        self.assertEqual(rc, 1)

    def test_main_list(self):
        jobs = [{"key": "monday_digest", "cadence": "weekly", "kind": "digest",
                 "last_run": {"ran_at": "2026-05-20"}}]
        with mock.patch.object(self.rs.scheduled_agents, "list_jobs", return_value=jobs):
            rc, out = self._capture(self.rs.main, ["--list"])
        self.assertEqual(rc, 0)
        self.assertIn("monday_digest", out)

    def test_main_all(self):
        jobs = [{"key": "j1"}, {"key": "j2"}]
        ok_rec = {"ok": True, "job": "j", "kind": "d", "ran_at": "t",
                  "message": "", "steps": []}
        with mock.patch.object(self.rs.scheduled_agents, "list_jobs", return_value=jobs), \
                mock.patch.object(self.rs.scheduled_agents, "run_job", return_value=ok_rec):
            rc, _ = self._capture(self.rs.main, ["--all"])
        self.assertEqual(rc, 0)

    def test_main_today_no_jobs(self):
        with mock.patch.object(self.rs.scheduled_agents, "jobs_for_weekday", return_value=[]):
            rc, out = self._capture(self.rs.main, ["--today"])
        self.assertEqual(rc, 0)
        self.assertIn("No jobs scheduled", out)

    def test_main_today_with_jobs(self):
        jobs = [types.SimpleNamespace(key="due_today")]
        ok_rec = {"ok": True, "job": "due_today", "kind": "d", "ran_at": "t",
                  "message": "", "steps": []}
        with mock.patch.object(self.rs.scheduled_agents, "jobs_for_weekday", return_value=jobs), \
                mock.patch.object(self.rs.scheduled_agents, "run_job", return_value=ok_rec):
            rc, _ = self._capture(self.rs.main, ["--today"])
        self.assertEqual(rc, 0)

    def test_main_explicit_key(self):
        ok_rec = {"ok": True, "job": "k", "kind": "d", "ran_at": "t",
                  "message": "", "steps": []}
        with mock.patch.object(self.rs.scheduled_agents, "run_job",
                               return_value=ok_rec) as m:
            rc, _ = self._capture(self.rs.main, ["my_explicit_key"])
        self.assertEqual(rc, 0)
        m.assert_called_once_with("my_explicit_key", actor="cron")


if __name__ == "__main__":
    unittest.main()
