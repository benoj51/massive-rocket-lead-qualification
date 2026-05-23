"""v1.0.0bh — partner-sourced notes should still trigger summary synthesis.

Ben: "Added notes which were given by a partner on Shell but the notes
were not synthesised as they should be."

Root cause: the call-save handler gated `synthesise_lead` on
`extracted is not None`. When extract_from_notes returned None
(transient API error, malformed JSON, etc), the summary refresh was
silently skipped. Synthesis pulls from the FULL call history, not
the single call's extraction, so it has no dependency on that
extract succeeding.

These tests lock in the de-coupling: synthesis fires whenever AI is
configured + the call save succeeds, regardless of extraction.
"""
from __future__ import annotations

import importlib
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


class PartnerNoteSynthesisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "contacts")
        os.environ["CALLS_STORE_DIR"] = os.path.join(cls.tmp, "calls")
        os.environ["LEAD_CONTACT_NOTES_STORE_DIR"] = os.path.join(cls.tmp, "notes")
        os.environ["LEAD_SUMMARY_STORE_DIR"] = os.path.join(cls.tmp, "summary")
        os.environ["LEAD_AGENCIES_STORE_DIR"] = os.path.join(cls.tmp, "agencies")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        # Pretend AI is configured so the synthesis gate opens.
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "ai_summary", "contacts_store",
                    "calls_store", "lead_contact_notes_store",
                    "lead_summary_store", "lead_agencies_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("CONTACTS_STORE_DIR", "CALLS_STORE_DIR",
                  "LEAD_CONTACT_NOTES_STORE_DIR",
                  "LEAD_SUMMARY_STORE_DIR",
                  "LEAD_AGENCIES_STORE_DIR",
                  "SKIP_COMMAND_CENTRE_SEED",
                  "ANTHROPIC_API_KEY"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # -----------------------------------------------------------------
    # The regression case: extract returns None, synthesis should still run.
    # -----------------------------------------------------------------

    def test_synthesis_fires_when_extraction_returns_none(self):
        """The pre-fix bug: extract failed → synthesis skipped silently.
        Now: synthesis runs regardless. Confirmed by the synth mock
        being called even though extract returned None."""
        lead = "shell-bug-repro"
        synth_calls = []
        def fake_synth(ctx):
            synth_calls.append(ctx)
            return {"state_of_play": "Test summary",
                    "headline": "headline"}
        with patch.object(self.server.ai_summary, "is_configured",
                            return_value=True), \
             patch.object(self.server.ai_summary, "extract_from_notes",
                            return_value=None), \
             patch.object(self.server.ai_summary, "synthesise_lead",
                            side_effect=fake_synth), \
             patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.get_page.return_value = {
                "id": lead, "company": "Shell"}
            MockSync.return_value.update_page.return_value = {"lead": {}}
            r = self.client.post(
                f"/api/calls/{lead}",
                json={"type": "note",
                       "title": "Note from Marina at Braze",
                       "content": "She said Shell is opening their CRM RFP in Q4."})
        # Synthesis IS called even though extraction returned None.
        self.assertEqual(len(synth_calls), 1)
        body = r.get_json()
        self.assertIsNotNone(body["summary"])
        self.assertIsNone(body["summary_refresh_error"])

    def test_summary_refresh_error_surfaces_when_synth_fails(self):
        """If synth itself raises, the error makes it into the response
        so the UI can toast something honest instead of looking like
        nothing happened."""
        lead = "shell-synth-fail"
        with patch.object(self.server.ai_summary, "is_configured",
                            return_value=True), \
             patch.object(self.server.ai_summary, "extract_from_notes",
                            return_value=None), \
             patch.object(self.server.ai_summary, "synthesise_lead",
                            side_effect=RuntimeError("rate limit")), \
             patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.get_page.return_value = {
                "id": lead, "company": "Shell"}
            r = self.client.post(
                f"/api/calls/{lead}",
                json={"type": "note", "content": "partner note"})
        body = r.get_json()
        self.assertIsNone(body["summary"])
        self.assertIsNotNone(body["summary_refresh_error"])
        self.assertIn("rate limit", body["summary_refresh_error"])

    def test_summary_refresh_error_when_synth_returns_none(self):
        """If synth returns None (no exception, just no result), the
        error field tells the user to retry via Refresh."""
        lead = "shell-synth-none"
        with patch.object(self.server.ai_summary, "is_configured",
                            return_value=True), \
             patch.object(self.server.ai_summary, "extract_from_notes",
                            return_value=None), \
             patch.object(self.server.ai_summary, "synthesise_lead",
                            return_value=None), \
             patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.get_page.return_value = {
                "id": lead, "company": "Shell"}
            r = self.client.post(
                f"/api/calls/{lead}",
                json={"type": "note", "content": "partner note"})
        body = r.get_json()
        self.assertIsNone(body["summary"])
        self.assertIsNotNone(body["summary_refresh_error"])
        self.assertIn("click Refresh", body["summary_refresh_error"])

    def test_ai_off_does_not_attempt_synthesis(self):
        """When AI isn't configured at all, we don't try synthesis
        (no error toast either — the AE knows AI is off from the
        existing "AI off" banner)."""
        lead = "shell-ai-off"
        synth_calls = []
        with patch.object(self.server.ai_summary, "is_configured",
                            return_value=False), \
             patch.object(self.server.ai_summary, "synthesise_lead",
                            side_effect=lambda c: synth_calls.append(c)), \
             patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.get_page.return_value = {
                "id": lead, "company": "Shell"}
            r = self.client.post(
                f"/api/calls/{lead}",
                json={"type": "note", "content": "x"})
        self.assertEqual(synth_calls, [])  # never attempted
        body = r.get_json()
        self.assertIsNone(body["summary"])
        self.assertIsNone(body["summary_refresh_error"])

    def test_partner_source_carried_into_synthesis_context(self):
        """When the note is partner-sourced, the partner_source dict
        ends up in the synthesis context so Claude can attribute
        ('Marina at Braze told us...') correctly."""
        lead = "shell-attrib"
        captured_ctx = []
        with patch.object(self.server.ai_summary, "is_configured",
                            return_value=True), \
             patch.object(self.server.ai_summary, "extract_from_notes",
                            return_value=None), \
             patch.object(self.server.ai_summary, "synthesise_lead",
                            side_effect=lambda c: (
                                captured_ctx.append(c)
                                or {"state_of_play": "x"})), \
             patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.get_page.return_value = {
                "id": lead, "company": "Shell"}
            MockSync.return_value.update_page.return_value = {"lead": {}}
            self.client.post(
                f"/api/calls/{lead}",
                json={"type": "note", "content": "Shell Q4 RFP",
                       "partner_source": {
                           "partner_id": "braze",
                           "partner_name": "Braze",
                           "contact_id": "marina-id",
                           "contact_name": "Marina Klusas",
                       }})
        self.assertEqual(len(captured_ctx), 1)
        # The synthesis context should include this call with its
        # partner_source preserved so the prompt's attribution rubric
        # has something to work with.
        ctx_calls = captured_ctx[0].get("calls") or []
        self.assertTrue(any(
            (c.get("partner_source") or {}).get("contact_name")
                == "Marina Klusas"
            for c in ctx_calls))


if __name__ == "__main__":
    unittest.main()
