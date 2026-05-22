"""v1.0.0m — partner-contact conversation synthesis.

Tests:
- Store round-trips
- Add-note endpoint triggers a synthesis refresh (mocked Claude)
- Summary GET returns the cached payload
- Summary POST forces a refresh
- Schema normalisation drops bad shapes / caps array lengths
- Synthesis is best-effort (None when AI unconfigured + endpoint
  surfaces a friendly message, doesn't 500)
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
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _reload_partner_stack():
    """Ensure stores pick up the temp dirs set in setUp."""
    for mod in (
        "partner_contact_summary_store",
        "partner_notes_store",
        "partner_contacts_store",
        "partners_store",
        "project_store",
    ):
        sys.modules.pop(mod, None)


class StoreRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["PARTNER_CONTACT_SUMMARY_STORE_DIR"] = os.path.join(self.tmp, "pcs")
        _reload_partner_stack()

    def tearDown(self):
        os.environ.pop("PARTNER_CONTACT_SUMMARY_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load_missing_returns_none(self):
        import partner_contact_summary_store as store
        self.assertIsNone(store.load("braze", "missing"))

    def test_save_then_load_roundtrip(self):
        import partner_contact_summary_store as store
        payload = {
            "summary": "Marina is excited about Popeyes Q3.",
            "accounts_discussed": ["Popeyes US"],
            "updates_on_prior_accounts": [],
            "territory_info": ["Strategic Enterprise CPG — US East"],
            "challenges": ["No exec sponsor at the brand level"],
            "opportunities": ["KFC US expansion is the next domino"],
            "additional_info": "Marina's manager just changed to Bill Thomas.",
        }
        saved = store.save("braze", "marina-klusas", payload)
        self.assertIn("generated_at", saved)
        loaded = store.load("braze", "marina-klusas")
        self.assertEqual(loaded["summary"], payload["summary"])
        self.assertEqual(loaded["accounts_discussed"], ["Popeyes US"])

    def test_delete_removes_file(self):
        import partner_contact_summary_store as store
        store.save("braze", "marina-klusas", {"summary": "x"})
        self.assertTrue(store.delete("braze", "marina-klusas"))
        self.assertIsNone(store.load("braze", "marina-klusas"))
        # Second delete is a no-op
        self.assertFalse(store.delete("braze", "marina-klusas"))


class SynthesisNormalisationTests(unittest.TestCase):
    """The synthesis function caps arrays at 6 and ignores malformed
    keys — even when Claude returns extras."""

    def test_returns_none_without_api_key(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        sys.modules.pop("ai_summary", None)
        import ai_summary
        result = ai_summary.synthesise_partner_contact_conversation({"contact": {}, "notes": []})
        self.assertIsNone(result)

    def test_normalises_oversize_arrays_and_missing_fields(self):
        """Patch the Claude client to return a misshapen JSON blob and
        check that we cap arrays at 6 + default missing fields."""
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        sys.modules.pop("ai_summary", None)
        import ai_summary

        fake_response = mock.MagicMock()
        fake_response.content = [mock.MagicMock(text=json.dumps({
            "summary": "  Pad spaces  ",
            "accounts_discussed": [f"Account {i}" for i in range(10)],
            # missing updates_on_prior_accounts
            "territory_info": [123, "  ", "Real bullet", None],
            "challenges": ["A challenge"],
            "opportunities": ["Opp 1", "Opp 2"],
            # additional_info missing entirely
        }))]
        fake_client = mock.MagicMock()
        fake_client.messages.create.return_value = fake_response

        with mock.patch.object(ai_summary, "Anthropic", create=True, return_value=fake_client):
            # The function imports Anthropic locally — patch the module-level
            # attribute lookup by injecting via sys.modules.
            sys.modules["anthropic"] = mock.MagicMock(Anthropic=lambda **kw: fake_client)
            result = ai_summary.synthesise_partner_contact_conversation({
                "contact": {"name": "Marina"}, "notes": [{"content": "test"}],
            })

        self.assertIsNotNone(result)
        self.assertEqual(result["summary"], "Pad spaces")
        self.assertEqual(len(result["accounts_discussed"]), 6)  # capped
        self.assertEqual(result["updates_on_prior_accounts"], [])  # defaulted
        # 123 + None + whitespace filtered, "Real bullet" survives
        self.assertEqual(result["territory_info"], ["123", "Real bullet"])
        self.assertEqual(result["challenges"], ["A challenge"])
        self.assertEqual(result["additional_info"], "")


class EndpointIntegrationTests(unittest.TestCase):
    """End-to-end through the Flask app: add note → server refreshes
    summary → GET returns it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Snapshot which env vars we're setting so tearDown can restore
        # whatever the parent process had, instead of unconditionally
        # popping (which polluted the next test class's module reload).
        self._env_set: dict[str, str | None] = {}
        for k, v in {
            "PARTNERS_STORE_PATH": os.path.join(self.tmp, "p.json"),
            "PARTNER_CONTACTS_STORE_DIR": os.path.join(self.tmp, "pc"),
            "PARTNER_NOTES_STORE_DIR": os.path.join(self.tmp, "pn"),
            "PARTNER_CONTACT_SUMMARY_STORE_DIR": os.path.join(self.tmp, "pcs"),
            "SKIP_NOTION_BOOT": "1",
            "SKIP_COMMAND_CENTRE_SEED": "1",
        }.items():
            self._env_set[k] = os.environ.get(k)  # may be None
            os.environ[k] = v
        os.environ.pop("ANTHROPIC_API_KEY", None)
        for mod in (
            "server", "audit", "ai_summary",
            "partner_contact_summary_store",
            "partner_notes_store", "partner_contacts_store",
            "partners_store", "project_store",
        ):
            sys.modules.pop(mod, None)
        import server
        self.server = server
        self.client = server.app.test_client()
        # Seed a partner + contact directly via the stores to keep the
        # test independent of the seed file.
        import partners_store, partner_contacts_store
        self.partner = partners_store.save_partner({
            "name": "Braze", "type": "Technology partner",
        })
        partner_contacts_store.save_contact(self.partner["id"], {
            "id": "braze-marina-klusas", "name": "Marina Klusas",
            "title": "Strategic Enterprise AE — CPG",
            "territories": ["Strategic Enterprise"],
            "country": "United States",
        })

    def tearDown(self):
        # Restore the parent-process env exactly as we found it. Popping
        # unconditionally would unset a SKIP_* flag that the test
        # runner had set on the command line, which then leaked into
        # the next test class's module reload.
        for k, original in self._env_set.items():
            if original is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = original
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_add_note_returns_summary_field_even_when_ai_off(self):
        """Without ANTHROPIC_API_KEY the synthesis is None — the endpoint
        must still return the note + a summary key (null), never 500."""
        r = self.client.post(
            f"/api/partners/{self.partner['id']}/contacts/braze-marina-klusas/notes",
            json={"type": "call", "content": "Talked about Popeyes US Q3 plans."},
        )
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("note", data)
        self.assertEqual(len(data["notes"]), 1)
        self.assertIn("summary", data)
        self.assertIsNone(data["summary"])  # AI off → no synthesis

    def test_summary_get_returns_null_when_not_yet_generated(self):
        r = self.client.get(
            f"/api/partners/{self.partner['id']}/contacts/braze-marina-klusas/summary"
        )
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.get_json()["summary"])

    def test_summary_post_returns_friendly_message_when_ai_off(self):
        # Add a note first so there's something to synthesise.
        self.client.post(
            f"/api/partners/{self.partner['id']}/contacts/braze-marina-klusas/notes",
            json={"type": "call", "content": "Note body."},
        )
        r = self.client.post(
            f"/api/partners/{self.partner['id']}/contacts/braze-marina-klusas/summary"
        )
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIsNone(data["summary"])
        self.assertIn("ANTHROPIC_API_KEY", data.get("error", ""))

    def test_summary_persists_after_mocked_synthesis(self):
        """When AI returns a payload, the server caches it and the GET
        endpoint returns the cached value."""
        # Add a note first
        self.client.post(
            f"/api/partners/{self.partner['id']}/contacts/braze-marina-klusas/notes",
            json={"type": "call", "content": "Initial context."},
        )

        # Mock the synthesis function to return a fake summary.
        import ai_summary
        fake_summary = {
            "summary": "Marina is focused on Popeyes Q3.",
            "accounts_discussed": ["Popeyes US"],
            "updates_on_prior_accounts": [],
            "territory_info": ["US East Coast"],
            "challenges": ["No exec sponsor"],
            "opportunities": ["KFC US expansion"],
            "additional_info": "",
        }
        with mock.patch.object(
            ai_summary, "synthesise_partner_contact_conversation",
            return_value=fake_summary,
        ):
            r = self.client.post(
                f"/api/partners/{self.partner['id']}/contacts/braze-marina-klusas/summary"
            )

        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIsNotNone(data["summary"])
        self.assertEqual(data["summary"]["summary"], "Marina is focused on Popeyes Q3.")

        # Now the GET endpoint should return the cached value (no AI needed).
        r2 = self.client.get(
            f"/api/partners/{self.partner['id']}/contacts/braze-marina-klusas/summary"
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.get_json()["summary"]["summary"],
                          "Marina is focused on Popeyes Q3.")


if __name__ == "__main__":
    unittest.main()
