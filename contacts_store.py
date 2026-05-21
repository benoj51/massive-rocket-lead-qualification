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
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
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
        p.write_text(json.dumps(contacts, indent=2))


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
    }


def _parse_iso(s: str | None):
    """Parse our ISO-Z timestamps back to a tz-aware datetime."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def annotate_touch_state(contact: dict[str, Any]) -> dict[str, Any]:
    """Add derived touch fields (overdue, days_since_touch, etc.) in
    place. Mirror of partner_contacts_store.annotate_touch_state."""
    cadence = int(contact.get("cadence_days") or 30)
    last = _parse_iso(contact.get("last_touched_at"))
    baseline = last or _parse_iso(contact.get("added_at"))
    if baseline is None:
        contact["next_touch_due"] = None
        contact["days_since_touch"] = None
        contact["days_until_due"] = 0
        contact["overdue"] = False
        contact["is_due_soon"] = False
        return contact
    now = datetime.now(timezone.utc)
    days_since = (now - baseline).days
    due_at = baseline + timedelta(days=cadence)
    days_until_due = (due_at - now).days
    contact["next_touch_due"] = due_at.isoformat(timespec="seconds").replace("+00:00", "Z")
    contact["days_since_touch"] = days_since if last else None
    contact["days_until_due"] = days_until_due
    contact["overdue"] = days_until_due < 0
    contact["is_due_soon"] = 0 <= days_until_due <= 7
    return contact


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
