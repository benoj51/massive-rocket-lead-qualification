"""v0.10.0 Phase A — accounts_graph: parent → brand relationships."""
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


class AccountsGraphTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["ACCOUNTS_GRAPH_PATH"] = os.path.join(self.tmp, "graph.json")
        for mod in ("accounts_graph", "project_store"):
            sys.modules.pop(mod, None)

    def tearDown(self):
        os.environ.pop("ACCOUNTS_GRAPH_PATH", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_graph_returns_none_for_parent(self):
        import accounts_graph
        self.assertIsNone(accounts_graph.parent_of("kfc"))
        self.assertEqual(accounts_graph.children_of("yum"), [])
        self.assertFalse(accounts_graph.is_parent("yum"))

    def test_set_and_read_parent(self):
        import accounts_graph
        res = accounts_graph.set_parent("kfc", "yum_brands")
        self.assertEqual(res["lead_id"], "kfc")
        self.assertEqual(res["parent_account_id"], "yum_brands")
        self.assertEqual(accounts_graph.parent_of("kfc"), "yum_brands")
        self.assertTrue(accounts_graph.is_parent("yum_brands"))

    def test_children_of_lists_all_brands(self):
        import accounts_graph
        accounts_graph.set_parent("kfc", "yum_brands")
        accounts_graph.set_parent("pizza_hut", "yum_brands")
        accounts_graph.set_parent("taco_bell", "yum_brands")
        kids = accounts_graph.children_of("yum_brands")
        self.assertEqual(set(kids), {"kfc", "pizza_hut", "taco_bell"})

    def test_unlink_via_set_parent_none(self):
        import accounts_graph
        accounts_graph.set_parent("kfc", "yum_brands")
        accounts_graph.set_parent("kfc", None)
        self.assertIsNone(accounts_graph.parent_of("kfc"))
        self.assertFalse(accounts_graph.is_parent("yum_brands"))

    def test_self_reference_blocked(self):
        import accounts_graph
        with self.assertRaises(accounts_graph.GraphError):
            accounts_graph.set_parent("yum_brands", "yum_brands")

    def test_one_level_rule_blocks_grandchildren(self):
        """A parent (with children) cannot itself become a child."""
        import accounts_graph
        accounts_graph.set_parent("kfc", "yum_brands")  # Yum is now a parent
        with self.assertRaises(accounts_graph.GraphError):
            accounts_graph.set_parent("yum_brands", "some_holdco")

    def test_can_delete_parent_with_no_children(self):
        import accounts_graph
        ok, blockers = accounts_graph.can_delete("yum_brands")
        self.assertTrue(ok)
        self.assertEqual(blockers, [])

    def test_can_delete_blocked_when_children_exist(self):
        import accounts_graph
        accounts_graph.set_parent("kfc", "yum_brands")
        accounts_graph.set_parent("pizza_hut", "yum_brands")
        ok, blockers = accounts_graph.can_delete("yum_brands")
        self.assertFalse(ok)
        self.assertEqual(set(blockers), {"kfc", "pizza_hut"})

    def test_unlink_all_children(self):
        import accounts_graph
        accounts_graph.set_parent("kfc", "yum_brands")
        accounts_graph.set_parent("pizza_hut", "yum_brands")
        unlinked = accounts_graph.unlink_all_children("yum_brands")
        self.assertEqual(set(unlinked), {"kfc", "pizza_hut"})
        self.assertIsNone(accounts_graph.parent_of("kfc"))
        self.assertIsNone(accounts_graph.parent_of("pizza_hut"))
        self.assertFalse(accounts_graph.is_parent("yum_brands"))

    def test_slug_normalisation_on_input(self):
        """Inputs are slugified, so URL-style or whitespaced IDs work."""
        import accounts_graph
        accounts_graph.set_parent("KFC Corporation", "Yum! Brands, Inc.")
        # Both ends get slugified consistently.
        self.assertEqual(
            accounts_graph.parent_of("kfc corporation"),
            accounts_graph.parent_of("KFC_Corporation"),
        )
        self.assertEqual(
            accounts_graph.parent_of("KFC Corporation"),
            "yum_brands_inc",
        )

    def test_full_graph_returns_complete_map(self):
        import accounts_graph
        accounts_graph.set_parent("kfc", "yum_brands")
        accounts_graph.set_parent("pizza_hut", "yum_brands")
        accounts_graph.set_parent("burger_king", "rbi")
        g = accounts_graph.full_graph()
        self.assertEqual(g, {
            "kfc": "yum_brands",
            "pizza_hut": "yum_brands",
            "burger_king": "rbi",
        })

    def test_persistence_across_process_restart(self):
        """File is written, a fresh import sees it."""
        import accounts_graph
        accounts_graph.set_parent("kfc", "yum_brands")
        # Simulate a fresh process by re-importing.
        sys.modules.pop("accounts_graph", None)
        import accounts_graph as fresh
        self.assertEqual(fresh.parent_of("kfc"), "yum_brands")


if __name__ == "__main__":
    unittest.main()
