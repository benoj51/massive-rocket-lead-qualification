"""v1.0.0am — Per-user todo store.

Ben asked: "They should also be able to create a custom to do list on
their home page."

Design
------
- One JSON file per owner slug (slugified MR-owner name).
- A todo carries: text, done flag, optional priority + due date,
  created/completed timestamps. No assignment to others — these are
  the user's own scratch list, not a delegation tool.
- No ring-buffer cap: todos are user-curated, the user is the one
  who decides when to clear them. We do soft-delete (purge on DELETE).

Shape
-----
    {
      "id":           "<uuid4>",
      "owner":        "Ben Ojuolape",
      "owner_slug":   "ben-ojuolape",
      "text":         "Follow up with Marina on the v2 demo",
      "done":         false,
      "priority":     "high" | "medium" | "low" | None,
      "due_date":     "2026-05-30" | None,
      "created_at":   "2026-05-23T19:45:00Z",
      "completed_at": None | iso8601,
    }

API
---
    list_for(owner, *, include_done=True) -> list[dict]
    create(owner, text, *, priority=None, due_date=None) -> dict
    update(owner, todo_id, **fields) -> dict | None
    delete(owner, todo_id) -> bool
    toggle_done(owner, todo_id) -> dict | None    # convenience wrapper
    clear_completed(owner) -> int                  # returns count removed
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DIR = Path(__file__).parent / "cache" / "todos"
_LOCK = threading.Lock()

PRIORITIES = ("high", "medium", "low")


class TodosStoreError(RuntimeError):
    pass


def _store_dir() -> Path:
    override = os.environ.get("TODOS_STORE_DIR")
    d = Path(override) if override else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slugify(value: str) -> str:
    if not value:
        return "unknown"
    s = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return s.strip("-") or "unknown"


def _path(owner: str) -> Path:
    return _store_dir() / f"{_slugify(owner)}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_raw(owner: str) -> list[dict[str, Any]]:
    p = _path(owner)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
        if not isinstance(data, list):
            return []
        return data
    except (OSError, ValueError):
        return []


def _save_raw(owner: str, rows: list[dict[str, Any]]) -> None:
    p = _path(owner)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows, indent=2, ensure_ascii=False))


def _normalise(t: dict[str, Any]) -> dict[str, Any]:
    out = dict(t)
    out.setdefault("id", uuid.uuid4().hex)
    out.setdefault("text", "")
    out.setdefault("done", False)
    out.setdefault("priority", None)
    out.setdefault("due_date", None)
    out.setdefault("created_at", _now())
    out.setdefault("completed_at", None)
    out.setdefault("owner", out.get("owner") or "Unknown")
    out.setdefault("owner_slug", _slugify(out["owner"]))
    return out


def _validate_priority(p: Any) -> str | None:
    if p in (None, ""):
        return None
    if isinstance(p, str) and p.lower() in PRIORITIES:
        return p.lower()
    raise TodosStoreError(f"priority must be one of {PRIORITIES} or None; got {p!r}")


def _validate_due(d: Any) -> str | None:
    if d in (None, ""):
        return None
    if not isinstance(d, str):
        raise TodosStoreError(f"due_date must be a YYYY-MM-DD string or None; got {d!r}")
    # Light-touch validation: YYYY-MM-DD shape. We don't insist on a
    # real calendar date so the user can store fuzzy "2026-13-01" if
    # they want to — the UI is the source of truth for date pickers.
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
        raise TodosStoreError(f"due_date must look like YYYY-MM-DD; got {d!r}")
    return d


# ---- core API -------------------------------------------------------------

def list_for(owner: str, *, include_done: bool = True) -> list[dict[str, Any]]:
    """Return todos for `owner`. Sort order:
      1. Open (not done) before done
      2. Within each bucket: priority (high > medium > low > none),
         then due_date ascending (sooner first, None last),
         then created_at descending (newest first as tiebreaker)
    """
    if not owner:
        return []
    with _LOCK:
        rows = [_normalise(r) for r in _load_raw(owner)]
    if not include_done:
        rows = [r for r in rows if not r.get("done")]
    pri_rank = {"high": 0, "medium": 1, "low": 2, None: 3}

    def _key(r: dict[str, Any]):
        done = 1 if r.get("done") else 0
        pri = pri_rank.get(r.get("priority"), 3)
        due = r.get("due_date") or "9999-99-99"
        created_neg = "0000" if not r.get("created_at") else _invert(r["created_at"])
        return (done, pri, due, created_neg)

    rows.sort(key=_key)
    return rows


def _invert(s: str) -> str:
    """Cheap descending-sort helper: invert the codepoints so that a
    newer ISO timestamp sorts BEFORE an older one in an ascending sort.
    Avoids two-pass sorts for the secondary descending key."""
    return "".join(chr(0x10FFFF - ord(c)) if ord(c) < 0x10FFFF else c for c in s)


def create(owner: str, text: str, *,
            priority: str | None = None,
            due_date: str | None = None) -> dict[str, Any]:
    if not (owner or "").strip():
        raise TodosStoreError("owner required")
    text = (text or "").strip()
    if not text:
        raise TodosStoreError("text required")
    if len(text) > 500:
        raise TodosStoreError("text too long (max 500 chars)")
    todo = _normalise({
        "id":           uuid.uuid4().hex,
        "owner":        owner.strip(),
        "text":         text,
        "done":         False,
        "priority":     _validate_priority(priority),
        "due_date":     _validate_due(due_date),
        "created_at":   _now(),
        "completed_at": None,
    })
    with _LOCK:
        rows = _load_raw(owner)
        rows.append(todo)
        _save_raw(owner, rows)
    return todo


def update(owner: str, todo_id: str, **fields: Any) -> dict[str, Any] | None:
    """Patch fields on a single todo. Allowed: text, done, priority,
    due_date. Returns the updated todo or None if not found."""
    if not (owner and todo_id):
        return None
    allowed = {"text", "done", "priority", "due_date"}
    bad = set(fields) - allowed
    if bad:
        raise TodosStoreError(f"unknown fields: {sorted(bad)}")
    with _LOCK:
        rows = _load_raw(owner)
        target = None
        for r in rows:
            if r.get("id") == todo_id:
                target = r
                break
        if target is None:
            return None
        if "text" in fields:
            t = (fields["text"] or "").strip()
            if not t:
                raise TodosStoreError("text cannot be empty")
            if len(t) > 500:
                raise TodosStoreError("text too long (max 500 chars)")
            target["text"] = t
        if "priority" in fields:
            target["priority"] = _validate_priority(fields["priority"])
        if "due_date" in fields:
            target["due_date"] = _validate_due(fields["due_date"])
        if "done" in fields:
            new_done = bool(fields["done"])
            # completed_at only set on the false→true transition, cleared
            # on the true→false transition. Avoids stomping a timestamp
            # the user might want preserved if they un-check and re-check.
            if new_done and not target.get("done"):
                target["completed_at"] = _now()
            elif not new_done and target.get("done"):
                target["completed_at"] = None
            target["done"] = new_done
        _save_raw(owner, rows)
        return _normalise(target)


def toggle_done(owner: str, todo_id: str) -> dict[str, Any] | None:
    """Flip the done flag in one call. Returns the updated todo.

    NOTE: must NOT acquire _LOCK and then call update() — Python's
    threading.Lock is non-reentrant, so a nested acquire deadlocks.
    Read the current state without the lock, then delegate to update()
    which acquires the lock once for the write. Tiny TOCTOU window
    (another writer could flip the same todo between read and write)
    is acceptable for a single-user scratch list.
    """
    if not (owner and todo_id):
        return None
    current = None
    with _LOCK:
        for r in _load_raw(owner):
            if r.get("id") == todo_id:
                current = bool(r.get("done"))
                break
    if current is None:
        return None
    return update(owner, todo_id, done=not current)


def delete(owner: str, todo_id: str) -> bool:
    if not (owner and todo_id):
        return False
    with _LOCK:
        rows = _load_raw(owner)
        new = [r for r in rows if r.get("id") != todo_id]
        if len(new) == len(rows):
            return False
        _save_raw(owner, new)
    return True


def clear_completed(owner: str) -> int:
    """Bulk-remove every done todo. Returns the count removed."""
    if not owner:
        return 0
    with _LOCK:
        rows = _load_raw(owner)
        new = [r for r in rows if not r.get("done")]
        n = len(rows) - len(new)
        if n:
            _save_raw(owner, new)
    return n
