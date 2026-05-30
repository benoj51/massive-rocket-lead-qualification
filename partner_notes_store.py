"""
Per-contact touch-point notes under a partner (v0.10.0y).

Each note is a short prose record of an interaction — a call, an email,
an intro, a touch-base. Notes are scoped to a (partner_id, contact_id)
pair so removing a contact doesn't leak notes elsewhere.

Storage: cache/partner_notes/<partner_slug>__<contact_id>.json — one
list per contact. Two-segment filename keeps the lookup deterministic.

Schema per note:
    {
      "id":          str (uuid),
      "partner_id":  str,
      "contact_id":  str,
      "type":        str,        # call / email / intro / touch / other
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

_DEFAULT_DIR = Path(__file__).parent / "cache" / "partner_notes"

NOTE_TYPES = ["call", "email", "intro", "touch", "other"]


class PartnerNotesStoreError(RuntimeError):
    pass


def _store_dir() -> Path:
    override = os.environ.get("PARTNER_NOTES_STORE_DIR")
    d = Path(override) if override else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slugify(value: str) -> str:
    import project_store
    return project_store.slugify(value)


def _path(partner_id: str, contact_id: str) -> Path:
    # Both segments are slugified so a hostile contact_id path segment
    # cannot escape the store dir or collide via odd characters.
    return _store_dir() / f"{_slugify(partner_id)}__{_slugify(contact_id)}.json"


def _now_iso() -> str:
    # microsecond precision so list sorts cleanly on multiple-per-second adds
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _load_raw(partner_id: str, contact_id: str, *, strict: bool = False) -> list[dict[str, Any]]:
    """Load this contact's notes. v1.0.0dp: routed through the
    corruption-aware loader. Mutation callers pass strict=True so a file
    we cannot read aborts the write (translated to our own error type)
    instead of silently clobbering recoverable history; read callers use
    the default lenient mode (returns [], recovers from .bak)."""
    import json_file_store
    try:
        return json_file_store.load_list_safe(_path(partner_id, contact_id), strict=strict)
    except json_file_store.CorruptStoreError as e:
        raise PartnerNotesStoreError(
            "note history file is unreadable; refusing to save so existing "
            "notes are not overwritten") from e


def _write_raw(partner_id: str, contact_id: str, notes: list[dict[str, Any]]) -> None:
    # v1.0.0cu: atomic write via json_file_store - prevents partial JSON
    # writes from corrupting note history on a crash.
    # v1.0.0dp: write_json_backup adds a .bak sidecar so a bad write or
    # an accidental wipe stays recoverable.
    import json_file_store
    json_file_store.write_json_backup(_path(partner_id, contact_id), notes)


def list_notes(partner_id: str, contact_id: str) -> list[dict[str, Any]]:
    """All notes for a contact, newest first."""
    rows = _load_raw(partner_id, contact_id)
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return rows


def add_note(partner_id: str, contact_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    content = (payload.get("content") or "").strip()
    if not content:
        raise PartnerNotesStoreError("Note content is required")
    note = {
        "id": uuid.uuid4().hex[:12],
        "partner_id": _slugify(partner_id),
        "contact_id": contact_id,
        "type": (payload.get("type") or "touch").strip().lower(),
        "content": content,
        "author": (payload.get("author") or "").strip() or None,
        "created_at": _now_iso(),
    }
    rows = _load_raw(partner_id, contact_id, strict=True)
    rows.append(note)
    _write_raw(partner_id, contact_id, rows)
    return note


def delete_note(partner_id: str, contact_id: str, note_id: str) -> bool:
    rows = _load_raw(partner_id, contact_id, strict=True)
    new_rows = [r for r in rows if r.get("id") != note_id]
    if len(new_rows) == len(rows):
        return False
    _write_raw(partner_id, contact_id, new_rows)
    return True


def delete_all_for_contact(partner_id: str, contact_id: str) -> bool:
    """Cascade delete — called when a contact is removed so we don't
    leak orphan notes."""
    import json_file_store
    p = _path(partner_id, contact_id)
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
