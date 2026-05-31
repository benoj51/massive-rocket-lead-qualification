"""v1.0.0dw - atomic writes + .bak recovery for the JSON stores.

The store-write migration routes every store's single write through the
atomic helpers in json_file_store (tempfile + fsync + os.replace), so a
crash mid-write can no longer truncate a store file. The human-authored
stores additionally use write_json_backup, which keeps a `.bak` sidecar
of the prior good state so a corrupted primary is recoverable.

These tests prove the highest-value human stores are actually wired to
write_json_backup: a plain atomic write would leave no sidecar.
"""
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


def _bak(p: Path) -> Path:
    return p.with_name(p.name + ".bak")


class PartnersStoreBackupTests(unittest.TestCase):
    """partners_store is a single-file roster: one bad write would lose
    every partner. It must keep a .bak."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "partners.json")
        os.environ["PARTNERS_STORE_PATH"] = self.path
        sys.modules.pop("partners_store", None)
        import partners_store
        self.store = partners_store

    def tearDown(self):
        os.environ.pop("PARTNERS_STORE_PATH", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_second_write_leaves_recoverable_bak(self):
        self.store.save_partner({"name": "Braze"})
        self.store.save_partner({"name": "Hightouch"})
        bak = _bak(Path(self.path))
        self.assertTrue(bak.exists(),
                        "single-file roster store must keep a .bak sidecar")
        # The sidecar is a parseable JSON list (the prior good state).
        recovered = json.loads(bak.read_text())
        self.assertIsInstance(recovered, list)
        self.assertTrue(recovered, "sidecar should hold the prior write")


class ContactsStoreBackupTests(unittest.TestCase):
    """contacts_store is per-lead, human-authored. Each file must keep a
    .bak of its prior contents."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["CONTACTS_STORE_DIR"] = self.tmp
        sys.modules.pop("contacts_store", None)
        import contacts_store
        self.store = contacts_store

    def tearDown(self):
        os.environ.pop("CONTACTS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_second_write_leaves_recoverable_bak(self):
        self.store.save_contact("lead-1", {"id": "c1", "name": "Ada Lovelace"})
        self.store.save_contact("lead-1", {"id": "c2", "name": "Alan Turing"})
        primary = self.store._path("lead-1")
        bak = _bak(primary)
        self.assertTrue(bak.exists(),
                        "per-lead human store must keep a .bak sidecar")
        # Primary holds both contacts and still parses cleanly (atomic write).
        rows = json.loads(primary.read_text())
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
