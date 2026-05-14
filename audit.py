"""Append-only audit log for the qualification platform.

Every qualify, Notion sync, and (future) HubSpot sync writes one JSON line
to `cache/audit.jsonl`. Cheap, human-readable, no DB. Good enough for
"who qualified what when" answers in the v0.3 window.

Events look like:
    {"ts": "2026-05-13T22:00:00Z", "type": "qualified",
     "actor": "bo", "company": "Deliveroo", "url": "...",
     "score": 9.4, "status": "qualify_in"}

For higher volume later, swap the storage layer in `_write` without changing
callers.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_DEFAULT_PATH = Path(__file__).parent / "cache" / "audit.jsonl"
_LOCK = threading.Lock()


def _path() -> Path:
    """Resolve audit log path. Allows override via AUDIT_LOG_PATH env var."""
    override = os.environ.get("AUDIT_LOG_PATH")
    p = Path(override) if override else _DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log_event(event_type: str, **fields: Any) -> None:
    """Append one event to the audit log. Best-effort — never raises."""
    if not event_type:
        return
    record = {"ts": _now_iso(), "type": event_type, **fields}
    line = json.dumps(record, default=str, ensure_ascii=False)
    try:
        with _LOCK:
            with _path().open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except OSError:
        # Logging must never break the request path.
        pass


def read_events(limit: int = 50, *, since: str | None = None) -> list[dict]:
    """Return the most recent `limit` events, newest first.

    `since` is an ISO-8601 string; events strictly older are dropped.
    """
    path = _path()
    if not path.exists():
        return []
    rows: list[dict] = []
    try:
        with _LOCK:
            with path.open("r", encoding="utf-8") as f:
                lines = f.readlines()
    except OSError:
        return []
    # Read newest-first by walking backwards.
    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if since and row.get("ts", "") < since:
            break
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def summarise(rows: Iterable[dict]) -> dict:
    """Roll up an event list for quick stats / digests."""
    rows = list(rows)
    by_type: dict[str, int] = {}
    qualified_in = 0
    qualified_out = 0
    borderline = 0
    by_company: dict[str, int] = {}
    for r in rows:
        t = r.get("type") or "unknown"
        by_type[t] = by_type.get(t, 0) + 1
        if t == "qualified":
            status = r.get("status")
            if status == "qualify_in":
                qualified_in += 1
            elif status == "qualify_out":
                qualified_out += 1
            elif status == "borderline":
                borderline += 1
            company = r.get("company")
            if company:
                by_company[company] = by_company.get(company, 0) + 1
    return {
        "total_events": len(rows),
        "by_type": by_type,
        "qualified_in": qualified_in,
        "borderline": borderline,
        "qualified_out": qualified_out,
        "top_companies": sorted(by_company.items(), key=lambda kv: -kv[1])[:10],
    }
