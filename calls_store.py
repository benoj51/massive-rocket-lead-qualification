"""
Persistent call / note log per lead.

Stores one JSON file per lead at cache/calls/<lead_id>.json, holding a list
of call records. Each record captures the AE's notes from a call or
transcript paste, the AI extraction results, and the timestamp.

Records are immutable once written (except for deletion). To "edit" a
record, the AE adds a new one with corrected content.

Public surface:
    list_calls(lead_id)                -> list[dict] (newest first)
    add_call(lead_id, payload)         -> the persisted record
    delete_call(lead_id, call_id)      -> bool
    aggregate_extractions(lead_id)     -> {meddpicc: {...}, signals: [...], project_scope: str|None}
        Merges extraction results across all calls (newer wins).

Record shape:
    {
        "id":            str,
        "lead_id":       str,
        "created_at":    ISO timestamp,
        "type":          "call" | "note" | "email" | "transcript",
        "title":         str,                   # optional headline
        "attendees":     list[str],             # contact names if known
        "content":       str,                   # the raw notes/transcript
        "extracted":     {meddpicc: {...}, project_scope: str|None}  # optional AI output
    }
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DIR = Path(__file__).parent / "cache" / "calls"
_LOCK = threading.Lock()


class CallsStoreError(RuntimeError):
    pass


VALID_TYPES = {"call", "note", "email", "transcript"}


def _store_dir() -> Path:
    override = os.environ.get("CALLS_STORE_DIR")
    d = Path(override) if override else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(lead_id: str) -> Path:
    import project_store
    return _store_dir() / f"{project_store.slugify(lead_id)}.json"


def _now() -> str:
    # Microsecond precision so back-to-back saves sort deterministically.
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _load_raw(lead_id: str) -> list[dict[str, Any]]:
    p = _path(lead_id)
    if not p.exists():
        return []
    try:
        with _LOCK:
            return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _write_raw(lead_id: str, rows: list[dict[str, Any]]) -> None:
    p = _path(lead_id)
    with _LOCK:
        p.write_text(json.dumps(rows, indent=2))


def list_calls(lead_id: str) -> list[dict[str, Any]]:
    rows = _load_raw(lead_id)
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return rows


def add_call(lead_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Append a new call/note record. Returns the persisted record."""
    content = (payload.get("content") or "").strip()
    if not content:
        raise CallsStoreError("content is required")
    call_type = (payload.get("type") or "note").strip().lower()
    if call_type not in VALID_TYPES:
        call_type = "note"
    record: dict[str, Any] = {
        "id": str(payload.get("id") or "").strip() or uuid.uuid4().hex[:12],
        "lead_id": lead_id,
        "created_at": _now(),
        "type": call_type,
        "title": (payload.get("title") or "").strip(),
        "attendees": [str(a).strip() for a in (payload.get("attendees") or []) if str(a).strip()],
        "content": content,
        "extracted": payload.get("extracted") or None,
    }
    rows = _load_raw(lead_id)
    rows.append(record)
    _write_raw(lead_id, rows)
    return record


def delete_call(lead_id: str, call_id: str) -> bool:
    rows = _load_raw(lead_id)
    new_rows = [r for r in rows if r.get("id") != call_id]
    if len(new_rows) == len(rows):
        return False
    _write_raw(lead_id, new_rows)
    return True


def aggregate_extractions(lead_id: str) -> dict[str, Any]:
    """Merge extraction results across all calls. Newer records win.

    Useful for building a "rolling" MEDDPICC view that reflects everything
    we've learned about the lead — not just the most recent qualification.
    """
    calls = sorted(_load_raw(lead_id), key=lambda r: r.get("created_at") or "")
    meddpicc: dict[str, Any] = {}
    project_scope: str | None = None
    for c in calls:
        ext = c.get("extracted") or {}
        for k, v in (ext.get("meddpicc") or {}).items():
            if isinstance(v, dict) and v.get("value"):
                meddpicc[k] = {"value": v["value"]}
        if ext.get("project_scope"):
            project_scope = ext["project_scope"]
    return {"meddpicc": meddpicc, "project_scope": project_scope}
