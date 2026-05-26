"""v1.0.0bb — call notes extract competitive agencies + tech stack
and auto-link them to the account.

Ben: "Notes should also be able to pick up on competitive agencies
or tech stack mentioned to be added to the respective account."

Three layers tested:
1. ai_summary.extract_from_notes parses the two new schema fields
   correctly (dedup, validation, generic-filter).
2. calls_store.aggregate_extractions rolls them up across calls
   with mention counts + call provenance.
3. End-to-end via the call POST endpoint: agencies land in
   lead_agencies_store as type=competitor with source=call_extracted;
   tech stack appends to the lead's Notion `tech_stack` field via
   the (patched) NotionSync.
"""
from __future__ import annotations

import importlib
import json
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


# -----------------------------------------------------------------
# Layer 1: extraction parser
# -----------------------------------------------------------------

class ExtractFromNotesTests(unittest.TestCase):
    """Patches the Anthropic SDK at the import-site level so
    extract_from_notes' parser branch is exercised end-to-end without
    a real LLM call."""

    def setUp(self):
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        sys.modules.pop("ai_summary", None)
        import ai_summary
        self.ai = ai_summary

    def tearDown(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)

    def _run_with_response(self, payload: dict):
        """Invoke extract_from_notes with the Anthropic SDK stubbed
        to return `payload` as the JSON body."""
        # Build a fake response object matching what `client.messages.create`
        # returns: an object with `content` = [block-with-text].
        class _Block:
            def __init__(self, text):
                self.text = text
        class _Msg:
            def __init__(self, text):
                self.content = [_Block(text)]
        class _Messages:
            def create(self, **kwargs):
                return _Msg(json.dumps(payload))
        class _FakeAnthropic:
            def __init__(self, **kwargs):
                self.messages = _Messages()
        # The function does `from anthropic import Anthropic` inside the
        # body — we patch the imported symbol on the anthropic module
        # itself so the local import picks up our fake.
        import anthropic
        with patch.object(anthropic, "Anthropic", _FakeAnthropic):
            return self.ai.extract_from_notes("call notes",
                                                 company_name="X")

    def test_parses_competitive_agencies(self):
        out = self._run_with_response({
            "competitive_agencies": [
                {"name": "WPP", "context": "current incumbent"},
                {"name": "Razorfish", "context": "previously evaluated"},
            ],
            "tech_stack_mentioned": [],
            "meddpicc": {}, "contacts_mentioned": [],
        })
        self.assertEqual(len(out["competitive_agencies"]), 2)
        names = {a["name"] for a in out["competitive_agencies"]}
        self.assertEqual(names, {"WPP", "Razorfish"})
        contexts = {a["context"] for a in out["competitive_agencies"]}
        self.assertIn("current incumbent", contexts)

    def test_dedupes_agency_names_within_call(self):
        """Same agency mentioned twice (different case) → one entry."""
        out = self._run_with_response({
            "competitive_agencies": [
                {"name": "WPP", "context": "current incumbent"},
                {"name": "wpp", "context": "previously evaluated"},
            ],
            "meddpicc": {}, "contacts_mentioned": [],
            "tech_stack_mentioned": [],
        })
        self.assertEqual(len(out["competitive_agencies"]), 1)

    def test_invalid_agency_context_normalises_to_none(self):
        out = self._run_with_response({
            "competitive_agencies": [
                {"name": "WPP", "context": "we lost the pitch lol"},
            ],
            "meddpicc": {}, "contacts_mentioned": [],
            "tech_stack_mentioned": [],
        })
        self.assertIsNone(out["competitive_agencies"][0]["context"])

    def test_filters_generic_tech_mentions(self):
        out = self._run_with_response({
            "tech_stack_mentioned": ["Braze", "a CDP", "their CRM",
                                       "Snowflake", "Snowflake"],
            "meddpicc": {}, "contacts_mentioned": [],
            "competitive_agencies": [],
        })
        # Dedup + generic filter: just Braze + Snowflake.
        self.assertEqual(sorted(out["tech_stack_mentioned"]),
                         ["Braze", "Snowflake"])

    def test_skips_null_and_empty_tech_entries(self):
        out = self._run_with_response({
            "tech_stack_mentioned": ["", None, "null", "Braze"],
            "meddpicc": {}, "contacts_mentioned": [],
            "competitive_agencies": [],
        })
        self.assertEqual(out["tech_stack_mentioned"], ["Braze"])

    # v1.0.0cq: sourcing-partner exclusion ---------------------------
    # When the AE marks a lead as "sourced via Braze", the AI extractor
    # used to drop Braze into the lead's tech_stack even though the
    # partner is the REFERRER, not necessarily in the prospect's stack.
    # The fix excludes any sourcing_partners name from the returned
    # tech_stack post-hoc.

    def _run_with_sourcing(self, payload, sourcing_partners):
        class _Block:
            def __init__(self, text): self.text = text
        class _Msg:
            def __init__(self, text): self.content = [_Block(text)]
        class _Messages:
            def create(self, **kwargs): return _Msg(json.dumps(payload))
        class _FakeAnthropic:
            def __init__(self, **kwargs): self.messages = _Messages()
        import anthropic
        with patch.object(anthropic, "Anthropic", _FakeAnthropic):
            return self.ai.extract_from_notes(
                "Sourced via Marina at Braze. They use Snowflake.",
                company_name="X",
                sourcing_partners=sourcing_partners,
            )

    def test_sourcing_partner_excluded_from_tech_stack(self):
        """Braze listed as sourcing partner -> stripped from tech_stack
        even if the model returned it."""
        out = self._run_with_sourcing({
            "tech_stack_mentioned": ["Braze", "Snowflake"],
            "meddpicc": {}, "contacts_mentioned": [],
            "competitive_agencies": [],
        }, sourcing_partners=["Braze"])
        self.assertEqual(out["tech_stack_mentioned"], ["Snowflake"])

    def test_sourcing_partner_case_insensitive_match(self):
        """Match is case-insensitive: 'Braze' filter strips 'braze'."""
        out = self._run_with_sourcing({
            "tech_stack_mentioned": ["braze", "Snowflake"],
            "meddpicc": {}, "contacts_mentioned": [],
            "competitive_agencies": [],
        }, sourcing_partners=["Braze"])
        self.assertEqual(out["tech_stack_mentioned"], ["Snowflake"])

    def test_no_sourcing_partner_no_filter(self):
        """Without sourcing_partners, behaviour is unchanged."""
        out = self._run_with_sourcing({
            "tech_stack_mentioned": ["Braze", "Snowflake"],
            "meddpicc": {}, "contacts_mentioned": [],
            "competitive_agencies": [],
        }, sourcing_partners=None)
        self.assertEqual(sorted(out["tech_stack_mentioned"]),
                          ["Braze", "Snowflake"])

    def test_multiple_sourcing_partners_all_excluded(self):
        out = self._run_with_sourcing({
            "tech_stack_mentioned": ["Braze", "mParticle", "Snowflake"],
            "meddpicc": {}, "contacts_mentioned": [],
            "competitive_agencies": [],
        }, sourcing_partners=["Braze", "mParticle"])
        self.assertEqual(out["tech_stack_mentioned"], ["Snowflake"])

    # v1.0.0bg: contacts_mentioned single-word filter -----------------

    def test_drops_single_word_contacts_without_email(self):
        """An AI-extracted contact like {name:'Sarah'} with no email
        is dropped — half-named contacts create cleanup work."""
        out = self._run_with_response({
            "meddpicc": {},
            "tech_stack_mentioned": [],
            "competitive_agencies": [],
            "contacts_mentioned": [
                {"name": "Sarah", "role": "prospect-side"},
                {"name": "John Doe", "role": "prospect-side"},
            ],
        })
        names = [c["name"] for c in out["contacts_mentioned"]]
        self.assertNotIn("Sarah", names)
        self.assertIn("John Doe", names)

    def test_keeps_single_word_contact_when_email_present(self):
        """A single-name + email pair is kept — the email gives the AE
        enough to disambiguate even without a surname."""
        out = self._run_with_response({
            "meddpicc": {},
            "tech_stack_mentioned": [],
            "competitive_agencies": [],
            "contacts_mentioned": [
                {"name": "Sarah", "email": "sarah@acme.com",
                 "role": "prospect-side"},
            ],
        })
        self.assertEqual(len(out["contacts_mentioned"]), 1)
        self.assertEqual(out["contacts_mentioned"][0]["name"], "Sarah")
        self.assertEqual(out["contacts_mentioned"][0]["email"],
                          "sarah@acme.com")


# -----------------------------------------------------------------
# Layer 2: aggregate_extractions rollup
# -----------------------------------------------------------------

class AggregateExtractionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["CALLS_STORE_DIR"] = self.tmp
        sys.modules.pop("calls_store", None)
        import calls_store
        self.store = calls_store

    def tearDown(self):
        os.environ.pop("CALLS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tech_stack_and_agencies_rolled_up_with_counts(self):
        lead = "acme"
        # Call 1: mentions Braze + WPP
        self.store.add_call(lead, {
            "type": "discovery", "title": "Disco 1",
            "content": "they use Braze, WPP is incumbent",
            "extracted": {
                "tech_stack_mentioned": ["Braze"],
                "competitive_agencies": [
                    {"name": "WPP", "context": "current incumbent"},
                ],
            },
        })
        # Call 2: re-mentions Braze + adds Snowflake + Razorfish
        self.store.add_call(lead, {
            "type": "discovery", "title": "Disco 2",
            "content": "still on Braze; using Snowflake; pitching Razorfish",
            "extracted": {
                "tech_stack_mentioned": ["Braze", "Snowflake"],
                "competitive_agencies": [
                    {"name": "Razorfish",
                     "context": "pitching against mr"},
                ],
            },
        })
        agg = self.store.aggregate_extractions(lead)
        # Tech stack — 3 unique names, Braze mentioned twice.
        tech_by_name = {t["name"]: t for t in agg["tech_stack_mentioned"]}
        self.assertEqual(tech_by_name["Braze"]["mentions"], 2)
        self.assertEqual(tech_by_name["Snowflake"]["mentions"], 1)
        # call_ids populated per entry.
        self.assertEqual(len(tech_by_name["Braze"]["call_ids"]), 2)
        # Agencies — 2 unique.
        ag_by_name = {a["name"]: a for a in agg["competitive_agencies"]}
        self.assertIn("WPP", ag_by_name)
        self.assertIn("Razorfish", ag_by_name)

    def test_empty_extraction_returns_empty_rollups(self):
        self.store.add_call("acme", {
            "type": "note", "title": "x", "content": "blah",
            "extracted": {"meddpicc": {}},
        })
        agg = self.store.aggregate_extractions("acme")
        self.assertEqual(agg["tech_stack_mentioned"], [])
        self.assertEqual(agg["competitive_agencies"], [])


# -----------------------------------------------------------------
# Layer 3: end-to-end via the call POST endpoint
# -----------------------------------------------------------------

class CallSaveAutoLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "contacts")
        os.environ["CALLS_STORE_DIR"] = os.path.join(cls.tmp, "calls")
        os.environ["LEAD_AGENCIES_STORE_DIR"] = os.path.join(cls.tmp, "agencies")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "contacts_store", "calls_store",
                    "ai_summary", "lead_agencies_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("CONTACTS_STORE_DIR", "CALLS_STORE_DIR",
                  "LEAD_AGENCIES_STORE_DIR",
                  "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        # Wipe agencies + calls per test for isolation.
        for sub in ("calls", "agencies"):
            d = Path(self.tmp) / sub
            if d.exists():
                shutil.rmtree(d)

    def test_agencies_auto_added_on_call_save(self):
        """POST /api/calls/<lead> with extracted.competitive_agencies →
        agencies land in lead_agencies_store as type=competitor with
        source=call_extracted + the source_call_id."""
        lead = "acme-auto"
        with patch.object(self.server.ai_summary, "is_configured",
                            return_value=True), \
             patch.object(self.server.ai_summary, "extract_from_notes",
                            return_value={
                                "competitive_agencies": [
                                    {"name": "WPP",
                                     "context": "current incumbent"},
                                    {"name": "Razorfish",
                                     "context": "previously evaluated"},
                                ],
                                "tech_stack_mentioned": [],
                                "meddpicc": {},
                                "contacts_mentioned": [],
                            }), \
             patch.object(self.server.ai_summary, "synthesise_lead",
                            return_value=None), \
             patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.get_page.return_value = {
                "id": lead, "company": "Acme", "tech_stack": "",
            }
            MockSync.return_value.update_page.return_value = {"lead": {}}
            r = self.client.post(
                f"/api/calls/{lead}",
                json={"type": "discovery", "title": "Disco",
                       "content": "WPP is incumbent. Razorfish pitched."})
        body = r.get_json()
        self.assertEqual(len(body["agencies_auto_added"]), 2)
        # Verify persistence.
        import lead_agencies_store
        rows = lead_agencies_store.list_agencies(lead)
        names = {a["name"]: a for a in rows}
        self.assertIn("WPP", names)
        self.assertEqual(names["WPP"]["type"],
                          lead_agencies_store.TYPE_COMPETITOR)
        self.assertEqual(names["WPP"]["source"], "call_extracted")
        # Razorfish flagged "previously evaluated" → type=previous.
        self.assertEqual(names["Razorfish"]["type"],
                          lead_agencies_store.TYPE_PREVIOUS)

    def test_agency_already_present_not_duplicated(self):
        """If an agency with the same case-insensitive name already
        exists on the lead, the auto-link skips it (no dupes)."""
        lead = "acme-existing"
        import lead_agencies_store
        lead_agencies_store.save_agency(lead, {
            "name": "WPP",
            "type": lead_agencies_store.TYPE_INCUMBENT,
        })
        with patch.object(self.server.ai_summary, "is_configured",
                            return_value=True), \
             patch.object(self.server.ai_summary, "extract_from_notes",
                            return_value={
                                "competitive_agencies": [
                                    {"name": "wpp",
                                     "context": "current incumbent"},
                                ],
                                "tech_stack_mentioned": [],
                                "meddpicc": {},
                                "contacts_mentioned": [],
                            }), \
             patch.object(self.server.ai_summary, "synthesise_lead",
                            return_value=None), \
             patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.get_page.return_value = {
                "id": lead, "tech_stack": "",
            }
            MockSync.return_value.update_page.return_value = {"lead": {}}
            r = self.client.post(
                f"/api/calls/{lead}",
                json={"type": "note", "content": "wpp still on it"})
        body = r.get_json()
        self.assertEqual(body["agencies_auto_added"], [])
        # Only one WPP row exists (the original incumbent, not a duplicated
        # competitor).
        rows = lead_agencies_store.list_agencies(lead)
        wpp_rows = [r for r in rows if r["name"].lower() == "wpp"]
        self.assertEqual(len(wpp_rows), 1)
        self.assertEqual(wpp_rows[0]["type"],
                          lead_agencies_store.TYPE_INCUMBENT)

    def test_tech_stack_auto_merged_into_lead(self):
        """Tech stack mentions append to the lead's Notion tech_stack
        field via NotionSync.update_page. Dedup against existing
        comma-separated entries (case-insensitive)."""
        lead = "acme-tech"
        update_calls = []
        with patch.object(self.server.ai_summary, "is_configured",
                            return_value=True), \
             patch.object(self.server.ai_summary, "extract_from_notes",
                            return_value={
                                "tech_stack_mentioned":
                                    ["Braze", "Snowflake", "iterable"],
                                "competitive_agencies": [],
                                "meddpicc": {},
                                "contacts_mentioned": [],
                            }), \
             patch.object(self.server.ai_summary, "synthesise_lead",
                            return_value=None), \
             patch.object(self.server, "NotionSync") as MockSync:
            inst = MockSync.return_value
            # Lead already has Braze + Iterable in its tech_stack;
            # auto-merge should only append Snowflake.
            inst.get_page.return_value = {
                "id": lead, "tech_stack": "Braze, Iterable",
            }
            inst.update_page.side_effect = lambda lid, edits: (
                update_calls.append({"lid": lid, "edits": edits})
                or {"lead": {}})
            r = self.client.post(
                f"/api/calls/{lead}",
                json={"type": "discovery",
                       "content": "still on Braze + Iterable; "
                                   "Snowflake is the warehouse"})
        body = r.get_json()
        # Only Snowflake was new (case-insensitive dedup against existing).
        self.assertEqual(body["tech_stack_appended"], ["Snowflake"])
        # update_page was called with the merged tech_stack value.
        tech_patch = next(c for c in update_calls
                            if "tech_stack" in c["edits"])
        self.assertEqual(tech_patch["edits"]["tech_stack"],
                          "Braze, Iterable, Snowflake")

    def test_tech_stack_empty_field_initialises(self):
        """When the lead's tech_stack is empty, the merged value is just
        the new tools comma-joined (no stray leading comma)."""
        lead = "acme-empty-tech"
        update_calls = []
        with patch.object(self.server.ai_summary, "is_configured",
                            return_value=True), \
             patch.object(self.server.ai_summary, "extract_from_notes",
                            return_value={
                                "tech_stack_mentioned": ["Braze"],
                                "competitive_agencies": [],
                                "meddpicc": {},
                                "contacts_mentioned": [],
                            }), \
             patch.object(self.server.ai_summary, "synthesise_lead",
                            return_value=None), \
             patch.object(self.server, "NotionSync") as MockSync:
            inst = MockSync.return_value
            inst.get_page.return_value = {"id": lead, "tech_stack": ""}
            inst.update_page.side_effect = lambda lid, edits: (
                update_calls.append({"edits": edits}) or {"lead": {}})
            self.client.post(
                f"/api/calls/{lead}",
                json={"type": "note", "content": "Braze"})
        tech_patch = next(c for c in update_calls
                            if "tech_stack" in c["edits"])
        self.assertEqual(tech_patch["edits"]["tech_stack"], "Braze")


if __name__ == "__main__":
    unittest.main()
