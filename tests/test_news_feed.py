"""v1.0.0dx — dedicated cross-account news feed.

Two layers:
1. account_news_store.all_news — aggregate scored items across every
   account that has any.
2. /api/news/feed — names resolved, sorted newest-first, optionally
   scoped to a user's watchlist.
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


class AllNewsAggregateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["ACCOUNT_NEWS_STORE_DIR"] = self.tmp
        sys.modules.pop("account_news_store", None)
        import account_news_store
        self.store = account_news_store

    def tearDown(self):
        os.environ.pop("ACCOUNT_NEWS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_aggregates_across_leads(self):
        self.store.upsert_many("shell", [
            {"id": "s1", "title": "Shell loyalty", "relevance_score": 9,
             "published_at": "2026-05-23T08:00:00Z"}])
        self.store.upsert_many("yum", [
            {"id": "y1", "title": "Yum CDP", "relevance_score": 7,
             "published_at": "2026-05-22T08:00:00Z"}])
        items = self.store.all_news()
        self.assertEqual(sorted(i["id"] for i in items), ["s1", "y1"])
        by_id = {i["id"]: i for i in items}
        # Each item carries its own lead_id so the caller can name it.
        self.assertEqual(by_id["s1"]["lead_id"], "shell")
        self.assertEqual(by_id["y1"]["lead_id"], "yum")

    def test_empty_when_no_news(self):
        self.assertEqual(self.store.all_news(), [])


class NewsFeedEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["ACCOUNT_NEWS_STORE_DIR"] = os.path.join(cls.tmp, "news")
        os.environ["ACCOUNT_WATCHLIST_STORE_DIR"] = os.path.join(cls.tmp, "wl")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "account_news_store", "account_watchlist_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("ACCOUNT_NEWS_STORE_DIR", "ACCOUNT_WATCHLIST_STORE_DIR",
                  "SKIP_COMMAND_CENTRE_SEED", "APOLLO_USE_FIXTURES"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        import account_news_store, account_watchlist_store
        for f in account_news_store._store_dir().glob("*.json"):
            f.unlink()
        for f in account_watchlist_store._store_dir().glob("*.json"):
            f.unlink()
        account_news_store.upsert_many("lead-shell", [
            {"id": "s1", "title": "Shell loyalty", "relevance_score": 9,
             "published_at": "2026-05-23T08:00:00Z"}])
        account_news_store.upsert_many("lead-yum", [
            {"id": "y1", "title": "Yum CDP", "relevance_score": 7,
             "published_at": "2026-05-20T08:00:00Z"}])

    def _patch_names(self):
        m = patch.object(self.server, "NotionSync")
        Mock = m.start()
        Mock.return_value.list_pipeline.return_value = [
            {"id": "lead-shell", "company": "Shell"},
            {"id": "lead-yum", "company": "Yum Brands"},
        ]
        self.addCleanup(m.stop)

    def test_feed_aggregates_names_and_sorts(self):
        self._patch_names()
        body = self.client.get("/api/news/feed").get_json()
        self.assertEqual(body["count"], 2)
        # Newest first (Shell 05-23 before Yum 05-20).
        self.assertEqual(body["items"][0]["title"], "Shell loyalty")
        self.assertEqual(body["items"][0]["account"], "Shell")
        self.assertEqual({a["account"] for a in body["accounts"]},
                         {"Shell", "Yum Brands"})

    def test_feed_scoped_to_user_watchlist(self):
        self._patch_names()
        import account_watchlist_store
        account_watchlist_store.add("Ben Ojuolape", "lead-yum")
        body = self.client.get(
            "/api/news/feed?user=Ben Ojuolape").get_json()
        self.assertTrue(body["scoped_to_user"])
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["items"][0]["lead_id"], "lead-yum")


if __name__ == "__main__":
    unittest.main()
