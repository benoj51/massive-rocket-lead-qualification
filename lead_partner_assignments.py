"""
Lead ↔ Partner-contact assignments (v0.11.0).

Links partner contacts to leads so the AE knows who the right Braze /
Snowflake / mParticle person is for a given account. Many-to-many:
- A lead can have multiple partner contacts assigned (Braze AE + Hightouch SE)
- A partner contact can be assigned to many leads (Marina Klusas
  covers Yum + Restaurant Brands + IHG)

Storage: one JSON file per lead at
cache/lead_partner_assignments/<lead_slug>.json
Each row: {partner_id, contact_id, assigned_at, assigned_by, note}

Public API:
    list_for_lead(lead_id)                         -> [assignment]
    list_for_contact(partner_id, contact_id)       -> [{lead_id, ...}]
    assign(lead_id, partner_id, contact_id, ...)   -> assignment (idempotent)
    unassign(lead_id, partner_id, contact_id)      -> bool
"""
from __future__ import annotations

import json
import json_file_store
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DIR = Path(__file__).parent / "cache" / "lead_partner_assignments"
_LOCK = threading.Lock()


class AssignmentsStoreError(RuntimeError):
    pass


def _slugify(value: str) -> str:
    import project_store
    return project_store.slugify(value)


def _store_dir() -> Path:
    override = os.environ.get("LEAD_PARTNER_ASSIGN_DIR")
    d = Path(override) if override else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(lead_id: str) -> Path:
    return _store_dir() / f"{_slugify(lead_id)}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


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
    with _LOCK:
        json_file_store.write_json_backup(_path(lead_id), rows)


def _key(partner_id: str, contact_id: str) -> tuple[str, str]:
    return (_slugify(partner_id), str(contact_id).strip())


def list_for_lead(lead_id: str) -> list[dict[str, Any]]:
    """Raw assignments for a lead. Caller enriches with partner + contact
    details (the server does this in the endpoint)."""
    return _load_raw(lead_id)


def list_for_contact(partner_id: str, contact_id: str) -> list[dict[str, Any]]:
    """All leads a partner-contact is assigned to. Across-leads scan —
    fine at our scale (~hundreds of leads max)."""
    pid_norm, cid_norm = _key(partner_id, contact_id)
    out: list[dict[str, Any]] = []
    d = _store_dir()
    if not d.exists():
        return out
    for f in d.glob("*.json"):
        lead_slug = f.stem
        try:
            rows = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for r in rows:
            if (r.get("partner_id") == pid_norm and r.get("contact_id") == cid_norm):
                out.append({**r, "lead_id": lead_slug})
                break
    return out


def assign(lead_id: str, partner_id: str, contact_id: str,
           *, assigned_by: str | None = None,
           note: str | None = None) -> dict[str, Any]:
    """Add a partner-contact ↔ lead link. Idempotent: re-assigning the
    same (partner_id, contact_id) updates `note` + `assigned_by` and
    leaves `assigned_at` untouched.
    """
    # Validate the raw inputs BEFORE slugifying — slugify("") returns
    # the "unknown" fallback which would silently corrupt the store.
    if not (partner_id or "").strip() or not (contact_id or "").strip():
        raise AssignmentsStoreError("partner_id and contact_id required")
    pid_norm, cid_norm = _key(partner_id, contact_id)
    rows = _load_raw(lead_id)
    for r in rows:
        if r.get("partner_id") == pid_norm and r.get("contact_id") == cid_norm:
            # Update mutable fields, preserve assigned_at + history.
            if note is not None:
                r["note"] = note
            if assigned_by:
                r["assigned_by"] = assigned_by
            r["updated_at"] = _now()
            _write_raw(lead_id, rows)
            return r
    row = {
        "partner_id": pid_norm,
        "contact_id": cid_norm,
        "assigned_at": _now(),
        "assigned_by": (assigned_by or "").strip() or None,
        "note": (note or "").strip() or None,
    }
    rows.append(row)
    _write_raw(lead_id, rows)
    return row


def unassign(lead_id: str, partner_id: str, contact_id: str) -> bool:
    pid_norm, cid_norm = _key(partner_id, contact_id)
    rows = _load_raw(lead_id)
    new_rows = [r for r in rows
                if not (r.get("partner_id") == pid_norm and r.get("contact_id") == cid_norm)]
    if len(new_rows) == len(rows):
        return False
    _write_raw(lead_id, new_rows)
    return True


def assignments_count(lead_id: str) -> int:
    return len(_load_raw(lead_id))
