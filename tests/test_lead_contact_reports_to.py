"""v1.0.0ar — lead-side contacts gain reports_to_id for the Account org chart.

Mirrors the partner_contacts_store reports_to_id field, used by the
in-drawer Account view's org-chart renderer to build a vertical tree
of stakeholders for a single account.
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


class LeadContactReportsToTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["CONTACTS_STORE_DIR"] = self.tmp
        sys.modules.pop("contacts_store", None)
        import contacts_store
        self.store = contacts_store

    def tearDown(self):
        os.environ.pop("CONTACTS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_is_none(self):
        c = self.store.save_contact("acme",
                                      {"name": "Jane Doe", "title": "VP"})
        self.assertIsNone(c["reports_to_id"])

    def test_persists_reports_to_id(self):
        boss = self.store.save_contact("acme",
                                         {"name": "Boss", "title": "CMO"})
        self.store.save_contact("acme",
                                  {"name": "Jane", "title": "Mgr",
                                   "reports_to_id": boss["id"]})
        contacts = self.store.list_contacts("acme")
        jane = next(c for c in contacts if c["name"] == "Jane")
        self.assertEqual(jane["reports_to_id"], boss["id"])

    def test_empty_string_normalises_to_none(self):
        """Empty form fields land as "" — normalise to None so the
        chart treats them as root nodes, not as a non-matching FK."""
        c = self.store.save_contact("acme",
                                      {"name": "Top", "reports_to_id": ""})
        self.assertIsNone(c["reports_to_id"])

    def test_whitespace_normalises_to_none(self):
        c = self.store.save_contact("acme",
                                      {"name": "Top", "reports_to_id": "   "})
        self.assertIsNone(c["reports_to_id"])

    def test_update_clears_reports_to(self):
        boss = self.store.save_contact("acme", {"name": "Boss"})
        jane = self.store.save_contact("acme",
                                         {"name": "Jane",
                                          "reports_to_id": boss["id"]})
        # Re-save with reports_to_id cleared (mimics the form sending null).
        updated = self.store.save_contact("acme", {
            "id": jane["id"], "name": "Jane",
            "reports_to_id": None,
        })
        self.assertIsNone(updated["reports_to_id"])

    def test_round_trip_via_list(self):
        """End-to-end: save with reports_to_id, list, check the field
        survives the JSON serialise / parse cycle."""
        a = self.store.save_contact("acme", {"name": "A"})
        b = self.store.save_contact("acme",
                                       {"name": "B", "reports_to_id": a["id"]})
        c = self.store.save_contact("acme",
                                       {"name": "C", "reports_to_id": b["id"]})
        contacts = self.store.list_contacts("acme")
        by_name = {x["name"]: x for x in contacts}
        self.assertIsNone(by_name["A"]["reports_to_id"])
        self.assertEqual(by_name["B"]["reports_to_id"], a["id"])
        self.assertEqual(by_name["C"]["reports_to_id"], b["id"])


if __name__ == "__main__":
    unittest.main()
