"""v1.0.0cg — pin the new shared helpers.

json_file_store + contact_cadence factored out duplication that the
audit caught. These tests:

1. Confirm the helper module's public API behaves as documented.
2. Verify the existing stores (contacts_store, partner_contacts_store)
   still expose the same cadence functions by re-export — no
   callers downstream broke.
3. Pin the v1.0.0cg drift fix: partners_store._now() now returns
   second-precision timestamps, consistent with every other store.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# -----------------------------------------------------------------
# 1. json_file_store helpers
# -----------------------------------------------------------------

class JsonFileStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        sys.modules.pop("json_file_store", None)
        import json_file_store
        self.jfs = json_file_store

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_now_iso_seconds_precision(self):
        s = self.jfs.now_iso()
        # ISO-Z with no fractional seconds.
        self.assertRegex(s, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertNotIn(".", s)

    def test_new_id_short_and_long(self):
        self.assertEqual(len(self.jfs.new_id(short=True)), 10)
        self.assertEqual(len(self.jfs.new_id(short=False)), 32)
        # Hex alphabet only.
        self.assertRegex(self.jfs.new_id(), r"^[0-9a-f]+$")

    def test_slugify_basic(self):
        self.assertEqual(self.jfs.slugify("Foo Bar"), "foo-bar")
        self.assertEqual(self.jfs.slugify("  Hello!  WORLD  "), "hello-world")
        self.assertEqual(self.jfs.slugify(""), "unknown")
        self.assertEqual(self.jfs.slugify("", fallback="custom"), "custom")

    def test_safe_id_accepts_safe(self):
        self.assertEqual(self.jfs.safe_id("abc123"), "abc123")
        self.assertEqual(self.jfs.safe_id("uuid-with_underscore-1"),
                          "uuid-with_underscore-1")

    def test_safe_id_rejects_traversal(self):
        for bad in ("../etc/passwd", "..", "a/b", "a\\b",
                     "", "a b", None, 42):
            with self.assertRaises((ValueError, TypeError)):
                self.jfs.safe_id(bad)

    def test_safe_id_custom_error_class(self):
        class MyError(RuntimeError):
            pass
        with self.assertRaises(MyError):
            self.jfs.safe_id("bad/path", error_cls=MyError)

    def test_store_dir_uses_env_override(self):
        override = os.path.join(self.tmp, "custom_loc")
        os.environ["MY_TEST_STORE_DIR"] = override
        try:
            d = self.jfs.store_dir("default_name",
                                      env_var="MY_TEST_STORE_DIR")
            self.assertEqual(str(d), override)
            self.assertTrue(d.is_dir())
        finally:
            os.environ.pop("MY_TEST_STORE_DIR", None)

    def test_load_list_missing_returns_empty(self):
        self.assertEqual(self.jfs.load_list(Path(self.tmp) / "nope.json"), [])

    def test_load_list_round_trip(self):
        p = Path(self.tmp) / "x.json"
        self.jfs.write_json(p, [{"a": 1}, {"b": 2}])
        self.assertEqual(self.jfs.load_list(p), [{"a": 1}, {"b": 2}])

    def test_load_dict_round_trip(self):
        p = Path(self.tmp) / "y.json"
        self.jfs.write_json(p, {"k": "v"})
        self.assertEqual(self.jfs.load_dict(p), {"k": "v"})
        self.assertIsNone(self.jfs.load_dict(Path(self.tmp) / "nope.json"))

    def test_load_returns_empty_on_corrupt_json(self):
        p = Path(self.tmp) / "bad.json"
        p.write_text("{not json}")
        self.assertEqual(self.jfs.load_list(p), [])
        self.assertIsNone(self.jfs.load_dict(p))


# -----------------------------------------------------------------
# 2. contact_cadence shared logic — verify both stores re-export it
# -----------------------------------------------------------------

class ContactCadenceShimTests(unittest.TestCase):
    def setUp(self):
        sys.modules.pop("contact_cadence", None)
        sys.modules.pop("contacts_store", None)
        sys.modules.pop("partner_contacts_store", None)

    def test_contacts_store_reexports_cadence(self):
        import contacts_store, contact_cadence
        # The reference is the same function object — true shim, not copy.
        self.assertIs(contacts_store.annotate_touch_state,
                       contact_cadence.annotate_touch_state)
        self.assertIs(contacts_store._parse_iso, contact_cadence.parse_iso)

    def test_partner_contacts_store_reexports_cadence(self):
        import partner_contacts_store, contact_cadence
        self.assertIs(partner_contacts_store.annotate_touch_state,
                       contact_cadence.annotate_touch_state)
        self.assertIs(partner_contacts_store._parse_iso,
                       contact_cadence.parse_iso)

    def test_annotate_overdue_basic(self):
        import contact_cadence
        c = {"cadence_days": 30, "last_touched_at": "2020-01-01T00:00:00Z",
             "added_at": "2020-01-01T00:00:00Z"}
        annotated = contact_cadence.annotate_touch_state(c)
        self.assertTrue(annotated["overdue"])
        self.assertLess(annotated["days_until_due"], 0)
        self.assertIsNotNone(annotated["next_touch_due"])

    def test_annotate_never_touched_no_added(self):
        import contact_cadence
        c = {"cadence_days": 30}
        annotated = contact_cadence.annotate_touch_state(c)
        self.assertFalse(annotated["overdue"])
        self.assertIsNone(annotated["next_touch_due"])

    def test_annotate_default_cadence_when_missing(self):
        import contact_cadence
        c = {"added_at": "2020-01-01T00:00:00Z"}  # no cadence_days
        annotated = contact_cadence.annotate_touch_state(c)
        # Default cadence = 30 days; baseline 2020 → overdue.
        self.assertTrue(annotated["overdue"])


# -----------------------------------------------------------------
# 3. partners_store timestamp drift fix
# -----------------------------------------------------------------

class PartnersStoreTimestampPrecisionTests(unittest.TestCase):
    def test_now_is_second_precision(self):
        sys.modules.pop("partners_store", None)
        import partners_store
        s = partners_store._now()
        # No fractional seconds — matches every other store now.
        self.assertRegex(s, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertNotIn(".", s)


if __name__ == "__main__":
    unittest.main()
