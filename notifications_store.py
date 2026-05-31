"""v1.0.0al — Per-user notification store.

Ben asked: "Should be notifications as well. When contacts or accounts
are being assigned to a person."

Design
------
- One JSON file per recipient slug (a slugified MR-owner name).
- Each notification carries enough context to render a one-line
  summary + a deep link back to the entity that triggered it.
- "Read" state is sticky once flipped; the bell-icon badge counts
  unread entries.
- Ring-buffered at 200 per recipient so the file doesn't grow without
  bound — older notifications drop off the bottom on each new write.

The store is deliberately minimal: no event bus, no fan-out. The
*caller* (server endpoint that mutates the entity) is responsible for
calling `notify_assignment` when a value of interest changes. That
keeps the trigger logic explicit and reviewable in one place.

Notification shape
------------------
    {
      "id":          "<uuid4>",
      "recipient":   "Ben Ojuolape",          # display name, stored verbatim
      "recipient_slug": "ben-ojuolape",       # for file routing
      "type":        "assigned_partner_contact" | "assigned_lead",
      "title":       "You were assigned Marina Klusas (Braze)",
      "body":        "Reassigned from Glenn Bonforte by Thierry Sequeira",
      "link": {                               # UI uses this to navigate
        "kind":  "partner_contact",
        "partner_id": "braze",
        "contact_id": "abc123",
      },
      "actor":       "Thierry Sequeira",      # who made the change
      "created_at":  "2026-05-23T19:45:00Z",
      "read_at":     None | iso8601,
    }

API
---
    notify_assignment(recipient, *, kind, ...)  -> notification dict
    list_for(recipient, *, unread_only=False, limit=50) -> list[dict]
    unread_count(recipient)                     -> int
    mark_read(notification_id, *, recipient)    -> bool
    mark_all_read(recipient)                    -> int (count marked)
"""
from __future__ import annotations

import json
import json_file_store
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DIR = Path(__file__).parent / "cache" / "notifications"
_LOCK = threading.Lock()
_RING_CAP = 200  # per-recipient cap; older entries drop off on write


class NotificationsStoreError(RuntimeError):
    pass


def _store_dir() -> Path:
    override = os.environ.get("NOTIFICATIONS_STORE_DIR")
    d = Path(override) if override else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slugify(value: str) -> str:
    """Standalone slug — same shape as project_store.slugify but
    duplicated here to keep this module dep-free (project_store imports
    are slow on cold-start)."""
    if not value:
        return "unknown"
    s = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return s.strip("-") or "unknown"


def _path(recipient: str) -> Path:
    return _store_dir() / f"{_slugify(recipient)}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_raw(recipient: str) -> list[dict[str, Any]]:
    p = _path(recipient)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
        if not isinstance(data, list):
            return []
        return data
    except (OSError, ValueError):
        return []


def _save_raw(recipient: str, rows: list[dict[str, Any]]) -> None:
    p = _path(recipient)
    p.parent.mkdir(parents=True, exist_ok=True)
    json_file_store.write_json(p, rows)


def _normalise(n: dict[str, Any]) -> dict[str, Any]:
    """Backfill any missing structural fields. Never raises — a malformed
    row degrades to the safest defaults rather than blowing up the bell."""
    out = dict(n)
    out.setdefault("id", uuid.uuid4().hex)
    out.setdefault("type", "info")
    out.setdefault("title", "(no title)")
    out.setdefault("body", "")
    out.setdefault("link", None)
    out.setdefault("actor", None)
    out.setdefault("created_at", _now())
    out.setdefault("read_at", None)
    out.setdefault("recipient", out.get("recipient") or "Unknown")
    out.setdefault("recipient_slug", _slugify(out["recipient"]))
    return out


# ---- core API -------------------------------------------------------------

def notify_assignment(recipient: str, *,
                       kind: str,
                       title: str,
                       body: str = "",
                       link: dict[str, Any] | None = None,
                       actor: str | None = None,
                       ) -> dict[str, Any] | None:
    """Append an assignment-style notification for `recipient`.

    Returns the persisted notification dict, or None if `recipient` is
    falsy (the caller passed an empty owner — no-op rather than crash).
    Caller should ensure recipient != actor to avoid self-notification
    spam, but the store doesn't enforce that (a few legit self-notifs
    might be useful later, e.g. system-generated reminders).
    """
    if not (recipient or "").strip():
        return None
    n = _normalise({
        "id": uuid.uuid4().hex,
        "recipient": recipient.strip(),
        "type": kind,
        "title": title,
        "body": body,
        "link": link,
        "actor": (actor or "").strip() or None,
        "created_at": _now(),
        "read_at": None,
    })
    with _LOCK:
        rows = _load_raw(recipient)
        rows.append(n)
        # Ring-buffer cap: keep the newest _RING_CAP entries.
        if len(rows) > _RING_CAP:
            rows = rows[-_RING_CAP:]
        _save_raw(recipient, rows)
    return n


def list_for(recipient: str, *,
              unread_only: bool = False,
              limit: int = 50) -> list[dict[str, Any]]:
    """Return notifications for `recipient`, newest-first.

    File order is append-on-write (oldest first). We reverse FIRST so
    that file-position ties (multiple notifications in the same second)
    fall newest-first naturally, then apply a stable descending sort by
    timestamp — equal-keyed entries keep their reversed order.
    """
    if not recipient:
        return []
    with _LOCK:
        rows = [_normalise(r) for r in _load_raw(recipient)]
    rows.reverse()  # file → newest-first baseline
    if unread_only:
        rows = [r for r in rows if not r.get("read_at")]
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    if limit and limit > 0:
        rows = rows[:limit]
    return rows


def unread_count(recipient: str) -> int:
    if not recipient:
        return 0
    with _LOCK:
        rows = _load_raw(recipient)
    return sum(1 for r in rows if not r.get("read_at"))


def mark_read(notification_id: str, *, recipient: str) -> bool:
    """Flip a single notification to read. Returns True if it was
    found and updated, False if not present or already read."""
    if not (notification_id and recipient):
        return False
    with _LOCK:
        rows = _load_raw(recipient)
        changed = False
        for r in rows:
            if r.get("id") == notification_id and not r.get("read_at"):
                r["read_at"] = _now()
                changed = True
                break
        if changed:
            _save_raw(recipient, rows)
    return changed


def mark_all_read(recipient: str) -> int:
    """Mark every unread notification for `recipient` as read. Returns
    the count that were flipped."""
    if not recipient:
        return 0
    with _LOCK:
        rows = _load_raw(recipient)
        ts = _now()
        n = 0
        for r in rows:
            if not r.get("read_at"):
                r["read_at"] = ts
                n += 1
        if n:
            _save_raw(recipient, rows)
    return n


def clear(recipient: str) -> int:
    """Delete every notification for a recipient. Used by tests; also
    handy for an "archive all" admin action down the line. Returns the
    count removed."""
    if not recipient:
        return 0
    with _LOCK:
        rows = _load_raw(recipient)
        n = len(rows)
        _save_raw(recipient, [])
    return n
