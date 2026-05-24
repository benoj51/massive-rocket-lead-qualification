"""v1.0.0bi — account watchlist store + endpoint tests.

Per-user list of leads the team wants tracked for relevant news.
Foundation for v1.0.0bj which adds the news fetcher + AI relevance
+ bell notifications.
"""
from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class AccountWatchlistStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["ACCOUNT_WATCHLIST_STORE_DIR"] = self.tmp
        sys.modules.pop("account_watchlist_store", None)
        import account_watchlist_store
        self.store = account_watchlist_store

    def tearDown(self):
        os.environ.pop("ACCOUNT_WATCHLIST_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_add_and_list(self):
        entry = self.store.add("Ben", "page-abc")
        self.assertEqual(entry["lead_id"], "page-abc")
        self.assertTrue(entry["added_at"])
        self.assertIsNone(entry["last_news_seen_at"])
        items = self.store.list_for("Ben")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["lead_id"], "page-abc")

    def test_add_idempotent(self):
        first = self.store.add("Ben", "page-abc")
        second = self.store.add("Ben", "page-abc")
        # Same entry — added_at preserved.
        self.assertEqual(first["added_at"], second["added_at"])
        # And only one row in the file.
        self.assertEqual(len(self.store.list_for("Ben")), 1)

    def test_list_newest_first(self):
        self.store.add("Ben", "first")
        # Tiny sleep so the timestamps differ at second resolution.
        import time
        time.sleep(1.05)
        self.store.add("Ben", "second")
        items = self.store.list_for("Ben")
        self.assertEqual([i["lead_id"] for i in items],
                         ["second", "first"])

    def test_remove(self):
        self.store.add("Ben", "page-abc")
        self.assertTrue(self.store.remove("Ben", "page-abc"))
        self.assertEqual(self.store.list_for("Ben"), [])
        # Second remove → False.
        self.assertFalse(self.store.remove("Ben", "page-abc"))

    def test_is_watching(self):
        self.assertFalse(self.store.is_watching("Ben", "page-abc"))
        self.store.add("Ben", "page-abc")
        self.assertTrue(self.store.is_watching("Ben", "page-abc"))
        self.store.remove("Ben", "page-abc")
        self.assertFalse(self.store.is_watching("Ben", "page-abc"))

    def test_per_user_isolation(self):
        self.store.add("Ben", "page-abc")
        self.store.add("Glenn", "page-xyz")
        self.assertEqual([i["lead_id"] for i in self.store.list_for("Ben")],
                         ["page-abc"])
        self.assertEqual([i["lead_id"] for i in self.store.list_for("Glenn")],
                         ["page-xyz"])
        self.assertFalse(self.store.is_watching("Ben", "page-xyz"))

    def test_watchers_of(self):
        """Inverse lookup: every user watching a given lead. Used by
        the news fetcher (v1.0.0bj) to fan a single scan out."""
        self.store.add("Ben", "shell")
        self.store.add("Glenn", "shell")
        self.store.add("Ben", "yum")  # noise
        watchers = self.store.watchers_of("shell")
        # Returns slugified user names; the notifications store
        # accepts both display + slug.
        self.assertEqual(sorted(watchers), ["ben", "glenn"])

    def test_watchers_of_empty_when_no_watchers(self):
        self.store.add("Ben", "shell")
        self.assertEqual(self.store.watchers_of("yum"), [])

    def test_mark_news_seen_bumps_high_water_mark(self):
        self.store.add("Ben", "shell")
        self.assertIsNone(self.store.list_for("Ben")[0]["last_news_seen_at"])
        self.assertTrue(self.store.mark_news_seen(
            "Ben", "shell", ts="2026-05-24T10:00:00Z"))
        items = self.store.list_for("Ben")
        self.assertEqual(items[0]["last_news_seen_at"],
                          "2026-05-24T10:00:00Z")

    def test_mark_news_seen_missing_entry_returns_false(self):
        self.assertFalse(self.store.mark_news_seen("Ben", "no-such"))

    def test_validation_user_required(self):
        with self.assertRaises(self.store.AccountWatchlistStoreError):
            self.store.add("", "page-abc")

    def test_validation_lead_id_required(self):
        with self.assertRaises(self.store.AccountWatchlistStoreError):
            self.store.add("Ben", "")

    def test_cap_at_200(self):
        for i in range(200):
            self.store.add("Ben", f"lead-{i}")
        with self.assertRaises(self.store.AccountWatchlistStoreError):
            self.store.add("Ben", "lead-201")


class AccountWatchlistEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["ACCOUNT_WATCHLIST_STORE_DIR"] = os.path.join(cls.tmp, "wl")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "account_watchlist_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("ACCOUNT_WATCHLIST_STORE_DIR",
                  "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        import account_watchlist_store
        for w in account_watchlist_store.list_for("Ben Ojuolape"):
            account_watchlist_store.remove("Ben Ojuolape", w["lead_id"])

    def test_list_requires_user(self):
        r = self.client.get("/api/watchlist")
        self.assertEqual(r.status_code, 400)

    def test_add_then_list_with_company_enrichment(self):
        """List should enrich each entry with the lead's company name
        via the Notion pipeline lookup (best-effort)."""
        with patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.list_pipeline.return_value = [
                {"id": "shell", "company": "Shell"},
            ]
            self.client.post("/api/watchlist/shell",
                              json={"user": "Ben Ojuolape"})
            body = self.client.get(
                "/api/watchlist?user=Ben%20Ojuolape").get_json()
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["lead_id"], "shell")
        self.assertEqual(body["items"][0]["company"], "Shell")

    def test_add_returns_201_and_watching_true(self):
        with patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.list_pipeline.return_value = []
            r = self.client.post("/api/watchlist/shell",
                                  json={"user": "Ben Ojuolape"})
        self.assertEqual(r.status_code, 201)
        body = r.get_json()
        self.assertTrue(body["watching"])
        self.assertEqual(body["entry"]["lead_id"], "shell")

    def test_remove_endpoint(self):
        with patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.list_pipeline.return_value = []
            self.client.post("/api/watchlist/shell",
                              json={"user": "Ben Ojuolape"})
        r = self.client.delete("/api/watchlist/shell?user=Ben%20Ojuolape")
        body = r.get_json()
        self.assertTrue(body["removed"])
        self.assertFalse(body["watching"])

    def test_remove_unknown_returns_removed_false(self):
        r = self.client.delete("/api/watchlist/never-watched?user=Ben%20Ojuolape")
        body = r.get_json()
        self.assertFalse(body["removed"])

    def test_status_endpoint(self):
        with patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.list_pipeline.return_value = []
            self.client.post("/api/watchlist/shell",
                              json={"user": "Ben Ojuolape"})
        on = self.client.get(
            "/api/watchlist/shell/status?user=Ben%20Ojuolape").get_json()
        off = self.client.get(
            "/api/watchlist/yum/status?user=Ben%20Ojuolape").get_json()
        self.assertTrue(on["watching"])
        self.assertFalse(off["watching"])

    def test_add_missing_user_400(self):
        r = self.client.post("/api/watchlist/shell", json={})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
