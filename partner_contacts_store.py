"""
Partner contacts (v0.10.0y).

Per-partner contact list with the metadata the Partnerships team needs:
territory, region, country, industries (multi), MR owner, and an optional
reports-to link for an org chart later.

Storage: one JSON file per partner at
cache/partner_contacts/<partner_slug>.json — same pattern as the
lead-side `contacts_store`, so AE muscle memory carries.

Schema per contact:
    {
      "id":          str (uuid or slug),
      "partner_id":  str (FK to partners_store),
      "name":        str,
      "title":       str | None,
      "email":       str | None,
      "linkedin_url": str | None,
      "phone":       str | None,
      "territory":   str | None,    # Strategic Enterprise / Enterprise / Mid-Market
      "region":      str | None,    # UK / West Coast / East Coast / Central / EMEA / APAC
      "country":     str | None,    # free text (or from the country dropdown list)
      "industries":  list[str],     # multi-select; from INDUSTRIES enum
      "mr_owner":    str | None,    # who at MR manages this relationship
      "reports_to_id": str | None,  # FK to another contact in the SAME partner
      "status":      str,           # active / dormant / left
      "tags":        list[str],     # free-form tags
      "added_at":    str,
      "updated_at":  str,
    }

Public API:
    list_contacts(partner_id)                  -> [contact_dict]
    get_contact(partner_id, contact_id)        -> contact_dict | None
    save_contact(partner_id, contact)          -> persisted contact (id assigned if absent)
    delete_contact(partner_id, contact_id)     -> bool
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DIR = Path(__file__).parent / "cache" / "partner_contacts"
_LOCK = threading.Lock()


# Enumerations the UI offers as dropdowns / chip multi-selects. Edit here
# to change the available choices; the UI mirrors them.
TERRITORIES = ["Strategic Enterprise", "Enterprise", "Mid-Market", "SMB"]
REGIONS = ["UK", "West Coast", "East Coast", "Central",
           "EMEA", "APAC", "LATAM", "ANZ", "Global"]
INDUSTRIES = ["QSR", "C-Store / Gas", "Retail", "Financial Services",
              "Travel & Hospitality", "Healthcare", "Media",
              "Telecom", "SaaS", "Other"]
STATUSES = ["active", "dormant", "left"]


class PartnerContactsStoreError(RuntimeError):
    pass


def _store_dir() -> Path:
    override = os.environ.get("PARTNER_CONTACTS_STORE_DIR")
    d = Path(override) if override else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slugify(value: str) -> str:
    import project_store
    return project_store.slugify(value)


def _path(partner_id: str) -> Path:
    return _store_dir() / f"{_slugify(partner_id)}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_raw(partner_id: str) -> list[dict[str, Any]]:
    p = _path(partner_id)
    if not p.exists():
        return []
    try:
        with _LOCK:
            return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _write_raw(partner_id: str, contacts: list[dict[str, Any]]) -> None:
    with _LOCK:
        _path(partner_id).write_text(json.dumps(contacts, indent=2))


def _normalise(partner_id: str, contact: dict[str, Any]) -> dict[str, Any]:
    name = (contact.get("name") or "").strip()
    email = (contact.get("email") or "").strip()
    if not name and not email:
        raise PartnerContactsStoreError("Contact requires at least name or email")
    cid = (contact.get("id") or "").strip() or uuid.uuid4().hex[:12]
    industries = contact.get("industries") or []
    if isinstance(industries, str):
        industries = [s.strip() for s in industries.split(",") if s.strip()]
    industries = [str(i).strip() for i in industries if str(i).strip()]
    return {
        "id": cid,
        "partner_id": _slugify(partner_id),
        "name": name,
        "title": (contact.get("title") or "").strip() or None,
        "email": email or None,
        "linkedin_url": (contact.get("linkedin_url") or "").strip() or None,
        "phone": (contact.get("phone") or "").strip() or None,
        "territory": (contact.get("territory") or "").strip() or None,
        "region": (contact.get("region") or "").strip() or None,
        "country": (contact.get("country") or "").strip() or None,
        "industries": industries,
        "mr_owner": (contact.get("mr_owner") or "").strip() or None,
        "reports_to_id": (contact.get("reports_to_id") or "").strip() or None,
        "status": (contact.get("status") or "active").strip().lower(),
        "tags": [str(t).strip() for t in (contact.get("tags") or []) if str(t).strip()],
        "added_at": contact.get("added_at") or _now(),
        "updated_at": _now(),
    }


def list_contacts(partner_id: str) -> list[dict[str, Any]]:
    """All contacts under this partner, sorted active-first then alpha."""
    rows = _load_raw(partner_id)
    rows.sort(key=lambda r: (
        r.get("status") != "active",
        (r.get("name") or "").lower(),
    ))
    return rows


def get_contact(partner_id: str, contact_id: str) -> dict[str, Any] | None:
    for r in _load_raw(partner_id):
        if r.get("id") == contact_id:
            return r
    return None


def save_contact(partner_id: str, contact: dict[str, Any]) -> dict[str, Any]:
    """Add or update a contact by id."""
    clean = _normalise(partner_id, contact)
    rows = _load_raw(partner_id)
    for i, r in enumerate(rows):
        if r.get("id") == clean["id"]:
            clean["added_at"] = r.get("added_at") or clean["added_at"]
            rows[i] = clean
            _write_raw(partner_id, rows)
            return clean
    rows.append(clean)
    _write_raw(partner_id, rows)
    return clean


def delete_contact(partner_id: str, contact_id: str) -> bool:
    rows = _load_raw(partner_id)
    new_rows = [r for r in rows if r.get("id") != contact_id]
    if len(new_rows) == len(rows):
        return False
    _write_raw(partner_id, new_rows)
    return True


def list_all_contacts() -> list[dict[str, Any]]:
    """Across-partner roster — for cross-cutting search / global filters."""
    out: list[dict[str, Any]] = []
    if not _store_dir().exists():
        return out
    for f in _store_dir().glob("*.json"):
        try:
            data = json.loads(f.read_text())
            if isinstance(data, list):
                out.extend(data)
        except (json.JSONDecodeError, OSError):
            continue
    return out
