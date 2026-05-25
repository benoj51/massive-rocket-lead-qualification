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
# v1.0.0h: Braze's hierarchy uses "Emerging Enterprise" + "Scale" as
# distinct segments. Added to the enum so the seed data lands cleanly
# without distortion.
TERRITORIES = ["Strategic Enterprise", "Enterprise", "Emerging Enterprise",
                "Mid-Market", "Scale", "SMB"]
REGIONS = ["UK", "West Coast", "East Coast", "Central",
           "EMEA", "APAC", "LATAM", "ANZ", "Global"]
# v1.0.0ac: Entertainment / Gaming / Sports added per Ben's roster.
INDUSTRIES = ["QSR", "C-Store / Gas", "Retail", "Financial Services",
              "Travel & Hospitality", "Healthcare", "Media",
              "Entertainment", "Gaming", "Sports",
              "Telecom", "SaaS", "Other"]
STATUSES = ["active", "dormant", "left"]
# v1.0.0ac: three new partnership-CRM dimensions on every partner contact.
# - Sentiment: how this contact feels about MR right now. Drives the
#   urgency of next touch + which deals to lean on them for.
# - Tier: how strategically important they are to the partnership.
# - Seniority: org-rank shorthand for who's the right escalation path.
# All three are user-editable via the Settings panel (enum_config_store).
PARTNER_SENTIMENTS = ["Champion", "Warm", "Neutral", "Cool", "Blocker"]
# v1.0.0ad: tiers describe IMPORTANCE TO MR (not engagement frequency
# — Last touch + cadence already cover that). T1 = relationships we
# cannot afford to lose; T4 = we know them, low priority.
TIERS              = ["T1 — Critical", "T2 — Important",
                       "T3 — Nurture", "T4 — Awareness"]
SENIORITIES        = ["C-Suite", "VP", "Director", "Manager",
                       "Individual Contributor"]


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


def _coerce_tag_list(value: Any) -> list[str]:
    """Accept either a string (legacy single value), comma-separated
    string (CSV imports), or list. Always return a deduped, trimmed list."""
    if value is None or value == "":
        return []
    if isinstance(value, str):
        # Comma-separated OR single value — both end up as a list.
        items = [s.strip() for s in value.split(",")]
    elif isinstance(value, (list, tuple)):
        items = [str(s).strip() for s in value]
    else:
        items = [str(value).strip()]
    # Dedupe while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for s in items:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _normalise(partner_id: str, contact: dict[str, Any]) -> dict[str, Any]:
    name = (contact.get("name") or "").strip()
    email = (contact.get("email") or "").strip()
    if not name and not email:
        raise PartnerContactsStoreError("Contact requires at least name or email")
    cid = (contact.get("id") or "").strip() or uuid.uuid4().hex[:12]
    # v1.0.0e (Tier 3b): territory + region are now multi-tag. Industries
    # were already multi. Accepts legacy single-string input for backward
    # compat (someone owns US OR they own US + Canada — both work).
    # Prefer the plural key (sent by the new UI); fall back to the
    # singular for old payloads or CSV imports.
    territories = _coerce_tag_list(
        contact.get("territories") if contact.get("territories") is not None
        else contact.get("territory")
    )
    regions = _coerce_tag_list(
        contact.get("regions") if contact.get("regions") is not None
        else contact.get("region")
    )
    industries = _coerce_tag_list(contact.get("industries"))
    # v0.10.0z: touch cadence fields. Defaults to 30 days. last_touched_at
    # bumps automatically when a note is added; the AE-edit flow does NOT
    # bump it (only intentional outreach counts as a touch).
    raw_cadence = contact.get("cadence_days")
    if raw_cadence is None or raw_cadence == "":
        cadence_days = 30
    else:
        try:
            cadence_days = int(raw_cadence)
        except (TypeError, ValueError):
            cadence_days = 30
    cadence_days = max(1, min(cadence_days, 365))
    return {
        "id": cid,
        "partner_id": _slugify(partner_id),
        "name": name,
        "title": (contact.get("title") or "").strip() or None,
        "email": email or None,
        "linkedin_url": (contact.get("linkedin_url") or "").strip() or None,
        "phone": (contact.get("phone") or "").strip() or None,
        # v1.0.0e: territory + region are now lists. Empty list means
        # "no tag" (replaces the old None convention).
        "territories": territories,
        "regions": regions,
        # Backward-compat shims: `territory` / `region` (singular) still
        # exposed as the FIRST tag for any caller that reads them. UI
        # writes always go through the multi-select chips → list path.
        "territory": territories[0] if territories else None,
        "region": regions[0] if regions else None,
        "country": (contact.get("country") or "").strip() or None,
        "industries": industries,
        "mr_owner": (contact.get("mr_owner") or "").strip() or None,
        "reports_to_id": (contact.get("reports_to_id") or "").strip() or None,
        "status": (contact.get("status") or "active").strip().lower(),
        # v1.0.0ac: three new partnership-CRM dimensions. All three are
        # free-text-ish strings (the UI presents a dropdown from the
        # editable enum config, but the store accepts any string so
        # legacy / custom values aren't blocked).
        "partner_sentiment": (contact.get("partner_sentiment") or "").strip() or None,
        "tier":              (contact.get("tier") or "").strip() or None,
        "seniority":         (contact.get("seniority") or "").strip() or None,
        "tags": [str(t).strip() for t in (contact.get("tags") or []) if str(t).strip()],
        "cadence_days": cadence_days,
        "last_touched_at": contact.get("last_touched_at") or None,
        "added_at": contact.get("added_at") or _now(),
        "updated_at": _now(),
    }


# v1.0.0cg: cadence logic moved to contact_cadence.py — was a
# byte-identical copy of contacts_store's version (the comment on
# that one literally said "Mirror of partner_contacts_store"). Kept
# as named re-exports so external code that imports them by name
# keeps working.
from contact_cadence import (
    parse_iso as _parse_iso,
    annotate_touch_state,
)


def touch_contact(partner_id: str, contact_id: str, *,
                   at: str | None = None) -> dict[str, Any] | None:
    """Bump last_touched_at to `at` (defaults to now). Returns updated
    contact or None if not found. Used by the note-add flow + any
    explicit "log a touch" action."""
    rows = _load_raw(partner_id)
    found = None
    when = at or _now()
    for r in rows:
        if r.get("id") == contact_id:
            r["last_touched_at"] = when
            r["updated_at"] = _now()
            found = r
            break
    if found is None:
        return None
    _write_raw(partner_id, rows)
    return found


def list_contacts(partner_id: str) -> list[dict[str, Any]]:
    """All contacts under this partner, sorted active-first then alpha.
    Each row is annotated with touch state (overdue, days_until_due,
    etc.) so the UI doesn't need a second computation."""
    rows = _load_raw(partner_id)
    rows.sort(key=lambda r: (
        r.get("status") != "active",
        (r.get("name") or "").lower(),
    ))
    for r in rows:
        annotate_touch_state(r)
    return rows


def overdue_contacts(partner_id: str | None = None) -> list[dict[str, Any]]:
    """Return active, overdue contacts. Pass partner_id to scope; omit
    for an across-all-partners roster (used by the Today / overview
    surface)."""
    if partner_id:
        contacts = list_contacts(partner_id)
    else:
        contacts = []
        for raw in list_all_contacts():
            annotate_touch_state(raw)
            contacts.append(raw)
    return [
        c for c in contacts
        if c.get("status") == "active" and c.get("overdue")
    ]


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
