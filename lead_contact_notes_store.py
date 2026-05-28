"""
Per-(lead, contact) engagement timeline (v1.0.0b — Tier 1d).

Mirrors the partner-side `partner_notes_store`: each note is a short
prose record of an interaction with a specific lead contact (call,
email, intro, touch-base, follow-up). Scoped to (lead_id, contact_id)
so deleting a contact doesn't leak notes elsewhere.

Storage: cache/lead_contact_notes/<lead_slug>__<contact_id>.json.

Schema per note:
    {
      "id":          str (uuid),
      "lead_id":     str,
      "contact_id":  str,
      "type":        str,        # call / email / intro / touch /
                                  # follow_up / other
      "content":     str,
      "author":      str | None,
      "created_at":  str,
    }
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DIR = Path(__file__).parent / "cache" / "lead_contact_notes"

NOTE_TYPES = ["call", "email", "intro", "touch", "follow_up", "other"]


class LeadContactNotesStoreError(RuntimeError):
    pass


def _store_dir() -> Path:
    override = os.environ.get("LEAD_CONTACT_NOTES_STORE_DIR")
    d = Path(override) if override else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slugify(value: str) -> str:
    import project_store
    return project_store.slugify(value)


def _path(lead_id: str, contact_id: str) -> Path:
    return _store_dir() / f"{_slugify(lead_id)}__{contact_id}.json"


def _now_iso() -> str:
    # microsecond precision so multiple-per-second adds sort cleanly
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _load_raw(lead_id: str, contact_id: str, *, strict: bool = False) -> list[dict[str, Any]]:
    """Load this contact's notes. v1.0.0dp: routed through the
    corruption-aware loader. Mutation callers pass strict=True so a file
    we cannot read aborts the write (translated to our own error type)
    instead of silently clobbering recoverable history; read callers use
    the default lenient mode (returns [], recovers from .bak)."""
    import json_file_store
    try:
        return json_file_store.load_list_safe(_path(lead_id, contact_id), strict=strict)
    except json_file_store.CorruptStoreError as e:
        raise LeadContactNotesStoreError(
            "note history file is unreadable; refusing to save so existing "
            "notes are not overwritten") from e


def _write_raw(lead_id: str, contact_id: str, notes: list[dict[str, Any]]) -> None:
    # v1.0.0dp: atomic write + .bak sidecar (write_json_backup). Brings
    # this store in line with partner_notes_store / calls_store, which
    # migrated off plain write_text() in v1.0.0cu, and adds the backup
    # so a bad write or accidental wipe stays recoverable.
    import json_file_store
    json_file_store.write_json_backup(_path(lead_id, contact_id), notes)


def list_notes(lead_id: str, contact_id: str) -> list[dict[str, Any]]:
    """All notes for this lead contact, newest first."""
    rows = _load_raw(lead_id, contact_id)
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return rows


def add_note(lead_id: str, contact_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    content = (payload.get("content") or "").strip()
    if not content:
        raise LeadContactNotesStoreError("Note content is required")
    type_ = (payload.get("type") or "touch").strip().lower()
    if type_ not in NOTE_TYPES:
        type_ = "other"
    note = {
        "id": uuid.uuid4().hex[:12],
        "lead_id": _slugify(lead_id),
        "contact_id": contact_id,
        "type": type_,
        "content": content,
        "author": (payload.get("author") or "").strip() or None,
        "created_at": _now_iso(),
    }
    rows = _load_raw(lead_id, contact_id, strict=True)
    rows.append(note)
    _write_raw(lead_id, contact_id, rows)
    return note


def delete_note(lead_id: str, contact_id: str, note_id: str) -> bool:
    rows = _load_raw(lead_id, contact_id, strict=True)
    new_rows = [r for r in rows if r.get("id") != note_id]
    if len(new_rows) == len(rows):
        return False
    _write_raw(lead_id, contact_id, new_rows)
    return True


def delete_all_for_contact(lead_id: str, contact_id: str) -> bool:
    """Cascade delete — called when a contact is removed."""
    import json_file_store
    p = _path(lead_id, contact_id)
    if not p.exists():
        return False
    # v1.0.0dp: snapshot to .bak before the cascade removes the live
    # file, so an accidental contact deletion doesn't vaporise notes.
    json_file_store.backup_file(p)
    try:
        p.unlink()
        return True
    except OSError:
        return False
