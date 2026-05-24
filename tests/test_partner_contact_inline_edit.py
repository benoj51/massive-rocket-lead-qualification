"""v1.0.0bt — Inline-edit PATCH for partner contacts.

The new Partners table renders Tier / Sentiment / Seniority as
editable dropdowns that PATCH `/api/partners/<pid>/contacts/<cid>`
with a single field on change. These tests pin the endpoint
behaviour the UI relies on:

1. A single-field PATCH must NOT clobber the other fields.
2. Setting a value to null/empty must clear it without erroring.
3. Other fields (industries multi-tag, name, etc.) must round-trip
   through the partial-update path unchanged.
"""
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


class PartnerContactInlineEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["PARTNERS_STORE_PATH"] = os.path.join(cls.tmp, "partners.json")
        os.environ["PARTNER_CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "pc")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "partners_store", "partner_contacts_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("PARTNERS_STORE_PATH", "PARTNER_CONTACTS_STORE_DIR",
                  "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        import partners_store, partner_contacts_store
        # Reset both stores between tests.
        p = partners_store._path()
        if p.exists():
            p.unlink()
        d = partner_contacts_store._store_dir()
        if d.exists():
            for f in d.glob("*.json"):
                f.unlink()
        # Seed: one partner + one richly-populated contact so we
        # can prove the partial PATCH doesn't lose neighbours.
        self.partner = partners_store.save_partner({
            "name": "Braze", "type": "Technology partner"})
        self.contact = partner_contacts_store.save_contact(self.partner["id"], {
            "name":              "Marina Klusas",
            "title":             "Strategic Enterprise AE",
            "email":             "marina@braze.com",
            "tier":              "T1 — Critical",
            "partner_sentiment": "Warm",
            "seniority":         "Director",
            "industries":        ["QSR", "Retail"],
            "country":           "United States",
            "mr_owner":          "Ben Ojuolape",
        })

    def _patch(self, body):
        return self.client.patch(
            f"/api/partners/{self.partner['id']}/contacts/{self.contact['id']}",
            json=body)

    # ---- single-field PATCH path -----------------------------------

    def test_single_field_patch_tier(self):
        r = self._patch({"tier": "T2 — Important"})
        self.assertEqual(r.status_code, 200)
        saved = r.get_json()["contact"]
        self.assertEqual(saved["tier"], "T2 — Important")
        # Neighbours unchanged.
        self.assertEqual(saved["partner_sentiment"], "Warm")
        self.assertEqual(saved["seniority"], "Director")
        self.assertEqual(saved["email"], "marina@braze.com")
        self.assertEqual(saved["industries"], ["QSR", "Retail"])
        self.assertEqual(saved["mr_owner"], "Ben Ojuolape")

    def test_single_field_patch_sentiment(self):
        r = self._patch({"partner_sentiment": "Champion"})
        self.assertEqual(r.status_code, 200)
        saved = r.get_json()["contact"]
        self.assertEqual(saved["partner_sentiment"], "Champion")
        # Tier unchanged.
        self.assertEqual(saved["tier"], "T1 — Critical")
        self.assertEqual(saved["seniority"], "Director")

    def test_single_field_patch_seniority(self):
        r = self._patch({"seniority": "VP"})
        self.assertEqual(r.status_code, 200)
        saved = r.get_json()["contact"]
        self.assertEqual(saved["seniority"], "VP")
        # Neighbours.
        self.assertEqual(saved["tier"], "T1 — Critical")
        self.assertEqual(saved["partner_sentiment"], "Warm")

    # ---- clearing a value with null/empty --------------------------

    def test_clear_tier_with_null(self):
        r = self._patch({"tier": None})
        self.assertEqual(r.status_code, 200)
        saved = r.get_json()["contact"]
        self.assertIsNone(saved["tier"])
        # Sentiment intact.
        self.assertEqual(saved["partner_sentiment"], "Warm")

    def test_clear_sentiment_with_empty_string(self):
        r = self._patch({"partner_sentiment": ""})
        self.assertEqual(r.status_code, 200)
        saved = r.get_json()["contact"]
        # Empty string normalises to None.
        self.assertIsNone(saved["partner_sentiment"])
        self.assertEqual(saved["tier"], "T1 — Critical")

    def test_clear_seniority_with_null(self):
        r = self._patch({"seniority": None})
        self.assertEqual(r.status_code, 200)
        saved = r.get_json()["contact"]
        self.assertIsNone(saved["seniority"])

    # ---- rapid sequential edits (the UI's actual access pattern) ---

    def test_three_sequential_field_edits(self):
        """The UI sends three separate PATCH calls if the user
        changes tier then sentiment then seniority. Each call's
        result must reflect all prior edits — last-write-wins on a
        partial merge."""
        r1 = self._patch({"tier": "T3 — Nurture"})
        self.assertEqual(r1.get_json()["contact"]["tier"], "T3 — Nurture")
        r2 = self._patch({"partner_sentiment": "Cool"})
        c2 = r2.get_json()["contact"]
        self.assertEqual(c2["tier"], "T3 — Nurture")  # preserved
        self.assertEqual(c2["partner_sentiment"], "Cool")
        r3 = self._patch({"seniority": "C-Suite"})
        c3 = r3.get_json()["contact"]
        self.assertEqual(c3["tier"], "T3 — Nurture")
        self.assertEqual(c3["partner_sentiment"], "Cool")
        self.assertEqual(c3["seniority"], "C-Suite")
        # Free-text + multi-tag fields untouched.
        self.assertEqual(c3["name"], "Marina Klusas")
        self.assertEqual(c3["industries"], ["QSR", "Retail"])

    # ---- error paths ------------------------------------------------

    def test_patch_unknown_contact_404(self):
        r = self.client.patch(
            f"/api/partners/{self.partner['id']}/contacts/nope",
            json={"tier": "T2 — Important"})
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
