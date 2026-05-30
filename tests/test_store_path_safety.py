"""v1.0.0dv - path-hardening for the two-segment note stores.

lead_contact_notes_store and partner_notes_store build a filename from
two id segments. The second segment (contact_id) was previously
interpolated raw; it is now slugified like the first, so a hostile path
segment cannot escape the store directory.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lead_contact_notes_store as lcn  # noqa: E402
import partner_notes_store as pn  # noqa: E402


class NoteStorePathSafetyTests(unittest.TestCase):
    def _assert_safe(self, store, a: str, b: str):
        p = store._path(a, b)
        # File lands directly in the store dir, with no traversal.
        self.assertEqual(p.parent, store._store_dir())
        self.assertNotIn("..", p.name)
        self.assertNotIn("/", p.name)
        self.assertNotIn("\\", p.name)

    def test_lead_contact_notes_hostile_contact_id(self):
        self._assert_safe(lcn, "lead-1", "../../etc/passwd")
        self._assert_safe(lcn, "lead-1", "..%5C..%5Cpwned")

    def test_partner_notes_hostile_contact_id(self):
        self._assert_safe(pn, "partner-1", "../../etc/passwd")
        self._assert_safe(pn, "partner-1", "..%5C..%5Cpwned")

    def test_normal_ids_unchanged_shape(self):
        # A real id (uuid4().hex[:12]) is lowercase hex and survives
        # slugify unchanged, so existing note files are not orphaned.
        cid = "a1b2c3d4e5f6"
        p = lcn._path("lead-1", cid)
        self.assertIn(cid, p.name)


if __name__ == "__main__":
    unittest.main()
