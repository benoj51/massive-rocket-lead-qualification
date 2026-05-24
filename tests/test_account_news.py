"""v1.0.0bj — account news fetcher + scorer + sweep tests.

Three layers (mirrors the engagement-test pattern):
1. account_news.py — RSS parsing, relevance scoring (Anthropic stubbed)
2. account_news_store.py — persistence + dedup
3. /api/admin/watchlist/sweep — end-to-end with HTTP + Anthropic stubbed
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_FAKE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <item>
    <title>Shell launches new loyalty programme - Reuters</title>
    <link>https://reuters.com/shell-loyalty</link>
    <description>Shell today unveiled a new global loyalty programme...</description>
    <pubDate>Fri, 23 May 2026 08:00:00 GMT</pubDate>
    <source>Reuters</source>
  </item>
  <item>
    <title>Shell opens new gas station in Texas - Local News</title>
    <link>https://local.com/shell-tx</link>
    <description>A new Shell station opened in Houston yesterday.</description>
    <pubDate>Fri, 23 May 2026 09:00:00 GMT</pubDate>
    <source>Local News</source>
  </item>
</channel>
</rss>"""


# -----------------------------------------------------------------
# Layer 1: account_news.py — RSS parsing + scorer
# -----------------------------------------------------------------

class AccountNewsModuleTests(unittest.TestCase):
    def setUp(self):
        sys.modules.pop("account_news", None)
        import account_news
        self.news = account_news

    def test_parse_rss_extracts_items(self):
        items = self.news._parse_rss(_FAKE_RSS)
        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertIn("Shell launches new loyalty programme", first["title"])
        self.assertEqual(first["link"], "https://reuters.com/shell-loyalty")
        self.assertEqual(first["source"], "Reuters")
        self.assertEqual(first["published_at"], "2026-05-23T08:00:00Z")
        self.assertTrue(first["id"])  # sha1 hash

    def test_item_id_stable_across_runs(self):
        a = self.news._item_id("Shell launches", "https://x.com/a")
        b = self.news._item_id("Shell launches", "https://x.com/a")
        self.assertEqual(a, b)
        c = self.news._item_id("Different title", "https://x.com/a")
        self.assertNotEqual(a, c)

    def test_fetch_for_company_returns_empty_on_http_failure(self):
        with patch.object(self.news.requests, "get",
                            side_effect=self.news.requests.RequestException("boom")):
            items = self.news.fetch_for_company("Shell")
        self.assertEqual(items, [])

    def test_fetch_for_company_filters_by_since_iso(self):
        fake_resp = MagicMock(ok=True, text=_FAKE_RSS)
        with patch.object(self.news.requests, "get", return_value=fake_resp):
            items = self.news.fetch_for_company(
                "Shell", since_iso="2026-05-24T00:00:00Z")
        # Both fake items are from 2026-05-23 → filter drops them all.
        self.assertEqual(items, [])

    def test_fetch_for_company_with_no_filter_returns_all(self):
        fake_resp = MagicMock(ok=True, text=_FAKE_RSS)
        with patch.object(self.news.requests, "get", return_value=fake_resp):
            items = self.news.fetch_for_company("Shell")
        self.assertEqual(len(items), 2)

    def test_score_relevance_drops_below_threshold(self):
        os.environ["ANTHROPIC_API_KEY"] = "test"
        raw_items = [
            {"id": "a", "title": "Shell launches loyalty",
             "snippet": "...", "source": "Reuters",
             "published_at": "2026-05-23T08:00:00Z"},
            {"id": "b", "title": "Shell opens gas station",
             "snippet": "...", "source": "Local",
             "published_at": "2026-05-23T09:00:00Z"},
        ]
        scored_response = [
            {"id": "a", "relevance_score": 9,
             "why_relevant": "Loyalty rebuild opportunity",
             "mr_action_hint": "Reach out via Marina"},
            {"id": "b", "relevance_score": 2,
             "why_relevant": "Local store opening, not material",
             "mr_action_hint": None},
        ]
        result = self._run_score_with(scored_response, raw_items)
        # b was below threshold (4), dropped.
        self.assertEqual([r["id"] for r in result], ["a"])
        self.assertEqual(result[0]["relevance_score"], 9)
        self.assertEqual(result[0]["why_relevant"],
                          "Loyalty rebuild opportunity")
        os.environ.pop("ANTHROPIC_API_KEY")

    def test_score_relevance_returns_empty_when_anthropic_off(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        result = self.news.score_relevance(
            [{"id": "a", "title": "x"}], "Shell")
        self.assertEqual(result, [])

    def test_score_relevance_handles_malformed_json(self):
        os.environ["ANTHROPIC_API_KEY"] = "test"
        result = self._run_score_with("not valid json", [
            {"id": "a", "title": "x", "snippet": "", "source": "",
             "published_at": ""},
        ])
        self.assertEqual(result, [])
        os.environ.pop("ANTHROPIC_API_KEY")

    def test_score_relevance_sorts_highest_first(self):
        os.environ["ANTHROPIC_API_KEY"] = "test"
        raw = [
            {"id": str(i), "title": f"x{i}", "snippet": "",
             "source": "", "published_at": ""} for i in range(3)
        ]
        scored = [
            {"id": "0", "relevance_score": 5, "why_relevant": "x"},
            {"id": "1", "relevance_score": 9, "why_relevant": "x"},
            {"id": "2", "relevance_score": 7, "why_relevant": "x"},
        ]
        result = self._run_score_with(scored, raw)
        self.assertEqual([r["id"] for r in result], ["1", "2", "0"])
        os.environ.pop("ANTHROPIC_API_KEY")

    def _run_score_with(self, llm_response, items):
        """Helper: patch Anthropic SDK at the module level so
        score_relevance's local import picks up the fake."""
        if isinstance(llm_response, (list, dict)):
            text = json.dumps(llm_response)
        else:
            text = llm_response
        class _Block:
            def __init__(self, t): self.text = t
        class _Msg:
            def __init__(self, t): self.content = [_Block(t)]
        class _Messages:
            def create(self, **kwargs): return _Msg(text)
        class _FakeAnthropic:
            def __init__(self, **kwargs): self.messages = _Messages()
        import anthropic
        with patch.object(anthropic, "Anthropic", _FakeAnthropic):
            return self.news.score_relevance(items, "Shell")


# -----------------------------------------------------------------
# Layer 2: account_news_store.py
# -----------------------------------------------------------------

class AccountNewsStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["ACCOUNT_NEWS_STORE_DIR"] = self.tmp
        sys.modules.pop("account_news_store", None)
        import account_news_store
        self.store = account_news_store

    def tearDown(self):
        os.environ.pop("ACCOUNT_NEWS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_upsert_adds_new_items(self):
        result = self.store.upsert_many("shell", [
            {"id": "a", "title": "Shell loyalty",
             "relevance_score": 9, "published_at": "2026-05-23T08:00:00Z"},
            {"id": "b", "title": "Shell mobile app",
             "relevance_score": 7, "published_at": "2026-05-22T08:00:00Z"},
        ])
        self.assertEqual(result["added"], 2)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(len(result["new_items"]), 2)

    def test_upsert_dedups_by_id(self):
        self.store.upsert_many("shell", [
            {"id": "a", "title": "first version", "relevance_score": 5},
        ])
        result = self.store.upsert_many("shell", [
            {"id": "a", "title": "updated version", "relevance_score": 9},
        ])
        self.assertEqual(result["added"], 0)
        self.assertEqual(result["updated"], 1)
        items = self.store.list_for("shell")
        self.assertEqual(len(items), 1)
        # Updated content reflected.
        self.assertEqual(items[0]["title"], "updated version")
        self.assertEqual(items[0]["relevance_score"], 9)

    def test_list_for_sorted_newest_first(self):
        self.store.upsert_many("shell", [
            {"id": "old", "title": "x",
             "published_at": "2026-05-20T08:00:00Z"},
            {"id": "new", "title": "x",
             "published_at": "2026-05-23T08:00:00Z"},
            {"id": "mid", "title": "x",
             "published_at": "2026-05-22T08:00:00Z"},
        ])
        ids = [i["id"] for i in self.store.list_for("shell")]
        self.assertEqual(ids, ["new", "mid", "old"])

    def test_ids_already_seen(self):
        self.store.upsert_many("shell", [
            {"id": "a", "title": "x"},
            {"id": "b", "title": "x"},
        ])
        seen = self.store.ids_already_seen("shell")
        self.assertEqual(seen, {"a", "b"})

    def test_per_lead_isolation(self):
        self.store.upsert_many("shell", [{"id": "s1", "title": "x"}])
        self.store.upsert_many("yum",   [{"id": "y1", "title": "x"}])
        self.assertEqual([i["id"] for i in self.store.list_for("shell")],
                         ["s1"])
        self.assertEqual([i["id"] for i in self.store.list_for("yum")],
                         ["y1"])


# -----------------------------------------------------------------
# Layer 3: sweep endpoint (end-to-end with HTTP + Anthropic stubbed)
# -----------------------------------------------------------------

class WatchlistSweepEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["ACCOUNT_WATCHLIST_STORE_DIR"] = os.path.join(cls.tmp, "wl")
        os.environ["ACCOUNT_NEWS_STORE_DIR"] = os.path.join(cls.tmp, "news")
        os.environ["NOTIFICATIONS_STORE_DIR"] = os.path.join(cls.tmp, "notif")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ["ANTHROPIC_API_KEY"] = "test"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "account_news", "account_news_store",
                    "account_watchlist_store", "notifications_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("ACCOUNT_WATCHLIST_STORE_DIR",
                  "ACCOUNT_NEWS_STORE_DIR",
                  "NOTIFICATIONS_STORE_DIR",
                  "SKIP_COMMAND_CENTRE_SEED", "ANTHROPIC_API_KEY"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        import account_watchlist_store, account_news_store, notifications_store
        # Wipe state per test.
        for f in account_watchlist_store._store_dir().glob("*.json"):
            f.unlink()
        for f in account_news_store._store_dir().glob("*.json"):
            f.unlink()
        notifications_store.clear("Ben Ojuolape")
        notifications_store.clear("ben-ojuolape")  # the slug
        notifications_store.clear("Glenn Bonforte")

    def test_sweep_with_no_watchers_returns_zero(self):
        body = self.client.post(
            "/api/admin/watchlist/sweep").get_json()
        self.assertEqual(body["leads_scanned"], 0)
        self.assertEqual(body["items_added"], 0)
        self.assertEqual(body["notifications_fired"], 0)

    def test_sweep_fans_news_out_to_all_watchers(self):
        """Two users watch the same Shell lead. One relevant news item.
        Both should get a news_alert notification."""
        # Seed two watchers.
        with patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.list_pipeline.return_value = []
            self.client.post("/api/watchlist/shell-lead",
                              json={"user": "Ben Ojuolape"})
            self.client.post("/api/watchlist/shell-lead",
                              json={"user": "Glenn Bonforte"})
        # Stub the news fetch + scoring.
        fake_items = [
            {"id": "news-1", "title": "Shell launches loyalty",
             "link": "https://reuters.com/x",
             "source": "Reuters", "snippet": "...",
             "published_at": "2026-05-23T08:00:00Z"},
        ]
        fake_scored = [
            {**fake_items[0], "relevance_score": 9,
             "why_relevant": "Loyalty rebuild",
             "mr_action_hint": "Outreach via Marina",
             "scored_at": "2026-05-24T09:00:00Z"},
        ]
        with patch.object(self.server, "NotionSync") as MockSync, \
             patch.object(self.server.account_news,
                            "fetch_for_company",
                            return_value=fake_items), \
             patch.object(self.server.account_news,
                            "score_relevance",
                            return_value=fake_scored):
            MockSync.return_value.list_pipeline.return_value = [
                {"id": "shell-lead", "company": "Shell"},
            ]
            body = self.client.post(
                "/api/admin/watchlist/sweep").get_json()
        self.assertEqual(body["leads_scanned"], 1)
        self.assertEqual(body["items_added"], 1)
        self.assertEqual(body["notifications_fired"], 2)
        # Both users got a news_alert.
        import notifications_store
        for slug in ("ben-ojuolape", "glenn-bonforte"):
            items = notifications_store.list_for(slug)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["type"], "news_alert")
            self.assertIn("Shell", items[0]["title"])
            self.assertIn("Loyalty rebuild", items[0]["body"])
            self.assertEqual(items[0]["link"]["lead_id"], "shell-lead")

    def test_sweep_skips_already_seen_items(self):
        """A second sweep on the same news doesn't re-notify."""
        with patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.list_pipeline.return_value = []
            self.client.post("/api/watchlist/shell-lead",
                              json={"user": "Ben Ojuolape"})
        fake_items = [{"id": "news-1", "title": "Shell loyalty",
                        "link": "https://r/x", "source": "R",
                        "snippet": "", "published_at": "2026-05-23T08:00:00Z"}]
        fake_scored = [{**fake_items[0], "relevance_score": 9,
                         "why_relevant": "x"}]
        with patch.object(self.server, "NotionSync") as MockSync, \
             patch.object(self.server.account_news,
                            "fetch_for_company",
                            return_value=fake_items), \
             patch.object(self.server.account_news,
                            "score_relevance",
                            return_value=fake_scored):
            MockSync.return_value.list_pipeline.return_value = [
                {"id": "shell-lead", "company": "Shell"}]
            # First sweep: 1 notification.
            body1 = self.client.post(
                "/api/admin/watchlist/sweep").get_json()
            # Second sweep: dedup — 0 new notifications.
            body2 = self.client.post(
                "/api/admin/watchlist/sweep").get_json()
        self.assertEqual(body1["notifications_fired"], 1)
        self.assertEqual(body2["notifications_fired"], 0)

    def test_sweep_lead_id_query_param_scopes(self):
        """?lead_id=foo restricts the sweep to that single lead."""
        with patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.list_pipeline.return_value = []
            self.client.post("/api/watchlist/shell-lead",
                              json={"user": "Ben Ojuolape"})
            self.client.post("/api/watchlist/yum-lead",
                              json={"user": "Ben Ojuolape"})
        with patch.object(self.server, "NotionSync") as MockSync, \
             patch.object(self.server.account_news,
                            "fetch_for_company",
                            return_value=[]), \
             patch.object(self.server.account_news,
                            "score_relevance",
                            return_value=[]):
            MockSync.return_value.list_pipeline.return_value = [
                {"id": "shell-lead", "company": "Shell"},
                {"id": "yum-lead", "company": "Yum"},
            ]
            body = self.client.post(
                "/api/admin/watchlist/sweep?lead_id=shell-lead").get_json()
        # Only shell-lead got scanned even though both are watched.
        self.assertEqual(body["leads_scanned"], 1)


if __name__ == "__main__":
    unittest.main()
