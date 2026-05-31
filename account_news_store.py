"""v1.0.0bj — Persistent store for scored news items per account.

Keeps the AI-scored news items so:
- The lead drawer can render them without re-fetching every time
- The sweep dedupes against already-seen items (one notification per
  article, not one per sweep)
- A future "weekly digest" feature can roll up the week's items

Shape
-----
    {
      "id":               "<sha1 of title+link>",
      "lead_id":          "shell",
      "title":            "Shell launches new loyalty programme",
      "link":             "https://...",
      "source":           "Reuters",
      "snippet":          "Shell today unveiled...",
      "published_at":     "2026-05-22T08:00:00Z",
      "relevance_score":  9,
      "why_relevant":     "Loyalty rebuild opportunity",
      "mr_action_hint":   "Reach out via Marina (Braze) on CDP needs",
      "scored_at":        "2026-05-24T09:30:00Z",
      "seen_at":          "2026-05-24T09:30:00Z",
    }

API
---
    list_for(lead_id, *, limit=20) -> list[dict]
        Newest-first, capped.

    upsert_many(lead_id, items) -> dict
        Returns {added: int, updated: int, items: list}. Dedup by id.

    ids_already_seen(lead_id) -> set[str]
        For the sweep — skip items we've already processed.

    clear(lead_id) -> int
        Test helper.
"""
from __future__ import annotations

import json
import json_file_store
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DIR = Path(__file__).parent / "cache" / "account_news"
_LOCK = threading.Lock()
_RING_CAP = 100  # per-lead cap; older items drop off


class AccountNewsStoreError(RuntimeError):
    pass


def _store_dir() -> Path:
    override = os.environ.get("ACCOUNT_NEWS_STORE_DIR")
    d = Path(override) if override else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slugify(value: str) -> str:
    if not value:
        return "unknown"
    s = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return s.strip("-") or "unknown"


def _path(lead_id: str) -> Path:
    return _store_dir() / f"{_slugify(lead_id)}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_raw(lead_id: str) -> list[dict[str, Any]]:
    p = _path(lead_id)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
        if not isinstance(data, list):
            return []
        return data
    except (OSError, ValueError):
        return []


def _save_raw(lead_id: str, rows: list[dict[str, Any]]) -> None:
    p = _path(lead_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    json_file_store.write_json(p, rows)


def list_for(lead_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """Return scored news items for `lead_id`, newest-first."""
    if not lead_id:
        return []
    with _LOCK:
        rows = _load_raw(lead_id)
    # Sort: most recent published_at first; fall back to scored_at.
    def _key(r):
        return r.get("published_at") or r.get("scored_at") or ""
    rows.sort(key=_key, reverse=True)
    if limit and limit > 0:
        rows = rows[:limit]
    return rows


def upsert_many(lead_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Add/update scored items. Dedup by `id`. Returns counts +
    the new+updated rows so the caller can know which to notify on."""
    if not lead_id:
        raise AccountNewsStoreError("lead_id required")
    if not items:
        return {"added": 0, "updated": 0, "items": []}
    with _LOCK:
        rows = _load_raw(lead_id)
        existing_by_id = {r.get("id"): r for r in rows if r.get("id")}
        added: list[dict[str, Any]] = []
        updated: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            normalised = {
                "lead_id":   lead_id,
                "seen_at":   _now(),
                **item,
            }
            iid = item["id"]
            if iid in existing_by_id:
                # Preserve the original seen_at so the sweep can tell
                # new-since-last-sweep apart from re-poll.
                normalised["seen_at"] = existing_by_id[iid].get("seen_at") or _now()
                existing_by_id[iid].update(normalised)
                updated.append(existing_by_id[iid])
            else:
                rows.append(normalised)
                existing_by_id[iid] = normalised
                added.append(normalised)
        # Cap.
        if len(rows) > _RING_CAP:
            rows.sort(key=lambda r: r.get("published_at")
                        or r.get("scored_at") or "")
            rows = rows[-_RING_CAP:]
        _save_raw(lead_id, rows)
    return {"added": len(added), "updated": len(updated),
            "items": added + updated, "new_items": added}


def ids_already_seen(lead_id: str) -> set[str]:
    """Used by the sweep to skip articles we've already processed."""
    if not lead_id:
        return set()
    with _LOCK:
        rows = _load_raw(lead_id)
    return {r.get("id") for r in rows if r.get("id")}


def clear(lead_id: str) -> int:
    """Test/admin helper — wipe news for a lead. Returns count removed."""
    if not lead_id:
        return 0
    with _LOCK:
        rows = _load_raw(lead_id)
        n = len(rows)
        _save_raw(lead_id, [])
    return n
