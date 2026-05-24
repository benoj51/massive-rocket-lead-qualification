"""v1.0.0aq — Notion update_page should recover when a property is missing.

Ben hit "Save failed: Notion POST /pages 400: ... Sourced For is not a
property that exists." His DB pre-dated v1.0.0z and lacked the
"Sourced For" column. Without the recovery path, a single missing
property 400s the whole save and the AE loses every edit in the batch.

The fix: parse the error message, strip the offending property, retry
once. Boot self-heal also now creates the property on next deploy.

v1.0.0bp — recovery now returns (page, dropped_property_names) and
loops the retry so multiple missing properties can be stripped in one
save. Callers that previously got just a page dict need to unpack the
tuple.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from notion_sync import NotionSync, NotionSyncError  # noqa: E402


class MissingPropertyRecoveryTests(unittest.TestCase):
    def setUp(self):
        # NotionSync._request is the I/O boundary. We stub it so the
        # tests run with no network.
        self.sync = NotionSync.__new__(NotionSync)
        # Just enough attribute init for the methods we call.
        self.sync.database_id = "db123"
        self.sync.data_source_id = ""
        self.sync.api_key = "secret-test"

    def test_retry_after_missing_property_succeeds(self):
        """First call 400s with "Sourced For is not a property"; second
        call (without the offending key) succeeds. The user's lead saves."""
        calls = []
        def fake_request(method, path, json_body=None):
            calls.append({"method": method, "path": path, "props": dict(json_body["properties"])})
            if "Sourced For" in json_body["properties"]:
                raise NotionSyncError(
                    'Notion PATCH /pages/abc 400: {"object":"error",'
                    '"status":400,"code":"validation_error","message":'
                    '"Sourced For is not a property that exists."}')
            # Retry succeeded
            return {"id": "abc", "url": "https://notion.so/abc"}
        with patch.object(self.sync, "_request", side_effect=fake_request):
            page, dropped = self.sync._patch_page_with_missing_property_recovery(
                "abc",
                {"Company": {"title": []}, "Sourced For": {"multi_select": []}},
            )
        # Two _request calls: first with all props, second without "Sourced For"
        self.assertEqual(len(calls), 2)
        self.assertIn("Sourced For", calls[0]["props"])
        self.assertNotIn("Sourced For", calls[1]["props"])
        self.assertIn("Company", calls[1]["props"])
        self.assertEqual(page["id"], "abc")
        # v1.0.0bp: dropped names are surfaced so callers can warn.
        self.assertEqual(dropped, ["Sourced For"])

    def test_retry_handles_multi_word_property_name(self):
        """Property names can have spaces ("Lead Summary", "Sourced
        For"). The parser handles them by matching greedily up to
        " is not a property"."""
        def fake_request(method, path, json_body=None):
            if "Lead Summary" in json_body["properties"]:
                raise NotionSyncError(
                    "Lead Summary is not a property that exists.")
            return {"id": "abc"}
        with patch.object(self.sync, "_request", side_effect=fake_request):
            page, dropped = self.sync._patch_page_with_missing_property_recovery(
                "abc",
                {"Lead Summary": {"rich_text": []}, "Company": {"title": []}},
            )
        self.assertEqual(page["id"], "abc")
        self.assertEqual(dropped, ["Lead Summary"])

    def test_other_400_errors_are_not_swallowed(self):
        """The recovery path is narrowly scoped — unrelated 400s
        (auth, malformed body, etc.) must propagate so the user sees
        the real failure, not a silent partial save."""
        def fake_request(method, path, json_body=None):
            raise NotionSyncError(
                'Notion PATCH /pages/abc 400: {"message":'
                '"body.parent should be defined."}')
        with patch.object(self.sync, "_request", side_effect=fake_request):
            with self.assertRaises(NotionSyncError):
                self.sync._patch_page_with_missing_property_recovery(
                    "abc", {"Company": {"title": []}})

    def test_second_attempt_failure_propagates(self):
        """If the retry's failure isn't a missing-property error, surface
        it — don't keep retrying, don't return a fake success."""
        attempts = {"n": 0}
        def fake_request(method, path, json_body=None):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise NotionSyncError("Sourced For is not a property that exists.")
            raise NotionSyncError("Database is read-only.")
        with patch.object(self.sync, "_request", side_effect=fake_request):
            with self.assertRaises(NotionSyncError) as ctx:
                self.sync._patch_page_with_missing_property_recovery(
                    "abc",
                    {"Sourced For": {"multi_select": []}, "Company": {"title": []}},
                )
        # The error surfaced is the second one (the real, non-recoverable problem)
        self.assertIn("read-only", str(ctx.exception))
        self.assertEqual(attempts["n"], 2)

    def test_parser_miss_propagates_original_error(self):
        """If we can't parse the property name out of a weird error
        format, don't risk a silent partial save — re-raise."""
        def fake_request(method, path, json_body=None):
            raise NotionSyncError("Random 400 with no recognizable shape.")
        with patch.object(self.sync, "_request", side_effect=fake_request):
            with self.assertRaises(NotionSyncError):
                self.sync._patch_page_with_missing_property_recovery(
                    "abc", {"Company": {"title": []}})

    def test_only_missing_property_returns_noop(self):
        """If stripping the missing property leaves nothing to send,
        return a no-op response shape rather than firing an empty PATCH
        (which Notion would also 400)."""
        def fake_request(method, path, json_body=None):
            raise NotionSyncError("Sourced For is not a property that exists.")
        with patch.object(self.sync, "_request", side_effect=fake_request) as mock_req:
            page, dropped = self.sync._patch_page_with_missing_property_recovery(
                "abc", {"Sourced For": {"multi_select": []}})
        # Only one call — recovery noticed there's nothing left to retry.
        self.assertEqual(mock_req.call_count, 1)
        self.assertEqual(page["id"], "abc")
        self.assertEqual(dropped, ["Sourced For"])

    # ---- v1.0.0bp: looped recovery + dropped_props surfacing -------

    def test_loops_through_multiple_missing_properties(self):
        """Two columns missing → recovery should drop both across two
        retries and still succeed on the third call, surfacing both
        dropped names. Without the loop, the second missing property
        would 400 the save."""
        calls = []
        def fake_request(method, path, json_body=None):
            calls.append(set(json_body["properties"].keys()))
            if "Sourced For" in json_body["properties"]:
                raise NotionSyncError("Sourced For is not a property that exists.")
            if "Lead Summary" in json_body["properties"]:
                raise NotionSyncError("Lead Summary is not a property that exists.")
            return {"id": "abc"}
        with patch.object(self.sync, "_request", side_effect=fake_request):
            page, dropped = self.sync._patch_page_with_missing_property_recovery(
                "abc",
                {"Company": {"title": []},
                 "Sourced For": {"multi_select": []},
                 "Lead Summary": {"rich_text": []}},
            )
        # Three requests: full, minus Sourced For, minus both.
        self.assertEqual(len(calls), 3)
        self.assertEqual(page["id"], "abc")
        # Both dropped names surfaced (order preserved by drop sequence).
        self.assertEqual(set(dropped), {"Sourced For", "Lead Summary"})
        # Final call only carried Company.
        self.assertEqual(calls[-1], {"Company"})

    def test_full_success_returns_empty_dropped_list(self):
        """Happy path: no recovery needed → dropped should be []
        (not None). Callers can branch on truthiness uniformly."""
        def fake_request(method, path, json_body=None):
            return {"id": "abc"}
        with patch.object(self.sync, "_request", side_effect=fake_request):
            page, dropped = self.sync._patch_page_with_missing_property_recovery(
                "abc", {"Company": {"title": []}})
        self.assertEqual(page["id"], "abc")
        self.assertEqual(dropped, [])

    def test_update_page_surfaces_dropped_props_in_response(self):
        """End-to-end at the update_page boundary: when recovery drops
        a property, the returned dict includes dropped_props so the
        API + UI can warn instead of silently swallowing the loss."""
        def fake_request(method, path, json_body=None):
            if "Sourced For" in (json_body or {}).get("properties", {}):
                raise NotionSyncError("Sourced For is not a property that exists.")
            # Return a minimal page shape that _page_to_detail can parse.
            return {"id": "abc", "url": "https://notion.so/abc",
                    "properties": {}}
        with patch.object(self.sync, "_request", side_effect=fake_request):
            out = self.sync.update_page("abc", {
                "company": "Shell",
                "sourced_for_partners": ["Braze"],
            })
        self.assertTrue(out["updated"])
        # dropped_props key present + lists the offending column.
        self.assertEqual(out.get("dropped_props"), ["Sourced For"])

    def test_update_page_omits_dropped_props_when_clean(self):
        """When no recovery fires, response should NOT include the
        dropped_props key — clients shouldn't have to filter empty
        lists everywhere."""
        def fake_request(method, path, json_body=None):
            return {"id": "abc", "url": "https://notion.so/abc",
                    "properties": {}}
        with patch.object(self.sync, "_request", side_effect=fake_request):
            out = self.sync.update_page("abc", {"company": "Shell"})
        self.assertTrue(out["updated"])
        self.assertNotIn("dropped_props", out)


if __name__ == "__main__":
    unittest.main()
