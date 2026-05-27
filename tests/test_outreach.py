"""v1.0.0df - outreach draft module + endpoint."""
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


# --------------------------------------------------------------------
# Layer 1: pure module - prompt + parser
# --------------------------------------------------------------------

class OutreachModuleTests(unittest.TestCase):
    def setUp(self):
        sys.modules.pop("outreach", None)
        import outreach
        self.outreach = outreach

    def test_bad_channel_raises(self):
        with self.assertRaises(ValueError):
            self.outreach.draft({"name": "X"}, "fax")

    def test_invalid_tone_falls_back_to_friendly(self):
        # No API key set => returns the early-return dict with empty body
        # but doesn't raise. The tone normalisation happens before that.
        os.environ.pop("ANTHROPIC_API_KEY", None)
        out = self.outreach.draft({"name": "X"}, "email",
                                    tone="bizarre-tone")
        self.assertEqual(out["tone"], "friendly")

    def test_not_configured_returns_error_payload(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        out = self.outreach.draft({"name": "X"}, "email")
        self.assertEqual(out["body"], "")
        self.assertIn("API key", out.get("error", ""))

    def test_email_parser_extracts_subject(self):
        sub, body = self.outreach._parse_email(
            "Subject: Hello there\n\nHi Marina,\n\nLet's catch up.\n")
        self.assertEqual(sub, "Hello there")
        self.assertIn("Hi Marina", body)

    def test_email_parser_no_subject_returns_none(self):
        sub, body = self.outreach._parse_email("Hi there,\nJust a note.")
        self.assertIsNone(sub)
        self.assertIn("Just a note", body)

    def test_draft_email_full_path_with_mock(self):
        """End-to-end with a faked Anthropic response."""
        os.environ["ANTHROPIC_API_KEY"] = "test"
        try:
            class _Block:
                def __init__(self, text): self.text = text
            class _Msg:
                def __init__(self, text): self.content = [_Block(text)]
            class _Messages:
                def create(self, **kwargs):
                    return _Msg(
                        "Subject: Quick check-in on Pizza Hut\n\n"
                        "Hi Marina,\n\nFollowing up after last week's "
                        "conversation. Are you free Tuesday at 3?\n\n"
                        "Ben"
                    )
            class _Fake:
                def __init__(self, **kw): self.messages = _Messages()
            import anthropic
            with patch.object(anthropic, "Anthropic", _Fake):
                out = self.outreach.draft(
                    {"name": "Marina Klusas", "title": "Strategic AE",
                     "partner_name": "Braze", "email": "marina@braze.com"},
                    "email",
                    sender_name="Ben Ojuolape",
                    context_hint="Following up on Pizza Hut conversation",
                )
            self.assertEqual(out["channel"], "email")
            self.assertEqual(out["subject"], "Quick check-in on Pizza Hut")
            self.assertIn("Marina", out["body"])
            self.assertTrue(out["mailto"].startswith("mailto:marina@braze.com?"))
            self.assertIn("subject=", out["mailto"])
            self.assertGreater(out["char_count"], 0)
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)

    def test_draft_linkedin_has_no_subject_or_mailto(self):
        os.environ["ANTHROPIC_API_KEY"] = "test"
        try:
            class _Block:
                def __init__(self, text): self.text = text
            class _Msg:
                def __init__(self, text): self.content = [_Block(text)]
            class _Messages:
                def create(self, **kwargs):
                    return _Msg("Hi Marina, would love to catch up next week.")
            class _Fake:
                def __init__(self, **kw): self.messages = _Messages()
            import anthropic
            with patch.object(anthropic, "Anthropic", _Fake):
                out = self.outreach.draft(
                    {"name": "Marina", "partner_name": "Braze",
                     "linkedin_url": "https://linkedin.com/in/marina"},
                    "linkedin",
                )
            self.assertIsNone(out["subject"])
            self.assertIsNone(out["mailto"])
            self.assertEqual(out["channel"], "linkedin")
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)


# --------------------------------------------------------------------
# Layer 2: endpoint contract
# --------------------------------------------------------------------

class OutreachEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["PARTNERS_STORE_PATH"] = os.path.join(cls.tmp, "p.json")
        os.environ["PARTNER_CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "pc")
        os.environ["PARTNER_NOTES_STORE_DIR"] = os.path.join(cls.tmp, "pn")
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        os.environ["ANTHROPIC_API_KEY"] = "test"
        for m in ("server", "outreach", "partners_store",
                  "partner_contacts_store", "partner_notes_store"):
            sys.modules.pop(m, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("PARTNERS_STORE_PATH", "PARTNER_CONTACTS_STORE_DIR",
                  "PARTNER_NOTES_STORE_DIR", "ANTHROPIC_API_KEY"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _fake_anthropic(self, raw_text: str):
        class _Block:
            def __init__(self, text): self.text = text
        class _Msg:
            def __init__(self, text): self.content = [_Block(text)]
        class _Messages:
            def create(self, **kwargs):
                return _Msg(raw_text)
        class _Fake:
            def __init__(self, **kw): self.messages = _Messages()
        import anthropic
        return patch.object(anthropic, "Anthropic", _Fake)

    def test_endpoint_drafts_email_for_partner_contact(self):
        # Seed a partner + contact
        self.client.post("/api/partners", json={"name": "Braze"})
        c = self.client.post("/api/partners/braze/contacts", json={
            "name": "Marina Klusas", "title": "Strategic AE",
            "email": "marina@braze.com",
        }).get_json()["contact"]

        with self._fake_anthropic(
            "Subject: Pizza Hut intro\n\nHi Marina,\n\nWanted to check in.\n\nBen"
        ):
            r = self.client.post("/api/outreach/draft", json={
                "contact_kind": "partner_contact",
                "partner_id":   "braze",
                "contact_id":   c["id"],
                "channel":      "email",
                "tone":         "friendly",
                "sender_name":  "Ben Ojuolape",
            })
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["draft"]["channel"], "email")
        self.assertEqual(body["draft"]["subject"], "Pizza Hut intro")
        self.assertTrue(body["draft"]["mailto"].startswith("mailto:"))

    def test_endpoint_rejects_unknown_contact(self):
        r = self.client.post("/api/outreach/draft", json={
            "contact_kind": "partner_contact",
            "partner_id":   "braze",
            "contact_id":   "does-not-exist",
            "channel":      "email",
        })
        self.assertEqual(r.status_code, 404)

    def test_endpoint_rejects_bad_channel(self):
        self.client.post("/api/partners", json={"name": "Iterable"})
        c = self.client.post("/api/partners/iterable/contacts", json={
            "name": "Test"
        }).get_json()["contact"]
        r = self.client.post("/api/outreach/draft", json={
            "contact_kind": "partner_contact",
            "partner_id":   "iterable",
            "contact_id":   c["id"],
            "channel":      "fax",
        })
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
