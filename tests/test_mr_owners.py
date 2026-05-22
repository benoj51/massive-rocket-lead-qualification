"""v1.0.0o — MR owners single-source-of-truth tests."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class MrOwnersModuleTests(unittest.TestCase):
    def test_module_loads(self):
        import mr_owners
        self.assertTrue(len(mr_owners.OWNERS) >= 1)

    def test_every_owner_has_required_fields(self):
        import mr_owners
        required = {"name", "role", "region", "email", "active"}
        for o in mr_owners.OWNERS:
            self.assertTrue(required.issubset(o.keys()),
                             f"{o.get('name')} missing keys: {required - o.keys()}")

    def test_names_are_unique(self):
        import mr_owners
        names = [o["name"] for o in mr_owners.OWNERS]
        self.assertEqual(len(names), len(set(names)),
                          "Duplicate owner names")

    def test_emails_lowercase_or_blank(self):
        """Sonal Dalia's email is intentionally blank for now; everyone
        else should have a valid lowercase email."""
        import mr_owners
        for o in mr_owners.OWNERS:
            if o["email"]:
                self.assertEqual(o["email"], o["email"].lower(),
                                  f"{o['name']}'s email isn't lowercase")
                self.assertIn("@", o["email"], f"{o['name']}'s email looks invalid")

    def test_known_team_members_present(self):
        """Spot-check that the names Ben supplied are all in the roster."""
        import mr_owners
        names = {o["name"] for o in mr_owners.OWNERS}
        for expected in (
            "Thierry Sequeira", "Daniel Craig", "Ben Ojuolape",
            "Daniel Ergueta", "Tsveti Grncarova", "Jorge Arrechea",
            "Marija Veljanova", "Darren Addy", "Claudia Lima",
            "Sonal Dalia", "Jamie MacDow", "Lea",
        ):
            self.assertIn(expected, names, f"Missing: {expected}")

    def test_list_owners_filters_inactive(self):
        import mr_owners
        active = mr_owners.list_owners(active_only=True)
        all_o = mr_owners.list_owners(active_only=False)
        self.assertLessEqual(len(active), len(all_o))
        # Right now everyone is active — both lists should match.
        self.assertEqual(len(active), len(all_o))

    def test_get_owner_lookup(self):
        import mr_owners
        ben = mr_owners.get_owner("Ben Ojuolape")
        self.assertIsNotNone(ben)
        self.assertEqual(ben["region"], "UK → US")
        # Case-insensitive
        self.assertIsNotNone(mr_owners.get_owner("ben ojuolape"))
        # Missing
        self.assertIsNone(mr_owners.get_owner("Not A Person"))

    def test_names_helper(self):
        import mr_owners
        names = mr_owners.names()
        self.assertIsInstance(names, list)
        self.assertIn("Ben Ojuolape", names)


class OwnersEndpointTests(unittest.TestCase):
    def setUp(self):
        self._env_set: dict[str, str | None] = {}
        for k, v in {
            "SKIP_NOTION_BOOT": "1",
            "SKIP_COMMAND_CENTRE_SEED": "1",
        }.items():
            self._env_set[k] = os.environ.get(k)
            os.environ[k] = v
        for mod in ("server", "mr_owners"):
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

    def test_endpoint_returns_full_roster(self):
        r = self.client.get("/api/owners")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        names = {o["name"] for o in data["owners"]}
        self.assertIn("Ben Ojuolape", names)
        self.assertIn("Thierry Sequeira", names)
        self.assertIn("Claudia Lima", names)

    def test_endpoint_omits_inactive(self):
        """list_owners(active_only=True) should be what the endpoint returns."""
        import mr_owners
        expected = mr_owners.list_owners(active_only=True)
        r = self.client.get("/api/owners")
        self.assertEqual(len(r.get_json()["owners"]), len(expected))


if __name__ == "__main__":
    unittest.main()
