"""v1.0.0dm — watchlist news sweep, extracted as a reusable function.

The watchlist news sweep used to live inline in server.py's
`/api/admin/watchlist/sweep` endpoint. v1.0.0dm needs to run the same
logic from a scheduled job (scheduled_agents.run_job) without going
through HTTP, so the body is lifted here and BOTH callers share it:

  - server.py's endpoint is now a thin wrapper.
  - scheduled_agents.py's Wednesday news job calls run_sweep() directly.

Behaviour is unchanged from the original endpoint: scan every watched
account, fetch news, score relevance, persist new items, and fire a
`news_alert` notification to each watcher for items they haven't seen.

Pure leaf module: imports only the relevant stores + notion_sync, never
server, so it's safe to import from anywhere.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import account_news
import account_news_store
import account_watchlist_store
import notifications_store
from notion_sync import NotionSync

log = logging.getLogger(__name__)


def run_sweep(*, only: str | None = None) -> dict[str, Any]:
    """Scan watched accounts, fetch + score + persist news, notify watchers.

    Args:
        only: restrict to a single lead_id (testing / debugging).

    Returns a summary dict:
        {leads_scanned, items_added, notifications_fired, errors: [...]}
    Never raises; collects per-account errors into `errors`.
    """
    summary: dict[str, Any] = {
        "leads_scanned": 0,
        "items_added": 0,
        "notifications_fired": 0,
        "errors": [],
    }

    # Build the set of leads to scan: every lead any user is watching,
    # mapped to the list of users watching it.
    lead_to_watchers: dict[str, list[str]] = {}
    try:
        for f in account_watchlist_store._store_dir().glob("*.json"):
            try:
                rows = json.loads(f.read_text())
                if not isinstance(rows, list):
                    continue
                user = f.stem  # slug — notifications_store accepts it
                for r in rows:
                    lid = (r.get("lead_id") or "").strip()
                    if not lid or (only and lid != only):
                        continue
                    lead_to_watchers.setdefault(lid, []).append(user)
            except (OSError, ValueError):
                continue
    except Exception as e:  # noqa: BLE001
        summary["errors"].append(f"watchlist scan: {e}")
        return summary

    # Resolve company names for every lead in one Notion call.
    company_by_id: dict[str, str] = {}
    try:
        sync = NotionSync()
        for r in sync.list_pipeline(limit=500):
            if r.get("id") and r.get("company"):
                company_by_id[r["id"]] = r["company"]
    except Exception as e:  # noqa: BLE001
        log.warning("Sweep: pipeline name lookup failed: %s", e)

    for lid, watchers in lead_to_watchers.items():
        company = company_by_id.get(lid) or lid
        try:
            raw = account_news.fetch_for_company(company, limit=15)
            seen = account_news_store.ids_already_seen(lid)
            fresh = [i for i in raw if i["id"] not in seen]
            scored = account_news.score_relevance(fresh, company) if fresh else []
            result = account_news_store.upsert_many(lid, scored)
            summary["leads_scanned"] += 1
            summary["items_added"] += result["added"]
            # Notify each watcher for each NEW item (not updated).
            for item in result.get("new_items") or []:
                for user in watchers:
                    try:
                        notifications_store.notify_assignment(
                            user,
                            kind="news_alert",
                            title=f"{company}: {item.get('title', '')[:120]}",
                            body=(item.get("why_relevant") or
                                  item.get("snippet") or "")[:240],
                            link={"kind": "lead", "lead_id": lid},
                            actor=None,
                        )
                        summary["notifications_fired"] += 1
                    except Exception as e:  # noqa: BLE001
                        summary["errors"].append(
                            f"notify {user} for {lid}: {e}")
            # Bump the high-water mark per watcher.
            for user in watchers:
                try:
                    account_watchlist_store.mark_news_seen(user, lid)
                except Exception:  # noqa: BLE001
                    pass
        except Exception as e:  # noqa: BLE001
            summary["errors"].append(f"sweep {lid}: {e}")
            log.exception("Sweep error for %s", lid)

    return summary
