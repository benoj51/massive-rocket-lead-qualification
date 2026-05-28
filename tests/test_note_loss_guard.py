"""v1.0.0dp — guard against removing existing notes.

v1.0.0cu made every note/call write ATOMIC, which stops a crash from
*creating* a half-written file. It left the read-side hole open: the
load path returned [] on a file that EXISTS but can't be parsed, so the
very next add/delete loaded [], appended, and wrote it back -- silently
destroying recoverable history.

These tests pin the fix:
  - json_file_store gains a corruption-aware loader + a .bak sidecar.
  - the three human-authored history stores (lead_contact_notes,
    partner_notes, calls) route reads through the lenient loader and
    mutations through the STRICT loader, so a corrupt read can never
    clobber existing notes.
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

import json_file_store as jfs


class LoadListSafeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _p(self, name="store.json"):
        return self.tmp / name

    def test_missing_file_is_empty_not_corrupt(self):
        # A genuinely absent file is an empty store, never an error,
        # even under strict mode (mutation on a brand-new key).
        self.assertEqual(jfs.load_list_safe(self._p()), [])
        self.assertEqual(jfs.load_list_safe(self._p(), strict=True), [])

    def test_valid_list_round_trips(self):
        p = self._p()
        jfs.write_json(p, [{"id": "1"}])
        self.assertEqual(jfs.load_list_safe(p, strict=True), [{"id": "1"}])

    def test_empty_file_is_empty_list(self):
        p = self._p()
        p.write_text("")
        self.assertEqual(jfs.load_list_safe(p, strict=True), [])

    def test_corrupt_recovers_from_backup(self):
        p = self._p()
        # A good .bak sidecar exists alongside a corrupt primary.
        jfs.write_json(jfs._bak_path(p), [{"id": "kept"}])
        p.write_text("{ not json")
        # Even strict mode returns the recovered list rather than raising,
        # because the data is not actually lost.
        self.assertEqual(jfs.load_list_safe(p, strict=True), [{"id": "kept"}])
        self.assertEqual(jfs.load_list_safe(p), [{"id": "kept"}])

    def test_corrupt_no_backup_strict_raises_lenient_empty(self):
        p = self._p()
        p.write_text("{ not json")
        # Lenient (read) -> degrade to [].
        self.assertEqual(jfs.load_list_safe(p), [])
        # Strict (mutation) -> refuse, so the caller never overwrites it.
        with self.assertRaises(jfs.CorruptStoreError):
            jfs.load_list_safe(p, strict=True)

    def test_non_list_payload_treated_as_corrupt(self):
        p = self._p()
        p.write_text('{"not": "a list"}')
        self.assertEqual(jfs.load_list_safe(p), [])
        with self.assertRaises(jfs.CorruptStoreError):
            jfs.load_list_safe(p, strict=True)


class WriteJsonBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_first_write_has_no_backup(self):
        p = self.tmp / "s.json"
        jfs.write_json_backup(p, [{"id": "1"}])
        self.assertFalse(jfs._bak_path(p).exists())
        self.assertEqual(jfs.load_list_safe(p), [{"id": "1"}])

    def test_second_write_snapshots_prior_state(self):
        p = self.tmp / "s.json"
        jfs.write_json_backup(p, [{"id": "1"}])
        jfs.write_json_backup(p, [{"id": "1"}, {"id": "2"}])
        # .bak holds the state BEFORE the second write.
        self.assertEqual(jfs.load_list_safe(jfs._bak_path(p)), [{"id": "1"}])

    def test_corrupt_primary_never_clobbers_good_backup(self):
        p = self.tmp / "s.json"
        jfs.write_json_backup(p, [{"id": "1"}])          # primary=[1]
        jfs.write_json_backup(p, [{"id": "1"}, {"id": "2"}])  # .bak=[1]
        p.write_text("garbage")                          # primary corrupt
        # Writing again must NOT overwrite the good .bak with garbage.
        jfs.write_json_backup(p, [{"id": "3"}])
        self.assertEqual(jfs.load_list_safe(jfs._bak_path(p)), [{"id": "1"}])

    def test_backup_file_only_snapshots_readable(self):
        p = self.tmp / "s.json"
        self.assertFalse(jfs.backup_file(p))             # missing
        jfs.write_json(p, [{"id": "1"}])
        self.assertTrue(jfs.backup_file(p))              # readable
        self.assertEqual(jfs.load_list_safe(jfs._bak_path(p)), [{"id": "1"}])
        p.write_text("garbage")
        self.assertFalse(jfs.backup_file(p))             # corrupt -> skip


class _StoreGuardMixin:
    """Shared regression: a corrupt read must NOT wipe existing notes.

    Subclasses set `mod`, `add`, `read`, `path`, `err` for their store.
    """

    def _corrupt(self, path):
        path.write_text("{ this is not valid json at all")

    def test_corrupt_then_add_recovers_not_wipes(self):
        # Two saves: primary=[n1,n2], .bak=[n1].
        self.add("n1")
        self.add("n2")
        p = self.path()
        self.assertTrue(p.exists())
        self._corrupt(p)
        # The pre-fix bug: this add would load [], append, write [n3] and
        # destroy n1 + n2. Post-fix it recovers the last good state ([n1])
        # from .bak, so the EXISTING note survives.
        self.add("n3")
        contents = {n["content"] for n in self.read()}
        self.assertIn("n1", contents)   # existing note preserved
        self.assertIn("n3", contents)   # new note saved

    def test_unrecoverable_corruption_refuses_to_overwrite(self):
        # Single save -> primary exists, NO .bak yet.
        self.add("only")
        p = self.path()
        self._corrupt(p)
        before = p.read_text()
        # No recoverable copy -> the store refuses rather than clobber.
        with self.assertRaises(self.err):
            self.add("new")
        # The bytes on disk are untouched, so a human can recover them.
        self.assertEqual(p.read_text(), before)


class LeadContactNotesGuardTests(_StoreGuardMixin, unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["LEAD_CONTACT_NOTES_STORE_DIR"] = self.tmp
        for mod in ("lead_contact_notes_store", "project_store"):
            sys.modules.pop(mod, None)
        import lead_contact_notes_store as s
        self.s = s
        self.err = s.LeadContactNotesStoreError
        self._lead, self._contact = "lead-guard", "cX"

    def tearDown(self):
        os.environ.pop("LEAD_CONTACT_NOTES_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add(self, content):
        return self.s.add_note(self._lead, self._contact, {"content": content})

    def read(self):
        return self.s.list_notes(self._lead, self._contact)

    def path(self):
        return self.s._path(self._lead, self._contact)


class PartnerNotesGuardTests(_StoreGuardMixin, unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["PARTNER_NOTES_STORE_DIR"] = self.tmp
        for mod in ("partner_notes_store", "project_store"):
            sys.modules.pop(mod, None)
        import partner_notes_store as s
        self.s = s
        self.err = s.PartnerNotesStoreError
        self._partner, self._contact = "partner-guard", "cX"

    def tearDown(self):
        os.environ.pop("PARTNER_NOTES_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add(self, content):
        return self.s.add_note(self._partner, self._contact, {"content": content})

    def read(self):
        return self.s.list_notes(self._partner, self._contact)

    def path(self):
        return self.s._path(self._partner, self._contact)


class CallsStoreGuardTests(_StoreGuardMixin, unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["CALLS_STORE_DIR"] = self.tmp
        for mod in ("calls_store", "project_store"):
            sys.modules.pop(mod, None)
        import calls_store as s
        self.s = s
        self.err = s.CallsStoreError
        self._lead = "lead-guard"

    def tearDown(self):
        os.environ.pop("CALLS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add(self, content):
        return self.s.add_call(self._lead, {"content": content})

    def read(self):
        return self.s.list_calls(self._lead)

    def path(self):
        return self.s._path(self._lead)


class CascadeDeleteLeavesRecoverableBackupTests(unittest.TestCase):
    """An accidental contact deletion cascades the notes file away, but a
    .bak sidecar is left behind so it stays recoverable -- while
    list_notes still correctly reports the cascade as empty."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["LEAD_CONTACT_NOTES_STORE_DIR"] = self.tmp
        for mod in ("lead_contact_notes_store", "project_store"):
            sys.modules.pop(mod, None)
        import lead_contact_notes_store as s
        self.s = s

    def tearDown(self):
        os.environ.pop("LEAD_CONTACT_NOTES_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cascade_delete_is_recoverable(self):
        self.s.add_note("yum", "c1", {"content": "important"})
        p = self.s._path("yum", "c1")
        self.assertTrue(self.s.delete_all_for_contact("yum", "c1"))
        # Live file gone -> reads are empty (cascade semantics intact).
        self.assertFalse(p.exists())
        self.assertEqual(self.s.list_notes("yum", "c1"), [])
        # But the snapshot survives for manual recovery.
        self.assertEqual(jfs.load_list_safe(jfs._bak_path(p))[0]["content"],
                         "important")


if __name__ == "__main__":
    unittest.main()
