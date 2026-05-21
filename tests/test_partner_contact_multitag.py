"""v1.0.0e (Tier 3b) — multi-tag territory + region for partner contacts.

A contact can own multiple territories (Strategic Enterprise + Enterprise),
multiple regions (East Coast + Central), and (already supported) multiple
industries. Backward-compatible: legacy single-string input still works.
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


class MultiTagNormaliserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["PARTNER_CONTACTS_STORE_DIR"] = self.tmp
        for mod in ("partner_contacts_store", "project_store"):
            sys.modules.pop(mod, None)

    def tearDown(self):
        os.environ.pop("PARTNER_CONTACTS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_list_input_kept_as_list(self):
        import partner_contacts_store
        c = partner_contacts_store.save_contact("braze", {
            "name": "Multi",
            "territories": ["Strategic Enterprise", "Enterprise"],
            "regions": ["East Coast", "Central"],
        })
        self.assertEqual(c["territories"], ["Strategic Enterprise", "Enterprise"])
        self.assertEqual(c["regions"], ["East Coast", "Central"])
        # Singular shims preserve back-compat readers
        self.assertEqual(c["territory"], "Strategic Enterprise")
        self.assertEqual(c["region"], "East Coast")

    def test_legacy_singular_input_lifted_to_list(self):
        import partner_contacts_store
        c = partner_contacts_store.save_contact("braze", {
            "name": "Legacy",
            "territory": "Enterprise",
            "region": "UK",
        })
        self.assertEqual(c["territories"], ["Enterprise"])
        self.assertEqual(c["regions"], ["UK"])
        self.assertEqual(c["territory"], "Enterprise")
        self.assertEqual(c["region"], "UK")

    def test_comma_separated_string_parses(self):
        """CSV importers may pass `territory: "A, B"` — handle it."""
        import partner_contacts_store
        c = partner_contacts_store.save_contact("braze", {
            "name": "CSV",
            "territory": "Strategic Enterprise, Enterprise",
            "region": "East Coast, Central",
        })
        self.assertEqual(c["territories"], ["Strategic Enterprise", "Enterprise"])
        self.assertEqual(c["regions"], ["East Coast", "Central"])

    def test_empty_input_yields_empty_lists(self):
        import partner_contacts_store
        c = partner_contacts_store.save_contact("braze", {"name": "x"})
        self.assertEqual(c["territories"], [])
        self.assertEqual(c["regions"], [])
        self.assertIsNone(c["territory"])
        self.assertIsNone(c["region"])

    def test_dedupe_within_list(self):
        import partner_contacts_store
        c = partner_contacts_store.save_contact("braze", {
            "name": "Dupe",
            "territories": ["Enterprise", "Enterprise", "Mid-Market"],
        })
        self.assertEqual(c["territories"], ["Enterprise", "Mid-Market"])

    def test_plural_input_wins_over_singular_when_both_present(self):
        """If both `territories` (new shape) and `territory` (legacy) are
        in the payload, the new shape wins."""
        import partner_contacts_store
        c = partner_contacts_store.save_contact("braze", {
            "name": "Mixed",
            "territories": ["Strategic Enterprise"],
            "territory": "Enterprise",  # legacy field — should be ignored
        })
        self.assertEqual(c["territories"], ["Strategic Enterprise"])
        self.assertEqual(c["territory"], "Strategic Enterprise")

    def test_update_does_not_explode_existing_legacy_record(self):
        """Save once with legacy shape, then load and re-save (e.g. on
        edit) — both shapes should be present and consistent."""
        import partner_contacts_store
        first = partner_contacts_store.save_contact("braze", {
            "name": "Edit Me", "territory": "Enterprise",
        })
        # Re-save with the same dict (round-trip)
        second = partner_contacts_store.save_contact("braze", first)
        self.assertEqual(second["territories"], ["Enterprise"])
        self.assertEqual(second["territory"], "Enterprise")


class MultiTagSearchTests(unittest.TestCase):
    """Cross-surface search filters must match against the new multi-tag
    lists — a contact tagged 'Strategic Enterprise, Enterprise' should
    appear in a 'territory=Enterprise' filter."""

    @classmethod
    def setUpClass(cls):
        import importlib
        cls.tmp = tempfile.mkdtemp()
        os.environ["PARTNER_CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "pc")
        os.environ["PARTNERS_STORE_PATH"] = os.path.join(cls.tmp, "partners.json")
        os.environ["CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "contacts")
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "partner_contacts_store", "partners_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("PARTNER_CONTACTS_STORE_DIR", "PARTNERS_STORE_PATH",
                  "CONTACTS_STORE_DIR"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_search_matches_secondary_territory(self):
        """A contact with territories=[A, B] must appear when filtering
        by B (not just by A)."""
        import partner_contacts_store, partners_store
        partners_store.save_partner({"name": "Braze"})
        partner_contacts_store.save_contact("braze", {
            "name": "Multi Marina",
            "territories": ["Strategic Enterprise", "Enterprise"],
            "regions": ["East Coast", "Central"],
        })
        # Filter by the SECOND territory — must still surface.
        r = self.client.get("/api/contacts/search?territory=Enterprise")
        names = [c["name"] for c in r.get_json()["partner"]]
        self.assertIn("Multi Marina", names)
        # Same for secondary region.
        r2 = self.client.get("/api/contacts/search?region=Central")
        names2 = [c["name"] for c in r2.get_json()["partner"]]
        self.assertIn("Multi Marina", names2)

    def test_search_legacy_singular_still_works(self):
        """A pre-multi-tag contact stored with only `territory` (string)
        should still match the filter."""
        import partner_contacts_store, partners_store
        partners_store.save_partner({"name": "Legacy"})
        # Use the normaliser via save_contact, but pass legacy shape.
        partner_contacts_store.save_contact("legacy", {
            "name": "Legacy Lou", "territory": "Mid-Market",
        })
        r = self.client.get("/api/contacts/search?territory=Mid-Market")
        names = [c["name"] for c in r.get_json()["partner"]]
        self.assertIn("Legacy Lou", names)


if __name__ == "__main__":
    unittest.main()
