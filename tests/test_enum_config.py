"""v1.0.0ac — editable enum configuration store + endpoint."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class EnumConfigStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["ENUM_CONFIG_PATH"] = os.path.join(self.tmp, "enums.json")
        for mod in ("enum_config_store", "partner_contacts_store"):
            sys.modules.pop(mod, None)

    def tearDown(self):
        os.environ.pop("ENUM_CONFIG_PATH", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load_returns_defaults_when_no_file(self):
        import enum_config_store
        cfg = enum_config_store.load()
        # Industries default includes the new entries Ben asked for.
        self.assertIn("Entertainment", cfg["industries"])
        self.assertIn("Gaming", cfg["industries"])
        self.assertIn("Sports", cfg["industries"])
        # All 7 keys present.
        for key in ("industries", "territories", "regions", "statuses",
                     "partner_sentiments", "tiers", "seniorities"):
            self.assertIn(key, cfg)
            self.assertIsInstance(cfg[key], list)
            self.assertTrue(len(cfg[key]) > 0)

    def test_save_overrides_specific_keys(self):
        import enum_config_store
        cfg = enum_config_store.save({
            "industries": ["QSR", "Gaming", "Sports", "Esports"],
        })
        self.assertEqual(cfg["industries"], ["QSR", "Gaming", "Sports", "Esports"])
        # Other keys still come from defaults.
        self.assertIn("Champion", cfg["partner_sentiments"])

    def test_save_dedupes_and_strips(self):
        import enum_config_store
        cfg = enum_config_store.save({
            "tiers": ["  T1 — Strategic  ", "T1 — Strategic", "T2", "", "  ", "T2"],
        })
        self.assertEqual(cfg["tiers"], ["T1 — Strategic", "T2"])

    def test_save_empty_list_resets_to_default(self):
        import enum_config_store
        # First, set a custom list
        enum_config_store.save({"seniorities": ["Boss", "Worker"]})
        self.assertEqual(enum_config_store.load()["seniorities"], ["Boss", "Worker"])
        # Then pass [] to reset
        cfg = enum_config_store.save({"seniorities": []})
        self.assertIn("C-Suite", cfg["seniorities"])
        self.assertIn("VP", cfg["seniorities"])

    def test_save_ignores_unknown_keys(self):
        import enum_config_store
        before = enum_config_store.load()
        cfg = enum_config_store.save({"completely_unknown": ["x"]})
        self.assertEqual(set(cfg.keys()), set(before.keys()))

    def test_save_ignores_non_list_values(self):
        import enum_config_store
        before = enum_config_store.load()
        enum_config_store.save({"industries": "not a list"})
        self.assertEqual(enum_config_store.load()["industries"], before["industries"])

    def test_reset_single_key(self):
        import enum_config_store
        enum_config_store.save({"tiers": ["Custom"]})
        self.assertEqual(enum_config_store.load()["tiers"], ["Custom"])
        cfg = enum_config_store.reset_key("tiers")
        self.assertIn("T1 — Strategic", cfg["tiers"])

    def test_reset_unknown_key_raises(self):
        import enum_config_store
        with self.assertRaises(ValueError):
            enum_config_store.reset_key("not-real")

    def test_load_tolerates_corrupt_json(self):
        import enum_config_store
        # Write garbage to the file
        with open(os.environ["ENUM_CONFIG_PATH"], "w") as f:
            f.write("not json {{{")
        # Load should fall back to defaults silently
        cfg = enum_config_store.load()
        self.assertIn("Entertainment", cfg["industries"])


class PartnerContactsNewFieldsTests(unittest.TestCase):
    """New partner_sentiment / tier / seniority fields on partner contacts."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["PARTNER_CONTACTS_STORE_DIR"] = os.path.join(self.tmp, "pc")
        for mod in ("partner_contacts_store", "project_store"):
            sys.modules.pop(mod, None)

    def tearDown(self):
        os.environ.pop("PARTNER_CONTACTS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_new_fields_round_trip(self):
        import partner_contacts_store
        c = partner_contacts_store.save_contact("braze", {
            "name": "Marina Klusas",
            "partner_sentiment": "Champion",
            "tier": "T1 — Strategic",
            "seniority": "Director",
        })
        self.assertEqual(c["partner_sentiment"], "Champion")
        self.assertEqual(c["tier"], "T1 — Strategic")
        self.assertEqual(c["seniority"], "Director")
        # Survives re-read
        rows = partner_contacts_store.list_contacts("braze")
        self.assertEqual(rows[0]["partner_sentiment"], "Champion")

    def test_missing_new_fields_default_to_none(self):
        import partner_contacts_store
        c = partner_contacts_store.save_contact("braze", {"name": "Test"})
        self.assertIsNone(c["partner_sentiment"])
        self.assertIsNone(c["tier"])
        self.assertIsNone(c["seniority"])

    def test_blank_strings_collapse_to_none(self):
        import partner_contacts_store
        c = partner_contacts_store.save_contact("braze", {
            "name": "Test",
            "partner_sentiment": "   ",
            "tier": "",
            "seniority": None,
        })
        self.assertIsNone(c["partner_sentiment"])
        self.assertIsNone(c["tier"])
        self.assertIsNone(c["seniority"])


class EnumEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._env_set: dict[str, str | None] = {}
        for k, v in {
            "ENUM_CONFIG_PATH":         os.path.join(self.tmp, "enums.json"),
            "PARTNER_CONTACTS_STORE_DIR": os.path.join(self.tmp, "pc"),
            "PARTNERS_STORE_PATH":      os.path.join(self.tmp, "partners.json"),
            "PARTNER_NOTES_STORE_DIR":  os.path.join(self.tmp, "pn"),
            "SKIP_NOTION_BOOT":         "1",
            "SKIP_COMMAND_CENTRE_SEED": "1",
        }.items():
            self._env_set[k] = os.environ.get(k)
            os.environ[k] = v
        for mod in ("server", "enum_config_store", "partner_contacts_store"):
            sys.modules.pop(mod, None)
        import server
        self.server = server
        self.client = server.app.test_client()

    def tearDown(self):
        for k, original in self._env_set.items():
            if original is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = original
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_get_returns_full_config(self):
        r = self.client.get("/api/settings/enums")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        for key in ("industries", "territories", "regions", "statuses",
                     "partner_sentiments", "tiers", "seniorities"):
            self.assertIn(key, data)
        self.assertIn("Gaming", data["industries"])

    def test_patch_updates_keys(self):
        r = self.client.patch("/api/settings/enums",
                                json={"industries": ["QSR", "Gaming"]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["industries"], ["QSR", "Gaming"])

    def test_reset_endpoint(self):
        # Override industries
        self.client.patch("/api/settings/enums",
                          json={"industries": ["Custom1"]})
        self.assertEqual(self.client.get("/api/settings/enums")
                           .get_json()["industries"], ["Custom1"])
        # Reset
        r = self.client.post("/api/settings/enums/industries/reset")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Gaming", r.get_json()["industries"])

    def test_reset_unknown_key_returns_400(self):
        r = self.client.post("/api/settings/enums/garbage/reset")
        self.assertEqual(r.status_code, 400)

    def test_partner_enums_endpoint_includes_new_keys(self):
        """The Partners view's /api/partners/enums endpoint now surfaces
        partner_sentiments / tiers / seniorities so dropdowns populate."""
        r = self.client.get("/api/partners/enums")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("partner_sentiments", data)
        self.assertIn("tiers", data)
        self.assertIn("seniorities", data)
        self.assertIn("Champion", data["partner_sentiments"])

    def test_user_overrides_reflect_in_partner_enums(self):
        """User edits to enum_config_store should show up in the partner
        enums endpoint immediately (no caching across calls)."""
        self.client.patch("/api/settings/enums",
                          json={"industries": ["Esports", "Web3"]})
        r = self.client.get("/api/partners/enums")
        self.assertEqual(r.get_json()["industries"], ["Esports", "Web3"])


if __name__ == "__main__":
    unittest.main()
