"""v1.0.0ai — SOW brief-compliance tests.

Locks in the structure mandated by the MR SOW Training Brief
(May 2026). Catches regressions where the generator drops a
required section or required clause.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class BriefStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["PROJECT_STORE_DIR"]   = os.path.join(cls.tmp, "ps")
        os.environ["CRITERIA_STORE_PATH"] = os.path.join(cls.tmp, "crit.json")
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        for mod in ("sow", "project_store", "scope", "pricing",
                     "criteria_store"):
            sys.modules.pop(mod, None)
        import project_store, scope
        p = scope.new_project("deliveroo_co_uk", "Deliveroo", ["crm_build"])
        scope.update_criterion(p, "crm_build", "migrating_campaigns",
                                 value="25", status="qualified")
        scope.update_criterion(p, "crm_build", "channels",
                                 value="Email, Push", status="qualified")
        scope.update_criterion(p, "crm_build", "html_templates_count",
                                 value="4", status="qualifying")
        scope.transition(p, "pending_validation", actor="ae1")
        scope.transition(p, "validated", actor="d1", notes="ok")
        project_store.save(p)

    @classmethod
    def tearDownClass(cls):
        for k in ("PROJECT_STORE_DIR", "CRITERIA_STORE_PATH",
                  "APOLLO_USE_FIXTURES"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _build(self, **kwargs):
        import sow
        return sow.build_snapshot("deliveroo_co_uk", **kwargs)

    # ── Naming + Document Status ────────────────────────────

    def test_naming_convention_matches_brief(self):
        snap = self._build()
        # Brief Section 2.1: Appendix A — [Client] Statement of Work — DD MMM YYYY
        self.assertRegex(
            snap["naming_convention"],
            r"^Appendix A — Deliveroo — Statement of Work — \d{2} \w{3} \d{4}$"
        )

    def test_document_status_table_present_by_default(self):
        snap = self._build()
        ds = snap.get("document_status")
        self.assertIsNotNone(ds)
        self.assertEqual(ds["status"], "Draft")
        self.assertIn("next_steps_client", ds)
        self.assertIn("next_steps_mr", ds)

    # ── Required body sections ──────────────────────────────

    def test_all_required_body_sections_present(self):
        snap = self._build()
        sec = snap["sections"]
        required = [
            "opening_clause", "timing_and_fees", "executive_summary",
            "project_timeline", "scope_of_work", "out_of_scope",
            "investment", "commercial_clauses", "project_management",
            "monitoring_progress", "companys_participation",
            "variations", "changes_of_date", "assumptions",
            "annex_1_change_order",
        ]
        for k in required:
            self.assertIn(k, sec, f"Brief mandates section: {k}")

    # ── Required clauses (verbatim per brief) ───────────────

    def test_opening_clause_references_msa_and_legal_entities(self):
        snap = self._build(msa_date="12 March 2025")
        opening = snap["sections"]["opening_clause"]
        self.assertIn("Massive Rocket Limited", opening)
        self.assertIn("Deliveroo", opening)
        self.assertIn("12 March 2025", opening)
        self.assertIn("MSA", opening)

    def test_opening_clause_placeholder_when_msa_missing(self):
        snap = self._build()  # no msa_date
        self.assertIn("[MSA DATE PENDING]", snap["sections"]["opening_clause"])

    def test_80pct_consumption_clause_present_verbatim(self):
        snap = self._build()
        clause = snap["sections"]["commercial_clauses"]["consumption_80pct"]
        self.assertIn("eighty percent (80%)", clause)
        self.assertIn("one hundred percent (100%)", clause)

    def test_contingency_clause_present(self):
        snap = self._build()
        clause = snap["sections"]["commercial_clauses"]["contingency"]
        self.assertIn("ten percent (10%) contingency", clause)
        self.assertIn("Annex 1", clause)

    def test_blended_rate_clause_uses_correct_currency(self):
        snap = self._build(currency="GBP")
        clause = snap["sections"]["commercial_clauses"]["blended_rate"]
        # Brief Section 4.3: GBP £150 / EUR €175 / USD $200 blended.
        self.assertIn("£150", clause)
        self.assertIn("GBP", clause)
        # Full rate also stated
        self.assertIn("£163", clause)

    def test_blended_rate_clause_eur_variant(self):
        snap = self._build(currency="EUR")
        self.assertIn("€175", snap["sections"]["commercial_clauses"]["blended_rate"])

    def test_blended_rate_clause_usd_variant(self):
        snap = self._build(currency="USD")
        self.assertIn("$200", snap["sections"]["commercial_clauses"]["blended_rate"])

    def test_assumptions_include_linkedin_and_licence_exclusion(self):
        snap = self._build()
        joined = "\n".join(snap["sections"]["assumptions"])
        self.assertIn("LinkedIn", joined)
        self.assertIn("software licence", joined.lower())
        self.assertIn("10%", joined)  # 10% annual increase clause

    def test_out_of_scope_includes_brief_required_items(self):
        snap = self._build()
        joined = "\n".join(snap["sections"]["out_of_scope"]).lower()
        # Brief Section 2.3 + 3.3: must include platform training,
        # creative, engineering, external documentation.
        self.assertIn("platform training", joined)
        self.assertIn("creative services", joined)
        self.assertIn("engineering", joined)
        self.assertIn("external documentation", joined)

    def test_variations_clause_references_annex_1(self):
        snap = self._build()
        self.assertIn("Annex 1", snap["sections"]["variations"])
        self.assertIn("Change Order", snap["sections"]["variations"])

    def test_annex_1_change_order_template_included(self):
        snap = self._build()
        annex = snap["sections"]["annex_1_change_order"]
        self.assertIn("Change Order", annex["title"])
        fields = dict(annex["fields"])
        for label in ("Change Order Number", "Impact — Scope",
                       "Impact — Commercials", "Acceptance"):
            self.assertIn(label, fields)

    def test_signatory_block_uses_thierry_sequeira(self):
        snap = self._build()
        sig = snap["signatory_mr"]
        self.assertEqual(sig["name"], "Thierry Sequeira")
        self.assertEqual(sig["role"], "Director")
        self.assertEqual(sig["entity"], "Massive Rocket Limited")

    # ── HTML render ─────────────────────────────────────────

    def test_html_includes_naming_convention_in_title_block(self):
        import sow
        snap = self._build()
        html = sow.render_html(snap, version=1)
        self.assertIn(snap["naming_convention"], html)

    def test_html_includes_all_section_headings(self):
        import sow
        snap = self._build()
        html = sow.render_html(snap, version=1)
        for heading in (
            "Opening Clause", "Timing &amp; Fees", "Executive Summary",
            "Project Timeline", "Services In Scope", "Services Out of Scope",
            "Commercial Summary", "Project Management",
            "Monitoring Progress", "Company&#x27;s Participation",
            "Variations &amp; Change in Scope", "Changes of Date",
            "General Notes &amp; Assumptions", "Signatures",
        ):
            self.assertIn(heading, html, f"HTML missing required heading: {heading}")

    def test_html_includes_annex_1_template(self):
        import sow
        snap = self._build()
        html = sow.render_html(snap, version=1)
        self.assertIn("Annex 1", html)
        self.assertIn("Change Order Number", html)

    def test_html_includes_compliance_side_panel(self):
        import sow
        snap = self._build()
        html = sow.render_html(snap, version=1)
        self.assertIn("sidepanel", html)
        self.assertIn("Brief compliance", html)
        self.assertIn("Pre-export checklist", html)

    def test_html_includes_thierry_sequeira_in_signatures(self):
        import sow
        snap = self._build()
        html = sow.render_html(snap, version=1)
        self.assertIn("Thierry Sequeira", html)
        self.assertIn("Director", html)


class ComplianceCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["PROJECT_STORE_DIR"]   = os.path.join(cls.tmp, "ps")
        os.environ["CRITERIA_STORE_PATH"] = os.path.join(cls.tmp, "crit.json")
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        for mod in ("sow", "project_store", "scope", "pricing",
                     "criteria_store"):
            sys.modules.pop(mod, None)
        import project_store, scope
        p = scope.new_project("deliveroo_co_uk", "Deliveroo", ["crm_build"])
        scope.update_criterion(p, "crm_build", "migrating_campaigns",
                                 value="25", status="qualified")
        scope.update_criterion(p, "crm_build", "channels",
                                 value="Email, Push", status="qualified")
        scope.update_criterion(p, "crm_build", "html_templates_count",
                                 value="4", status="qualifying")
        scope.transition(p, "pending_validation", actor="ae1")
        scope.transition(p, "validated", actor="d1", notes="ok")
        project_store.save(p)

    @classmethod
    def tearDownClass(cls):
        for k in ("PROJECT_STORE_DIR", "CRITERIA_STORE_PATH",
                  "APOLLO_USE_FIXTURES"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_compliance_block_attached_to_snapshot(self):
        import sow
        snap = sow.build_snapshot("deliveroo_co_uk")
        c = snap.get("compliance")
        self.assertIsNotNone(c)
        self.assertIn("warnings", c)
        self.assertIn("checklist", c)
        self.assertIn("passed", c)

    def test_missing_msa_date_surfaces_warning(self):
        import sow
        snap = sow.build_snapshot("deliveroo_co_uk")  # no msa_date
        codes = [w["code"] for w in snap["compliance"]["warnings"]]
        self.assertIn("opening_msa", codes)

    def test_msa_date_supplied_clears_warning(self):
        import sow
        snap = sow.build_snapshot("deliveroo_co_uk",
                                    msa_date="01 January 2025")
        codes = [w["code"] for w in snap["compliance"]["warnings"]]
        self.assertNotIn("opening_msa", codes)

    def test_missing_start_date_surfaces_warning(self):
        import sow
        snap = sow.build_snapshot("deliveroo_co_uk")
        codes = [w["code"] for w in snap["compliance"]["warnings"]]
        self.assertIn("start_date", codes)

    def test_start_date_supplied_clears_warning(self):
        import sow
        snap = sow.build_snapshot("deliveroo_co_uk",
                                    start_date="01 Jun 2026")
        codes = [w["code"] for w in snap["compliance"]["warnings"]]
        self.assertNotIn("start_date", codes)

    def test_checklist_covers_all_brief_section_5_items(self):
        import sow
        snap = sow.build_snapshot("deliveroo_co_uk",
                                    msa_date="01 January 2025",
                                    start_date="01 Jun 2026")
        items = {it["key"]: it for it in snap["compliance"]["checklist"]}
        # A representative sample from brief Section 5
        for k in ("naming", "doc_status", "opening_msa", "currency",
                   "start_date", "clause_80pct", "clause_contingency",
                   "variations", "annex_1"):
            self.assertIn(k, items)

    def test_checklist_passes_when_all_inputs_provided(self):
        import sow
        snap = sow.build_snapshot("deliveroo_co_uk",
                                    msa_date="01 January 2025",
                                    start_date="01 Jun 2026",
                                    currency="GBP")
        c = snap["compliance"]
        # All checks should pass for a well-formed snapshot
        self.assertEqual(c["passed"], c["total"],
                          f"Failed checks: {[it['key'] for it in c['checklist'] if not it['passed']]}")


class PreviewEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["PROJECT_STORE_DIR"]   = os.path.join(cls.tmp, "ps")
        os.environ["CRITERIA_STORE_PATH"] = os.path.join(cls.tmp, "crit.json")
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ["SKIP_NOTION_BOOT"]    = "1"
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        for mod in ("server", "sow", "sow_store", "project_store",
                     "scope", "pricing", "criteria_store"):
            sys.modules.pop(mod, None)
        import project_store, scope
        p = scope.new_project("deliveroo_co_uk", "Deliveroo", ["crm_build"])
        scope.update_criterion(p, "crm_build", "migrating_campaigns",
                                 value="25", status="qualified")
        scope.update_criterion(p, "crm_build", "channels",
                                 value="Email, Push", status="qualified")
        scope.transition(p, "pending_validation", actor="ae1")
        scope.transition(p, "validated", actor="d1", notes="ok")
        project_store.save(p)
        import server
        cls.server = server
        cls.client = server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("PROJECT_STORE_DIR", "CRITERIA_STORE_PATH",
                  "APOLLO_USE_FIXTURES",
                  "SKIP_NOTION_BOOT", "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_preview_renders_html_without_saving(self):
        """Dry-run preview: HTML returned but no version persisted."""
        import sow_store
        before = sow_store.list_versions("deliveroo_co_uk")
        r = self.client.post("/api/sow/deliveroo_co_uk/preview",
                              json={"months": 12})
        self.assertEqual(r.status_code, 200)
        self.assertIn("<!doctype html>", r.data.decode("utf-8"))
        after = sow_store.list_versions("deliveroo_co_uk")
        self.assertEqual(len(before), len(after),
                          "Preview must not save a version")

    def test_preview_returns_json_when_accept_header_set(self):
        r = self.client.post("/api/sow/deliveroo_co_uk/preview",
                              json={"months": 12},
                              headers={"Accept": "application/json"})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn("snapshot", body)
        self.assertIn("compliance", body)

    def test_preview_accepts_msa_and_start_date_overrides(self):
        r = self.client.post("/api/sow/deliveroo_co_uk/preview",
                              json={"msa_date": "01 March 2025",
                                    "start_date": "15 June 2026"},
                              headers={"Accept": "application/json"})
        snap = r.get_json()["snapshot"]
        self.assertIn("01 March 2025", snap["sections"]["opening_clause"])
        self.assertIn("15 June 2026", snap["sections"]["timing_and_fees"]["start_date"])

    def test_preview_unknown_lead_400(self):
        r = self.client.post("/api/sow/does_not_exist/preview", json={})
        self.assertEqual(r.status_code, 400)

    def test_compliance_endpoint_returns_warnings(self):
        r = self.client.get("/api/sow/deliveroo_co_uk/compliance")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn("warnings", body)
        self.assertIn("checklist", body)


if __name__ == "__main__":
    unittest.main()
