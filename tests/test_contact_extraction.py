"""v1.0.0f (Tier 3c) — AI contact extraction from call notes.

When a transcript names people, the extract pipeline returns them as
`contacts_mentioned`, and the server dedupes against existing lead
contacts before surfacing suggestions in the UI.
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


class ExtractPromptShapeTests(unittest.TestCase):
    """The prompt schema must instruct Claude about contacts_mentioned
    + the role enum."""

    def setUp(self):
        for mod in ("ai_summary",):
            sys.modules.pop(mod, None)

    def test_prompt_documents_contacts_mentioned(self):
        import ai_summary
        prompt = ai_summary._EXTRACT_SYSTEM_PROMPT
        self.assertIn("contacts_mentioned", prompt)
        # Role enum present
        for role in ("prospect-side", "mr-side", "partner-side", "unknown"):
            self.assertIn(role, prompt)


class CallAddSuggestionsTests(unittest.TestCase):
    """The /api/calls/<id> POST returns `contact_suggestions` filtered
    against existing contacts + role."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "contacts")
        os.environ["CALLS_STORE_DIR"] = os.path.join(cls.tmp, "calls")
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        for mod in ("server", "contacts_store", "calls_store", "ai_summary"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("CONTACTS_STORE_DIR", None)
        os.environ.pop("CALLS_STORE_DIR", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _post_call_with_extracted_contacts(self, lead_id: str, mentioned: list[dict]):
        """Patch extract_from_notes so the AE flow gets a deterministic
        AI response — we're testing the server's downstream dedupe +
        filter logic, not Claude itself."""
        fake_extract = {
            "meddpicc": {},
            "synthesised_note": "Headline\nWhat we heard\n",
            "scope_criteria": {},
            "contacts_mentioned": mentioned,
        }
        with patch.object(self.server.ai_summary, "is_configured", return_value=True):
            with patch.object(self.server.ai_summary, "extract_from_notes",
                              return_value=fake_extract):
                # synthesise_lead also gets called inline — stub it to None
                # so the endpoint doesn't try to reach Claude for the summary.
                with patch.object(self.server.ai_summary, "synthesise_lead",
                                  return_value=None):
                    return self.client.post(
                        f"/api/calls/{lead_id}",
                        json={"type": "call", "content": "fake transcript"},
                    )

    def test_suggestions_returned_for_new_prospect_contacts(self):
        r = self._post_call_with_extracted_contacts("sugg-1", [
            {"name": "Jane Doe", "title": "VP Marketing", "role": "prospect-side"},
            {"name": "Tom Lee", "title": "Director Lifecycle", "role": "unknown"},
        ])
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        suggestions = body.get("contact_suggestions") or []
        names = {s["name"] for s in suggestions}
        self.assertEqual(names, {"Jane Doe", "Tom Lee"})

    def test_mr_side_contacts_filtered_out(self):
        """MR-side people (own team) should never be suggested as lead
        contacts."""
        r = self._post_call_with_extracted_contacts("sugg-2", [
            {"name": "Ben Ojuolape", "title": "Head of Partnerships",
             "role": "mr-side"},
            {"name": "Jane Doe", "title": "VP Marketing",
             "role": "prospect-side"},
        ])
        body = r.get_json()
        names = {s["name"] for s in body.get("contact_suggestions") or []}
        self.assertEqual(names, {"Jane Doe"})

    def test_partner_side_contacts_filtered_out(self):
        """Partner-side people (Braze AE etc.) belong in partner contacts,
        not lead contacts. Filter them out from suggestions."""
        r = self._post_call_with_extracted_contacts("sugg-3", [
            {"name": "Marina Klusas", "title": "Strategic AE @ Braze",
             "role": "partner-side"},
            {"name": "Jane Doe", "title": "VP Marketing",
             "role": "prospect-side"},
        ])
        names = {s["name"] for s in r.get_json().get("contact_suggestions") or []}
        self.assertEqual(names, {"Jane Doe"})

    def test_existing_lead_contacts_deduped_by_name(self):
        """A name already saved as a lead contact shouldn't re-appear in
        suggestions."""
        import contacts_store
        contacts_store.save_contact("dedupe", {"name": "Already Here"})
        r = self._post_call_with_extracted_contacts("dedupe", [
            {"name": "Already Here", "role": "prospect-side"},
            {"name": "New Person", "role": "prospect-side"},
        ])
        names = {s["name"] for s in r.get_json().get("contact_suggestions") or []}
        self.assertEqual(names, {"New Person"})

    def test_dedupe_case_insensitive(self):
        import contacts_store
        contacts_store.save_contact("ci-dedupe", {"name": "Jane Doe"})
        r = self._post_call_with_extracted_contacts("ci-dedupe", [
            {"name": "JANE DOE", "role": "prospect-side"},
            {"name": "Other Person", "role": "prospect-side"},
        ])
        names = {s["name"] for s in r.get_json().get("contact_suggestions") or []}
        # Jane (any case) should not surface
        self.assertEqual(names, {"Other Person"})


class SeedScriptTests(unittest.TestCase):
    """The Command Centre seed script is idempotent + creates the
    expected Braze records with the right hierarchy/tags."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["PARTNERS_STORE_PATH"] = os.path.join(self.tmp, "p.json")
        os.environ["PARTNER_CONTACTS_STORE_DIR"] = os.path.join(self.tmp, "pc")
        for mod in ("partners_store", "partner_contacts_store",
                    "seed_command_centre_partners", "project_store"):
            sys.modules.pop(mod, None)

    def tearDown(self):
        for k in ("PARTNERS_STORE_PATH", "PARTNER_CONTACTS_STORE_DIR"):
            os.environ.pop(k, None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_seed_creates_braze_and_hightouch_partners(self):
        import seed_command_centre_partners as seed
        summary = seed.seed()
        partner_names = {p["name"] for p in summary["partners_seeded"]}
        self.assertEqual(partner_names, {"Braze", "Hightouch"})

    def test_seed_creates_braze_contacts(self):
        """v1.0.0h: seed expanded from the original 2-contact stub to the
        full Braze AMER + EMEA + Partner-org roster. Spot-check that the
        original priority names still land + the roster has the bulk
        we'd expect."""
        import seed_command_centre_partners as seed
        import partner_contacts_store
        seed.seed()
        braze = partner_contacts_store.list_contacts("braze")
        names = {c["name"] for c in braze}
        # The original two priority contacts must still be present.
        self.assertIn("Glenn Bonforte", names)
        self.assertIn("Marina Klusas", names)
        # And a sampling of the newly-added leadership + AEs.
        for must_have in ("Eric Sanders", "Marlon Hills", "Stephanie Chang",
                          "William Thomas", "Eleanor Wolf", "Katie Cornwell"):
            self.assertIn(must_have, names, f"missing {must_have} from roster")
        # Roster should be in the comprehensive range, not the old 2.
        self.assertGreater(len(braze), 100,
                            f"Roster looks too thin ({len(braze)} contacts) — "
                            f"expected the full Command Centre seed")

    def test_seed_respects_tag_lists(self):
        """Every contact carries command_centre_seed; MR-priority names
        carry mr_priority + tighter cadence; inferred emails carry
        email_inferred."""
        import seed_command_centre_partners as seed
        import partner_contacts_store
        seed.seed()
        braze = partner_contacts_store.list_contacts("braze")
        for c in braze:
            self.assertIn("command_centre_seed", c.get("tags", []),
                          f"{c['name']} missing command_centre_seed tag")
        # MR-priority spot-check: Marina is on Ben's priority list.
        marina = next(c for c in braze if c["name"] == "Marina Klusas")
        self.assertIn("mr_priority", marina["tags"])
        self.assertEqual(marina["cadence_days"], 14)
        self.assertEqual(marina["email"], "Marina.Klusas@braze.com")
        # Email-override exception: Emmanouela uses the e.androulaki form.
        em = next(c for c in braze if c["name"] == "Emmanouela Androulaki")
        self.assertEqual(em["email"], "e.androulaki@braze.com")
        self.assertNotIn("email_inferred", em["tags"])

    def test_seed_idempotent(self):
        """Re-running upserts by stable id rather than duplicating rows."""
        import seed_command_centre_partners as seed
        import partner_contacts_store
        seed.seed()
        first_count = len(partner_contacts_store.list_contacts("braze"))
        seed.seed()
        second_count = len(partner_contacts_store.list_contacts("braze"))
        self.assertEqual(first_count, second_count,
                          "Re-running seed duplicated rows — id stability broke")

    def test_seed_creates_hightouch_partner_with_full_roster(self):
        """v1.0.0h: Hightouch now has its full NA Sales roster seeded
        too, with all emails inferred (no explicit emails supplied)."""
        import seed_command_centre_partners as seed
        import partner_contacts_store, partners_store
        seed.seed()
        self.assertIsNotNone(partners_store.get_partner("hightouch"))
        ht = partner_contacts_store.list_contacts("hightouch")
        names = {c["name"] for c in ht}
        # Roots: Vinod + John must be present.
        self.assertIn("Vinod Venkatasubramaniam", names)
        self.assertIn("John Knudsen", names)
        # All Hightouch emails should be inferred since no overrides given.
        for c in ht:
            self.assertIn("email_inferred", c.get("tags", []),
                          f"{c['name']} should be flagged email_inferred")
            self.assertTrue(c["email"].endswith("@hightouch.com"))

    def test_seed_hierarchy_intact(self):
        """Every reports_to_id should resolve to a real contact in the
        same partner — no dangling links."""
        import seed_command_centre_partners as seed
        import partner_contacts_store
        seed.seed()
        for partner_id in ("braze", "hightouch"):
            contacts = partner_contacts_store.list_contacts(partner_id)
            ids = {c["id"] for c in contacts}
            for c in contacts:
                ref = c.get("reports_to_id")
                if ref:
                    self.assertIn(ref, ids,
                                  f"{c['name']} → {ref} (no such contact in {partner_id})")


if __name__ == "__main__":
    unittest.main()
