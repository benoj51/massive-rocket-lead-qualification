"""v0.10.0v — project preview HTML rendering."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import project_preview


class RenderHtmlTests(unittest.TestCase):
    def test_minimal_snapshot_renders_doctype_and_title(self):
        html = project_preview.render_html({
            "company_name": "Acme Inc",
            "generated_at": "2026-05-21T10:00:00Z",
            "lead": {"company": "Acme Inc"},
        })
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn("Acme Inc", html)
        self.assertIn("<title>Project · Acme Inc</title>", html)
        self.assertIn("</html>", html)

    def test_summary_renders_state_of_play_and_next_action(self):
        html = project_preview.render_html({
            "company_name": "X",
            "generated_at": "2026-05-21",
            "lead": {},
            "summary": {
                "state_of_play": "Mid-discovery on a CDP build.",
                "next_action": "Book economic buyer call",
                "key_facts": ["Braze in stack", "Champion identified"],
                "open_questions": ["Budget cycle?"],
                "risks": ["No procurement engagement"],
            },
        })
        self.assertIn("Mid-discovery on a CDP build.", html)
        self.assertIn("Book economic buyer call", html)
        self.assertIn("Braze in stack", html)
        self.assertIn("Budget cycle?", html)
        self.assertIn("No procurement engagement", html)

    def test_bant_health_tiles_render_with_classes(self):
        html = project_preview.render_html({
            "company_name": "Y", "generated_at": "x", "lead": {},
            "bant_health": {
                "budget":    {"health": "red",   "caption": "No budget yet"},
                "authority": {"health": "amber", "caption": "VP confirmed"},
                "need":      {"health": "green", "caption": "Strong pain"},
                "timeline":  {"health": None,    "caption": "Not assessed"},
                "scope":     {"health": "green", "caption": "3 streams"},
            },
        })
        self.assertIn('bant-tile red', html)
        self.assertIn('bant-tile amber', html)
        self.assertIn('bant-tile green', html)
        self.assertIn('No budget yet', html)

    def test_scope_streams_render(self):
        html = project_preview.render_html({
            "company_name": "Z", "generated_at": "x", "lead": {},
            "scope": {
                "project_types": ["crm_build", "data_work"],
                "streams": [
                    {"project_type": "crm_build", "criteria": [
                        {"key": "migrating_campaigns", "label": "Campaigns to migrate",
                         "value": "120", "health": "green"},
                    ]},
                ],
            },
        })
        self.assertIn("crm build", html)  # underscores replaced
        self.assertIn("Campaigns to migrate", html)
        self.assertIn("120", html)

    def test_pricing_block_renders_totals(self):
        html = project_preview.render_html({
            "company_name": "P", "generated_at": "x", "lead": {},
            "pricing": {
                "currency": "USD", "rate_card": "MR Default", "months": 12,
                "totals": {"gross": 1191360, "net": 1112016, "discount": 79344},
                "phase_breakdown": [
                    {"phase": "Understand", "months": 3, "gross": 200000, "net": 180000},
                ],
                "team_breakdown": [
                    {"role": "Client Partner", "fte": 0.2, "gross": 50000, "net": 45000},
                ],
            },
        })
        self.assertIn("$1,191,360", html)
        self.assertIn("$1,112,016", html)
        self.assertIn("Understand", html)
        self.assertIn("Client Partner", html)

    def test_roadmap_milestones_render(self):
        html = project_preview.render_html({
            "company_name": "R", "generated_at": "x", "lead": {},
            "roadmap": {
                "start_date": "2026-06-01", "end_date": "2027-06-01",
                "milestones": [
                    {"name": "Audit", "phase": "Understand", "workstream": "CRM Strategy",
                     "start_month": 0, "length_months": 3},
                ],
                "extended_items": [
                    {"title": "Year 2 CDP expansion", "description": "Add more sources"},
                ],
            },
        })
        self.assertIn("Audit", html)
        self.assertIn("Understand", html)
        self.assertIn("CRM Strategy", html)
        self.assertIn("Year 2 CDP expansion", html)

    def test_no_data_sections_omitted(self):
        """Empty sections should NOT render their headings (keeps the doc clean)."""
        html = project_preview.render_html({
            "company_name": "Q", "generated_at": "x", "lead": {},
            "summary": None, "bant_health": None, "scope": None,
            "pricing": None, "roadmap": None,
        })
        self.assertNotIn("Pricing snapshot", html)
        self.assertNotIn("Roadmap", html)
        self.assertNotIn("BANT-S Health", html)
        # But it still produces valid HTML with the title.
        self.assertIn("<h1>", html)


if __name__ == "__main__":
    unittest.main()
