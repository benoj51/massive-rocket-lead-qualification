"""v0.5.1 tests: full 8-criterion MEDDPICC + notes + project scope flows."""
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


class QualifyPayloadShapeTests(unittest.TestCase):
    """The qualify() payload must include all 8 MEDDPICC keys + notes + scope."""

    def setUp(self):
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        for mod in ("qualify_service", "apollo", "scope"):
            sys.modules.pop(mod, None)

    def test_meddicc_has_nine_keys(self):
        # v0.10.0j: added budget_confirmed to feed the BANT-S Budget tile.
        from qualify_service import qualify
        r = qualify("Deliveroo", "deliveroo.co.uk")
        expected = {"metrics", "economic_buyer", "decision_criteria", "decision_process",
                    "paper_process", "identify_pain", "champion", "competition",
                    "budget_confirmed"}
        self.assertEqual(set(r["meddicc"].keys()), expected)

    def test_meddicc_entries_carry_health_field(self):
        from qualify_service import qualify
        r = qualify("Deliveroo", "deliveroo.co.uk")
        for k, entry in r["meddicc"].items():
            self.assertIn("health", entry, f"{k} missing health field")
            self.assertIsNone(entry["health"])  # null by default

    def test_qualify_result_includes_bant_health(self):
        from qualify_service import qualify
        r = qualify("Deliveroo", "deliveroo.co.uk")
        self.assertIn("bant_health", r)
        for tile in ("budget", "authority", "need", "timeline", "scope"):
            self.assertIn(tile, r["bant_health"])
            self.assertIn("health", r["bant_health"][tile])
            self.assertIn("caption", r["bant_health"][tile])

    def test_payload_includes_notes_and_scope(self):
        from qualify_service import qualify
        r = qualify("Deliveroo", "deliveroo.co.uk")
        self.assertIn("notes", r)
        self.assertIn("project_scope", r)
        # Defaults are empty strings (UI fills in later)
        self.assertEqual(r["notes"], "")
        self.assertEqual(r["project_scope"], "")


class NotionPageBlocksTests(unittest.TestCase):
    """MEDDPICC blocks include all 8 fields; notes + scope appear when set."""

    def test_meddpicc_blocks_render_all_eight(self):
        from notion_sync import _meddicc_blocks
        payload = {"meddicc": {
            "metrics": {"value": "5% revenue lift", "status": "confirmed"},
            "economic_buyer": {"value": "Jane CFO", "status": "in_progress"},
            "decision_criteria": {"value": "TBC", "status": "in_progress"},
            "decision_process": {"value": "RFP -> shortlist -> POC", "status": "in_progress"},
            "paper_process": {"value": "Legal takes ~6 weeks", "status": "in_progress"},
            "identify_pain": {"value": "Email open rates flat", "status": "confirmed"},
            "champion": {"value": "Mark CRM Lead", "status": "confirmed"},
            "competition": {"value": "Iterable, Mover", "status": "in_progress"},
        }}
        blocks = _meddicc_blocks(payload)
        # heading + 8 bullets
        self.assertEqual(len(blocks), 9)
        self.assertEqual(blocks[0]["type"], "heading_3")
        bullets = blocks[1:]
        text_blob = " ".join(
            "".join(t["text"]["content"] for t in b["bulleted_list_item"]["rich_text"])
            for b in bullets
        )
        for label in ("Metrics", "Economic Buyer", "Decision Criteria", "Decision Process",
                      "Paper Process", "Identify Pain", "Champion", "Competition"):
            self.assertIn(label, text_blob)

    def test_notes_and_scope_appear_in_page_blocks(self):
        from notion_sync import _page_blocks
        payload = {
            "company": {"name": "X", "url": "x.com"},
            "score": {"normalized_score": 8.0, "status": "qualify_in",
                      "status_display": "QUALIFY IN", "opportunity_label": "Retention",
                      "breakdown": {}},
            "fit_summary": "",
            "next_steps": [],
            "stakeholders": [],
            "meddicc": {},
            "notes": "Paragraph one.\n\nParagraph two.",
            "project_scope": "Migrate 25 campaigns to Braze.",
        }
        blocks = _page_blocks(payload)
        text_blob = ""
        for b in blocks:
            for content_block in b.values():
                if isinstance(content_block, dict):
                    for t in content_block.get("rich_text", []) or []:
                        text_blob += t.get("text", {}).get("content", "")
        self.assertIn("Project Scope", text_blob)
        self.assertIn("Migrate 25 campaigns to Braze", text_blob)
        self.assertIn("Notes & Transcript", text_blob)
        self.assertIn("Paragraph one", text_blob)
        self.assertIn("Paragraph two", text_blob)

    def test_meddpicc_score_column_caps_at_six_criteria(self):
        """Notion DB only has 6 score columns; we don't try to write the new 2 as cols."""
        from notion_sync import _payload_to_properties
        payload = {
            "company": {"name": "X", "url": "x.com"},
            "score": {"status": "qualify_in", "status_display": "QUALIFY IN",
                      "total_weighted": 0, "normalized_score": 0,
                      "opportunity_type": "retention", "breakdown": {}},
            "discovered": {},
            "opportunity": {"type": "retention"},
            "meddicc": {
                "paper_process": {"value": "x", "status": "confirmed"},
                "competition": {"value": "x", "status": "confirmed"},
            },
        }
        props = _payload_to_properties(payload)
        # New criteria must NOT be written as columns (Notion would reject)
        self.assertNotIn("Paper Process", props)
        self.assertNotIn("Competition", props)
        # Original 6 still present
        for col in ("Metrics", "Economic Buyer", "Decision Criteria",
                    "Decision Process", "Identify Pain", "Champion"):
            self.assertIn(col, props)


class TextChunkingTests(unittest.TestCase):
    def test_short_text_single_chunk(self):
        from notion_sync import _chunk_text
        self.assertEqual(_chunk_text("short", 100), ["short"])

    def test_paragraph_splitting(self):
        from notion_sync import _chunk_text
        text = "a" * 500 + "\n\n" + "b" * 500 + "\n\n" + "c" * 500
        chunks = _chunk_text(text, 700)
        # Each chunk should respect the size cap
        for c in chunks:
            self.assertLessEqual(len(c), 700)

    def test_single_long_paragraph_hard_cut(self):
        from notion_sync import _chunk_text
        chunks = _chunk_text("x" * 5000, 1000)
        for c in chunks:
            self.assertLessEqual(len(c), 1000)
        self.assertEqual(sum(len(c) for c in chunks), 5000)


class ExtractEndpointTests(unittest.TestCase):
    """The /api/lead/extract endpoint contract — without hitting Anthropic."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        for mod in ("server", "ai_summary"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_extract_requires_notes(self):
        r = self.client.post("/api/lead/extract", json={})
        self.assertEqual(r.status_code, 400)

    def test_extract_503_without_anthropic_key(self):
        r = self.client.post("/api/lead/extract",
                             json={"notes": "Sample call notes go here."})
        self.assertEqual(r.status_code, 503)
        self.assertIn("ANTHROPIC_API_KEY", r.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
