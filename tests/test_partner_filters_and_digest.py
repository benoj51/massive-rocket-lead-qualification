"""v0.5.4 tests — pipeline row enrichment + Slack digest partner section."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class PipelineRowEnrichmentTests(unittest.TestCase):
    """`_row_from_page` must include the new sourcing fields."""

    def test_row_includes_opportunity_source(self):
        from notion_sync import _row_from_page
        row = _row_from_page({
            "id": "p", "url": "u", "last_edited_time": "",
            "properties": {
                "Company": {"type": "title", "title": [{"plain_text": "X"}]},
                "Partner Source": {"type": "select", "select": {"name": "Braze"}},
            },
        })
        self.assertEqual(row["opportunity_source"], "Braze")

    def test_row_includes_sourced_for_partners(self):
        from notion_sync import _row_from_page
        row = _row_from_page({
            "id": "p", "url": "u", "last_edited_time": "",
            "properties": {
                "Company": {"type": "title", "title": [{"plain_text": "X"}]},
                "Sourced For": {"type": "multi_select", "multi_select": [
                    {"name": "Braze"}, {"name": "Hightouch"},
                ]},
            },
        })
        self.assertEqual(set(row["sourced_for_partners"]), {"Braze", "Hightouch"})

    def test_missing_sourcing_fields_default_safely(self):
        from notion_sync import _row_from_page
        row = _row_from_page({
            "id": "p", "url": "u", "last_edited_time": "",
            "properties": {
                "Company": {"type": "title", "title": [{"plain_text": "X"}]},
            },
        })
        self.assertEqual(row["opportunity_source"], "")
        self.assertEqual(row["sourced_for_partners"], [])


class PartnerSourcingBreakdownTests(unittest.TestCase):
    def test_aggregates_by_source(self):
        from slack_digest import partner_sourcing_breakdown
        rows = [
            {"company": "A", "opportunity_source": "Braze", "sourced_for_partners": []},
            {"company": "B", "opportunity_source": "Braze", "sourced_for_partners": []},
            {"company": "C", "opportunity_source": "Hightouch", "sourced_for_partners": []},
            {"company": "D", "opportunity_source": "", "sourced_for_partners": []},
        ]
        b = partner_sourcing_breakdown(rows)
        # Sorted by count desc
        self.assertEqual(b["by_source"][0][0], "Braze")
        self.assertEqual(b["by_source"][0][1], 2)
        self.assertEqual(b["by_source"][1][0], "Hightouch")
        self.assertEqual(b["leads_with_source"], 3)

    def test_aggregates_by_sourced_for(self):
        from slack_digest import partner_sourcing_breakdown
        rows = [
            {"company": "A", "opportunity_source": "", "sourced_for_partners": ["Braze", "Snowflake"]},
            {"company": "B", "opportunity_source": "", "sourced_for_partners": ["Braze"]},
            {"company": "C", "opportunity_source": "", "sourced_for_partners": []},
        ]
        b = partner_sourcing_breakdown(rows)
        names = {n: c for n, c, _ in b["by_sourced_for"]}
        self.assertEqual(names["Braze"], 2)
        self.assertEqual(names["Snowflake"], 1)
        self.assertEqual(b["leads_with_sourced_for"], 2)

    def test_empty_rows_returns_empty_breakdown(self):
        from slack_digest import partner_sourcing_breakdown
        b = partner_sourcing_breakdown([])
        self.assertEqual(b["by_source"], [])
        self.assertEqual(b["by_sourced_for"], [])

    def test_companies_attached_to_breakdown(self):
        from slack_digest import partner_sourcing_breakdown
        rows = [
            {"company": "Yum!", "opportunity_source": "Braze", "sourced_for_partners": []},
            {"company": "RBI", "opportunity_source": "Braze", "sourced_for_partners": []},
        ]
        b = partner_sourcing_breakdown(rows)
        _, _, companies = b["by_source"][0]
        self.assertEqual(set(companies), {"Yum!", "RBI"})


class DigestBlocksIncludeSourcingTests(unittest.TestCase):
    def test_digest_includes_partner_section_when_data_present(self):
        from slack_digest import build_digest
        rows = [
            {"company": "A", "icp_normalised": 9.0, "status": "Qualified",
             "opportunity_source": "Braze", "sourced_for_partners": ["Snowflake"]},
        ]
        payload = build_digest(pipeline_rows=rows, audit_events=[])
        flat = ""
        for b in payload["blocks"]:
            if b.get("type") == "section":
                if "text" in b:
                    flat += b["text"].get("text", "") + "\n"
                for f in b.get("fields", []):
                    flat += f.get("text", "") + "\n"
        self.assertIn("Sourced to MR by partner", flat)
        self.assertIn("Braze", flat)
        self.assertIn("MR sourcing for partners", flat)
        self.assertIn("Snowflake", flat)

    def test_digest_omits_partner_section_when_no_data(self):
        from slack_digest import build_digest
        rows = [
            {"company": "A", "icp_normalised": 9.0, "status": "Qualified",
             "opportunity_source": "", "sourced_for_partners": []},
        ]
        payload = build_digest(pipeline_rows=rows, audit_events=[])
        flat = ""
        for b in payload["blocks"]:
            if b.get("type") == "section" and "text" in b:
                flat += b["text"].get("text", "") + "\n"
        self.assertNotIn("Sourced to MR by partner", flat)
        self.assertNotIn("MR sourcing for partners", flat)


if __name__ == "__main__":
    unittest.main()
