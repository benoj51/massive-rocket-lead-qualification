"""v1.0.0bq — Settings → Users (writable MR owners store) tests.

Covers:
1. mr_owners_store CRUD + seed-on-first-read + ordering.
2. /api/settings/users CRUD endpoints.
3. mr_owners.py shim: list_owners / get_owner / names still resolve
   against the writable store so every existing caller
   (notifications, dropdowns, scoring) keeps working without an edit.
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


# -----------------------------------------------------------------
# Layer 1: mr_owners_store
# -----------------------------------------------------------------

class MrOwnersStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["MR_OWNERS_STORE_DIR"] = self.tmp
        sys.modules.pop("mr_owners_store", None)
        sys.modules.pop("mr_owners", None)
        import mr_owners_store
        self.store = mr_owners_store

    def tearDown(self):
        os.environ.pop("MR_OWNERS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- seed --------------------------------------------------------

    def test_first_read_seeds_from_constant(self):
        """No file yet → list_owners returns the seed list immediately.
        Subsequent reads use the persisted file."""
        owners = self.store.list_owners()
        self.assertGreaterEqual(len(owners), 12)
        # File should now exist on disk.
        self.assertTrue((Path(self.tmp) / "owners.json").exists())

    def test_seed_preserves_display_order(self):
        names = self.store.names()
        # First three from SEED_OWNERS: Thierry / Daniel Craig / Ben.
        self.assertEqual(names[0], "Thierry Sequeira")
        self.assertEqual(names[1], "Daniel Craig")
        self.assertEqual(names[2], "Ben Ojuolape")

    def test_seed_only_fires_once(self):
        """If a file already exists, the seed list is NOT re-read.
        Otherwise edits would silently revert on each list call."""
        self.store.list_owners()  # creates file
        # Mutate underlying file: remove first entry, save.
        owners = self.store.list_owners()
        self.store.delete_owner(owners[0]["id"])
        # Second list shouldn't reintroduce the deleted seed entry.
        re_listed = self.store.list_owners()
        self.assertNotIn(owners[0]["name"], [o["name"] for o in re_listed])

    # ---- create ------------------------------------------------------

    def test_create_owner(self):
        o = self.store.create_owner({
            "name": "Test Person", "role": "QA",
            "region": "Global", "email": "test@mr.com"})
        self.assertEqual(o["name"], "Test Person")
        self.assertEqual(o["role"], "QA")
        self.assertTrue(o["active"])
        self.assertTrue(o["id"])
        # Persisted.
        names = self.store.names()
        self.assertIn("Test Person", names)

    def test_create_requires_name(self):
        with self.assertRaises(self.store.MrOwnersStoreError):
            self.store.create_owner({"role": "QA"})
        with self.assertRaises(self.store.MrOwnersStoreError):
            self.store.create_owner({"name": "  "})

    def test_create_rejects_duplicate_name(self):
        """Two rows with the same name would confuse the owner-dropdown
        downstream — every UI surface keys off the name string."""
        self.store.create_owner({"name": "Unique One"})
        with self.assertRaises(self.store.MrOwnersStoreError):
            self.store.create_owner({"name": "unique one"})  # case-insensitive

    def test_new_owner_lands_at_end_of_order(self):
        before = len(self.store.list_owners(active_only=False))
        self.store.create_owner({"name": "ZZZ Late Add"})
        listed = self.store.list_owners(active_only=False)
        self.assertEqual(len(listed), before + 1)
        # Should be last in the display order.
        self.assertEqual(listed[-1]["name"], "ZZZ Late Add")

    # ---- update ------------------------------------------------------

    def test_update_owner_fields(self):
        o = self.store.create_owner({"name": "Updateable"})
        u = self.store.update_owner(o["id"], role="New Role",
                                       region="EMEA", email="new@mr.com")
        self.assertEqual(u["role"], "New Role")
        self.assertEqual(u["region"], "EMEA")
        self.assertEqual(u["email"], "new@mr.com")

    def test_update_rename(self):
        o = self.store.create_owner({"name": "Old Name"})
        u = self.store.update_owner(o["id"], name="New Name")
        self.assertEqual(u["name"], "New Name")
        # ID is stable across renames.
        self.assertEqual(u["id"], o["id"])

    def test_rename_to_existing_name_rejected(self):
        a = self.store.create_owner({"name": "Alpha"})
        self.store.create_owner({"name": "Beta"})
        with self.assertRaises(self.store.MrOwnersStoreError):
            self.store.update_owner(a["id"], name="beta")

    def test_update_name_cannot_be_blank(self):
        o = self.store.create_owner({"name": "X"})
        with self.assertRaises(self.store.MrOwnersStoreError):
            self.store.update_owner(o["id"], name="")

    def test_update_rejects_unknown_field(self):
        o = self.store.create_owner({"name": "X"})
        with self.assertRaises(self.store.MrOwnersStoreError):
            self.store.update_owner(o["id"], created_at="changed")

    def test_update_unknown_id_returns_none(self):
        self.assertIsNone(self.store.update_owner("nope", role="X"))

    # ---- (de)activate -----------------------------------------------

    def test_deactivate_then_reactivate(self):
        o = self.store.create_owner({"name": "Cycle"})
        deactivated = self.store.deactivate_owner(o["id"])
        self.assertFalse(deactivated["active"])
        # active_only=True hides it.
        active_names = self.store.names()
        self.assertNotIn("Cycle", active_names)
        # active_only=False still surfaces it.
        all_names = self.store.names(active_only=False)
        self.assertIn("Cycle", all_names)
        # Reactivate.
        re_act = self.store.activate_owner(o["id"])
        self.assertTrue(re_act["active"])
        self.assertIn("Cycle", self.store.names())

    def test_deactivated_get_owner_still_resolves(self):
        """get_owner returns inactive rows too — historical
        lead.owner = "Old Name" references must keep resolving back
        to an email/role after the person leaves."""
        o = self.store.create_owner({"name": "Departed",
                                        "email": "gone@mr.com"})
        self.store.deactivate_owner(o["id"])
        resolved = self.store.get_owner("departed")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["email"], "gone@mr.com")

    # ---- delete ------------------------------------------------------

    def test_delete_owner(self):
        o = self.store.create_owner({"name": "Doomed"})
        self.assertTrue(self.store.delete_owner(o["id"]))
        self.assertIsNone(self.store.get_owner(o["id"]))
        self.assertFalse(self.store.delete_owner(o["id"]))

    def test_delete_empty_id(self):
        self.assertFalse(self.store.delete_owner(""))

    # ---- get ---------------------------------------------------------

    def test_get_owner_by_name_case_insensitive(self):
        o = self.store.create_owner({"name": "Case Test"})
        self.assertEqual(self.store.get_owner("CASE TEST")["id"], o["id"])
        self.assertEqual(self.store.get_owner("case test")["id"], o["id"])

    def test_get_owner_by_id(self):
        o = self.store.create_owner({"name": "ById"})
        self.assertEqual(self.store.get_owner(o["id"])["name"], "ById")

    def test_get_owner_empty(self):
        self.assertIsNone(self.store.get_owner(""))
        self.assertIsNone(self.store.get_owner("   "))


# -----------------------------------------------------------------
# Layer 2: mr_owners.py backward-compat shim
# -----------------------------------------------------------------

class MrOwnersShimTests(unittest.TestCase):
    """The shim has to keep working for the half-dozen modules that
    import mr_owners.list_owners / get_owner / names. Any drift
    silently breaks notifications + owner dropdowns."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["MR_OWNERS_STORE_DIR"] = self.tmp
        sys.modules.pop("mr_owners_store", None)
        sys.modules.pop("mr_owners", None)
        import mr_owners
        self.mod = mr_owners

    def tearDown(self):
        os.environ.pop("MR_OWNERS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_shim_list_owners(self):
        self.assertGreaterEqual(len(self.mod.list_owners()), 12)

    def test_shim_names(self):
        names = self.mod.names()
        self.assertIn("Ben Ojuolape", names)

    def test_shim_get_owner_by_name(self):
        o = self.mod.get_owner("Ben Ojuolape")
        self.assertIsNotNone(o)
        self.assertEqual(o["email"], "ben@massiverocket.com")

    def test_shim_owners_constant_is_a_list(self):
        """Some legacy code iterates mr_owners.OWNERS directly. The
        shim materialises it on import so the iteration works
        without callers being aware of the migration."""
        self.assertIsInstance(self.mod.OWNERS, list)
        self.assertTrue(all(isinstance(o, dict) for o in self.mod.OWNERS))


# -----------------------------------------------------------------
# Layer 3: /api/settings/users endpoints
# -----------------------------------------------------------------

class SettingsUsersEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["MR_OWNERS_STORE_DIR"] = cls.tmp
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "mr_owners_store", "mr_owners"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("MR_OWNERS_STORE_DIR", "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        # Reset to seed list per test — independent of test order.
        import mr_owners_store
        p = Path(mr_owners_store._store_dir()) / "owners.json"
        if p.exists():
            p.unlink()

    def test_list_users_includes_seed(self):
        r = self.client.get("/api/settings/users")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertGreaterEqual(body["count"], 12)
        names = [u["name"] for u in body["users"]]
        self.assertIn("Ben Ojuolape", names)

    def test_create_endpoint(self):
        r = self.client.post("/api/settings/users", json={
            "name": "API New", "role": "API Tester",
            "region": "Test", "email": "api@mr.com"})
        self.assertEqual(r.status_code, 201)
        u = r.get_json()["user"]
        self.assertEqual(u["name"], "API New")
        self.assertEqual(u["role"], "API Tester")

    def test_create_duplicate_name_400(self):
        self.client.post("/api/settings/users", json={"name": "DupeAPI"})
        r = self.client.post("/api/settings/users", json={"name": "dupeapi"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("already exists", r.get_json()["error"])

    def test_create_missing_name_400(self):
        r = self.client.post("/api/settings/users", json={"role": "X"})
        self.assertEqual(r.status_code, 400)

    def test_patch_endpoint(self):
        c = self.client.post("/api/settings/users",
                                json={"name": "Patcheable"}).get_json()
        uid = c["user"]["id"]
        r = self.client.patch(f"/api/settings/users/{uid}",
                                json={"role": "Patched"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["user"]["role"], "Patched")

    def test_patch_deactivate(self):
        c = self.client.post("/api/settings/users",
                                json={"name": "DeactivateMe"}).get_json()
        uid = c["user"]["id"]
        r = self.client.patch(f"/api/settings/users/{uid}",
                                json={"active": False})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.get_json()["user"]["active"])

    def test_patch_unknown_id_404(self):
        r = self.client.patch("/api/settings/users/nope",
                                json={"role": "X"})
        self.assertEqual(r.status_code, 404)

    def test_patch_unknown_field_400(self):
        c = self.client.post("/api/settings/users",
                                json={"name": "Bogus"}).get_json()
        uid = c["user"]["id"]
        r = self.client.patch(f"/api/settings/users/{uid}",
                                json={"created_at": "tampered"})
        self.assertEqual(r.status_code, 400)

    def test_delete_endpoint(self):
        c = self.client.post("/api/settings/users",
                                json={"name": "DeleteMe"}).get_json()
        uid = c["user"]["id"]
        r = self.client.delete(f"/api/settings/users/{uid}")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["deleted"])
        # Second delete 404.
        r = self.client.delete(f"/api/settings/users/{uid}")
        self.assertEqual(r.status_code, 404)

    def test_existing_owners_endpoint_still_active_only(self):
        """/api/owners (read-only public surface) should still return
        active rows only — deactivating shouldn't strand dropdowns
        with ex-employees."""
        c = self.client.post("/api/settings/users",
                                json={"name": "OnlyActive"}).get_json()
        self.client.patch(f"/api/settings/users/{c['user']['id']}",
                            json={"active": False})
        r = self.client.get("/api/owners")
        names = [o["name"] for o in r.get_json()["owners"]]
        self.assertNotIn("OnlyActive", names)


if __name__ == "__main__":
    unittest.main()
