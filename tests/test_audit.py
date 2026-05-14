"""Audit log smoke tests."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jsonl")
        self.tmp.close()
        os.environ["AUDIT_LOG_PATH"] = self.tmp.name

    def tearDown(self):
        os.environ.pop("AUDIT_LOG_PATH", None)
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_log_and_read_roundtrip(self):
        import audit
        audit.log_event("qualified", company="Deliveroo", score=9.4, status="qualify_in")
        audit.log_event("notion_sync", company="Deliveroo", action="created")
        rows = audit.read_events(limit=10)
        self.assertEqual(len(rows), 2)
        # newest-first
        self.assertEqual(rows[0]["type"], "notion_sync")
        self.assertEqual(rows[1]["company"], "Deliveroo")
        # well-formed JSON on disk
        with open(self.tmp.name) as f:
            for line in f:
                json.loads(line)

    def test_summarise(self):
        import audit
        audit.log_event("qualified", company="A", status="qualify_in")
        audit.log_event("qualified", company="B", status="borderline")
        audit.log_event("qualified", company="A", status="qualify_in")
        audit.log_event("notion_sync", company="A", action="created")
        rows = audit.read_events(limit=100)
        s = audit.summarise(rows)
        self.assertEqual(s["qualified_in"], 2)
        self.assertEqual(s["borderline"], 1)
        self.assertEqual(s["by_type"]["qualified"], 3)
        self.assertEqual(s["by_type"]["notion_sync"], 1)
        # A should be top by event count
        self.assertEqual(s["top_companies"][0][0], "A")

    def test_log_event_never_raises_on_bad_path(self):
        """If the file can't be written, log_event swallows the error."""
        import audit
        os.environ["AUDIT_LOG_PATH"] = "/nonexistent_dir/that/does/not/exist/audit.jsonl"
        # mkdir will try to create — but parent dirs are non-writable in many cases.
        # Even if it succeeds, the open should be safe. We only care that no exception bubbles.
        try:
            audit.log_event("qualified", company="X")
        except Exception as e:
            self.fail(f"log_event raised: {e}")


if __name__ == "__main__":
    unittest.main()
