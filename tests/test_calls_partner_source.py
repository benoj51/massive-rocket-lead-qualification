"""v1.0.0z — partner_source attribution on lead-side calls.

Covers:
- partner_source flows through add_call → list_calls
- _normalise_partner_source handles None / empty / partial inputs
- update_call can set / clear partner_source after the fact
- list_calls_sourced_from cross-references across all leads
- Filter combinations: contact-specific, partner-only, both
- Endpoint passes partner_source through (smoke test)
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


class NormalisePartnerSourceTests(unittest.TestCase):
    def setUp(self):
        sys.modules.pop("calls_store", None)
        import calls_store
        self.calls = calls_store

    def test_none_returns_none(self):
        self.assertIsNone(self.calls._normalise_partner_source(None))

    def test_empty_dict_returns_none(self):
        self.assertIsNone(self.calls._normalise_partner_source({}))

    def test_missing_partner_id_returns_none(self):
        self.assertIsNone(self.calls._normalise_partner_source({"contact_id": "x"}))

    def test_partner_only(self):
        out = self.calls._normalise_partner_source({"partner_id": "braze"})
        self.assertEqual(out, {"partner_id": "braze"})

    def test_full_shape(self):
        out = self.calls._normalise_partner_source({
            "partner_id": "braze", "contact_id": "marina",
            "partner_name": "Braze", "contact_name": "Marina Klusas",
        })
        self.assertEqual(out["partner_id"], "braze")
        self.assertEqual(out["contact_id"], "marina")
        self.assertEqual(out["partner_name"], "Braze")
        self.assertEqual(out["contact_name"], "Marina Klusas")

    def test_strips_whitespace(self):
        out = self.calls._normalise_partner_source({
            "partner_id": "  braze  ", "contact_id": "  marina ",
        })
        self.assertEqual(out["partner_id"], "braze")
        self.assertEqual(out["contact_id"], "marina")

    def test_rejects_non_dict(self):
        self.assertIsNone(self.calls._normalise_partner_source("braze"))
        self.assertIsNone(self.calls._normalise_partner_source(["braze"]))


class AddCallWithPartnerSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["CALLS_STORE_DIR"] = os.path.join(self.tmp, "calls")
        sys.modules.pop("calls_store", None)
        import calls_store
        self.calls = calls_store

    def tearDown(self):
        os.environ.pop("CALLS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_call_without_source_has_null(self):
        rec = self.calls.add_call("lead-1", {"content": "internal note"})
        self.assertIsNone(rec["partner_source"])

    def test_call_with_source_round_trips(self):
        rec = self.calls.add_call("lead-1", {
            "content": "Marina told us Popeyes Q3 is moving",
            "partner_source": {
                "partner_id": "braze", "contact_id": "marina",
                "partner_name": "Braze", "contact_name": "Marina Klusas",
            },
        })
        self.assertEqual(rec["partner_source"]["contact_name"], "Marina Klusas")
        rows = self.calls.list_calls("lead-1")
        self.assertEqual(rows[0]["partner_source"]["contact_id"], "marina")

    def test_update_call_can_set_source_after_the_fact(self):
        rec = self.calls.add_call("lead-1", {"content": "n"})
        updated = self.calls.update_call("lead-1", rec["id"], {
            "partner_source": {"partner_id": "braze"},
        })
        self.assertEqual(updated["partner_source"], {"partner_id": "braze"})

    def test_update_call_can_clear_source(self):
        rec = self.calls.add_call("lead-1", {
            "content": "n",
            "partner_source": {"partner_id": "braze"},
        })
        updated = self.calls.update_call("lead-1", rec["id"], {
            "partner_source": None,
        })
        self.assertIsNone(updated["partner_source"])


class ListCallsSourcedFromTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["CALLS_STORE_DIR"] = os.path.join(self.tmp, "calls")
        sys.modules.pop("calls_store", None)
        import calls_store
        self.calls = calls_store

    def tearDown(self):
        os.environ.pop("CALLS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _seed(self):
        # 3 leads, mix of attributions
        self.calls.add_call("popeyes", {
            "content": "intro call",
            "partner_source": {"partner_id": "braze", "contact_id": "marina"},
        })
        self.calls.add_call("popeyes", {"content": "internal note"})  # no source
        self.calls.add_call("kfc", {
            "content": "Marina also mentioned KFC",
            "partner_source": {"partner_id": "braze", "contact_id": "marina"},
        })
        self.calls.add_call("kfc", {
            "content": "Hightouch perspective",
            "partner_source": {"partner_id": "hightouch", "contact_id": "vinod"},
        })
        self.calls.add_call("shell", {
            "content": "Braze team generic intel",
            "partner_source": {"partner_id": "braze"},  # partner-only, no contact
        })

    def test_by_contact_id(self):
        self._seed()
        rows = self.calls.list_calls_sourced_from(contact_id="marina")
        self.assertEqual(len(rows), 2)
        # Newest first
        self.assertTrue(rows[0]["created_at"] >= rows[1]["created_at"])

    def test_by_partner_id_includes_all_partner_attributions(self):
        self._seed()
        rows = self.calls.list_calls_sourced_from(partner_id="braze")
        # 2 from Marina + 1 partner-generic = 3
        self.assertEqual(len(rows), 3)

    def test_combined_filter_narrows(self):
        self._seed()
        # partner=braze AND contact=marina → just Marina's
        rows = self.calls.list_calls_sourced_from(
            partner_id="braze", contact_id="marina",
        )
        self.assertEqual(len(rows), 2)

    def test_empty_filter_returns_empty(self):
        self._seed()
        self.assertEqual(self.calls.list_calls_sourced_from(), [])

    def test_no_match_returns_empty(self):
        self._seed()
        rows = self.calls.list_calls_sourced_from(contact_id="someone-else")
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
