"""
Persistent contacts per lead.

Stores one JSON file per lead at cache/contacts/<lead_id>.json. Each contact
is keyed by a stable id (the Apollo person id if available; a generated UUID
otherwise). One contact per lead can be marked `is_primary` — that's the
"key contact" surfaced on the lead.

Public surface:
    list_contacts(lead_id)                 -> list[dict]
    save_contact(lead_id, contact)         -> the persisted contact
    delete_contact(lead_id, contact_id)    -> bool
    set_primary(lead_id, contact_id)       -> the now-primary contact
    primary_contact(lead_id)               -> dict | None

Contact shape (lenient — only `id` and at least one of name/email required):
    {
        "id":            str,
        "name":          str,
        "title":         str | None,
        "email":         str | None,
        "linkedin_url":  str | None,
        "phone":         str | None,
        "city":          str | None,
        "country":       str | None,
        "is_primary":    bool,
        "added_at":      ISO timestamp,
        "source":        "apollo" | "manual" | str  (where the row came from)
    }
"""
from __future__ import annotations

import json
import json_file_store
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DIR = Path(__file__).parent / "cache" / "contacts"
_LOCK = threading.Lock()


class ContactsStoreError(RuntimeError):
    pass


def _store_dir() -> Path:
    override = os.environ.get("CONTACTS_STORE_DIR")
    d = Path(override) if override else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(lead_id: str) -> Path:
    import project_store
    return _store_dir() / f"{project_store.slugify(lead_id)}.json"


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


def _write_raw(lead_id: str, contacts: list[dict[str, Any]]) -> None:
    p = _path(lead_id)
    with _LOCK:
        json_file_store.write_json_backup(p, contacts)


STATUSES = ["active", "dormant", "left"]


def _normalise(contact: dict[str, Any]) -> dict[str, Any]:
    name = (contact.get("name") or "").strip()
    email = (contact.get("email") or "").strip()
    if not name and not email:
        raise ContactsStoreError("Contact requires at least name or email")
    # v1.0.0a (Tier 1c): touch cadence + status parity with partner contacts.
    # Default cadence 30 days; clamp 1-365.
    raw_cadence = contact.get("cadence_days")
    if raw_cadence is None or raw_cadence == "":
        cadence_days = 30
    else:
        try:
            cadence_days = int(raw_cadence)
        except (TypeError, ValueError):
            cadence_days = 30
    cadence_days = max(1, min(cadence_days, 365))
    status = (contact.get("status") or "active").strip().lower() or "active"
    if status not in STATUSES:
        status = "active"
    return {
        "id": str(contact.get("id") or "").strip() or uuid.uuid4().hex[:12],
        "name": name,
        "title": (contact.get("title") or "").strip() or None,
        "email": email or None,
        "email_status": (contact.get("email_status") or "").strip() or None,
        "linkedin_url": (contact.get("linkedin_url") or "").strip() or None,
        "phone": (contact.get("phone") or "").strip() or None,
        "city": (contact.get("city") or "").strip() or None,
        "country": (contact.get("country") or "").strip() or None,
        "is_primary": bool(contact.get("is_primary")),
        "status": status,
        "cadence_days": cadence_days,
        "last_touched_at": contact.get("last_touched_at") or None,
        "added_at": contact.get("added_at") or _now(),
        "updated_at": _now(),
        "source": (contact.get("source") or "manual").strip() or "manual",
        # v1.0.0ar: optional reports-to link for the Account org chart.
        # Same shape as partner_contacts_store — FK to another contact
        # on the SAME lead. Empty string normalises to None so the chart
        # treats it as a root node.
        "reports_to_id": (contact.get("reports_to_id") or "").strip() or None,
        # v1.0.0bl: stakeholder map fields. Drive the influence×interest
        # matrix on live project detail. All optional + permissive so
        # existing contacts work untouched.
        # `stakeholder_role`: their role in the buying / delivery group.
        # `influence`: how much sway they have (high|medium|low|None).
        # `interest`: how much they care about MR's work (same scale).
        "stakeholder_role": _validate_stakeholder_enum(
            contact.get("stakeholder_role"),
            ("sponsor", "champion", "user", "blocker", "unknown")),
        "influence": _validate_stakeholder_enum(
            contact.get("influence"), ("high", "medium", "low")),
        "interest":  _validate_stakeholder_enum(
            contact.get("interest"),  ("high", "medium", "low")),
    }


def _validate_stakeholder_enum(value, allowed):
    """v1.0.0bl: coerce to a known value or None. Anything unrecognised
    (including empty string) → None — keeps old data clean and stops
    typos polluting the matrix."""
    if value is None or value == "":
        return None
    s = str(value).strip().lower()
    return s if s in allowed else None


# v1.0.0cg: cadence logic moved to contact_cadence.py so partner_contacts_store
# (which had a byte-identical copy) can share it. _parse_iso + annotate_touch_state
# kept as thin shims for any external caller that imports them by name.
from contact_cadence import (
    parse_iso as _parse_iso,
    annotate_touch_state,
)


def touch_contact(lead_id: str, contact_id: str, *,
                   at: str | None = None) -> dict[str, Any] | None:
    """Bump last_touched_at for an explicit "I just talked to them" action."""
    rows = _load_raw(lead_id)
    when = at or _now()
    found = None
    for r in rows:
        if r.get("id") == contact_id:
            r["last_touched_at"] = when
            r["updated_at"] = _now()
            found = r
            break
    if found is None:
        return None
    _write_raw(lead_id, rows)
    return found


def list_contacts(lead_id: str) -> list[dict[str, Any]]:
    """Return all contacts for a lead, primary first then by recency.
    v1.0.0a: each row is annotated with touch state (overdue,
    days_until_due, etc.) for the UI."""
    rows = _load_raw(lead_id)
    rows.sort(key=lambda r: (not r.get("is_primary"), r.get("added_at") or ""), reverse=False)
    for r in rows:
        annotate_touch_state(r)
    return rows


def overdue_contacts(lead_id: str | None = None) -> list[dict[str, Any]]:
    """Active contacts past their cadence. Pass lead_id to scope to one
    lead; omit for a cross-lead roster (Today/overview surface)."""
    if lead_id:
        contacts = list_contacts(lead_id)
        return [c for c in contacts
                if c.get("status") == "active" and c.get("overdue")]
    # Cross-lead scan
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
        if not isinstance(rows, list):
            continue
        for r in rows:
            annotate_touch_state(r)
            if r.get("status") == "active" and r.get("overdue"):
                r["lead_id"] = lead_slug
                out.append(r)
    return out


def save_contact(lead_id: str, contact: dict[str, Any]) -> dict[str, Any]:
    """Add or update by id. Returns the persisted record."""
    clean = _normalise(contact)
    rows = _load_raw(lead_id)
    found = False
    for i, r in enumerate(rows):
        if r.get("id") == clean["id"]:
            # Preserve original added_at; everything else replaces
            clean["added_at"] = r.get("added_at") or clean["added_at"]
            rows[i] = clean
            found = True
            break
    if not found:
        rows.append(clean)
    # If this one is_primary, clear is_primary on all others
    if clean["is_primary"]:
        for r in rows:
            if r["id"] != clean["id"]:
                r["is_primary"] = False
    _write_raw(lead_id, rows)
    return clean


def save_many(lead_id: str, contacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bulk save. Returns the saved entries (ignores invalid)."""
    saved: list[dict[str, Any]] = []
    for c in contacts or []:
        try:
            saved.append(save_contact(lead_id, c))
        except ContactsStoreError:
            continue
    return saved


def delete_contact(lead_id: str, contact_id: str) -> bool:
    rows = _load_raw(lead_id)
    new_rows = [r for r in rows if r.get("id") != contact_id]
    if len(new_rows) == len(rows):
        return False
    _write_raw(lead_id, new_rows)
    return True


def set_primary(lead_id: str, contact_id: str) -> dict[str, Any] | None:
    rows = _load_raw(lead_id)
    target: dict[str, Any] | None = None
    for r in rows:
        if r.get("id") == contact_id:
            r["is_primary"] = True
            target = r
        else:
            r["is_primary"] = False
    if not target:
        return None
    _write_raw(lead_id, rows)
    return target


def primary_contact(lead_id: str) -> dict[str, Any] | None:
    for r in _load_raw(lead_id):
        if r.get("is_primary"):
            return r
    return None
