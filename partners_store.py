"""
Partner registry (v0.10.0y).

A partner is an org Massive Rocket works WITH — Braze, Snowflake, mParticle,
Hightouch, etc. Distinct from `leads` (orgs we sell TO). Each partner has
its own list of contacts (in `partner_contacts_store`) and notes.

Storage: one JSON file at cache/partners/index.json with the full list.
Single-file because partners are small (~tens), low write rate, and we
often need the whole list for the UI (filters, pickers, etc.).

Public API:
    list_partners()                    -> [partner_dict]
    get_partner(partner_id)            -> partner_dict | None
    save_partner(payload)              -> persisted partner (id assigned if absent)
    delete_partner(partner_id)         -> bool (False if not found)
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path(__file__).parent / "cache" / "partners" / "index.json"
_LOCK = threading.Lock()


# Enumerations the UI relies on. Keep these in sync with qualify.html
# (rendered dropdown options). Free-text country lives elsewhere.
PARTNER_TYPES = ["Technology partner", "Sourcing partner", "Reseller",
                 "Agency partner", "Other"]


class PartnersStoreError(RuntimeError):
    pass


def _path() -> Path:
    override = os.environ.get("PARTNERS_STORE_PATH")
    p = Path(override) if override else _DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _now() -> str:
    # v1.0.0cg: aligned with the rest of the system (second precision).
    # The original microsecond version was added so a "saves bump
    # updated_at" test could pass without a 1s sleep — but that drift
    # meant partner `updated_at` values were inconsistent with every
    # other store's. The test now sleeps 1.1s; the consistency wins.
    return datetime.now(timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def _slugify(value: str) -> str:
    import project_store
    return project_store.slugify(value)


def _load_raw() -> list[dict[str, Any]]:
    p = _path()
    if not p.exists():
        return []
    try:
        with _LOCK:
            return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _write_raw(rows: list[dict[str, Any]]) -> None:
    with _LOCK:
        _path().write_text(json.dumps(rows, indent=2))


def _normalise(p: dict[str, Any]) -> dict[str, Any]:
    name = (p.get("name") or "").strip()
    if not name:
        raise PartnersStoreError("Partner requires a name")
    pid = (p.get("id") or "").strip() or _slugify(name)
    return {
        "id": pid,
        "name": name,
        "type": (p.get("type") or "Technology partner").strip(),
        "url": (p.get("url") or "").strip() or None,
        "logo_url": (p.get("logo_url") or "").strip() or None,
        "description": (p.get("description") or "").strip() or None,
        "owner": (p.get("owner") or "").strip() or None,
        "status": (p.get("status") or "active").strip() or "active",
        "created_at": p.get("created_at") or _now(),
        "updated_at": _now(),
    }


def list_partners() -> list[dict[str, Any]]:
    """Return all partners, sorted by name (case-insensitive)."""
    rows = _load_raw()
    rows.sort(key=lambda r: (r.get("name") or "").lower())
    return rows


def get_partner(partner_id: str) -> dict[str, Any] | None:
    """Return the partner record or None."""
    pid = _slugify(partner_id)
    for r in _load_raw():
        if r.get("id") == pid:
            return r
    return None


def save_partner(payload: dict[str, Any]) -> dict[str, Any]:
    """Add or update a partner by id (matched after slugify)."""
    clean = _normalise(payload)
    rows = _load_raw()
    for i, r in enumerate(rows):
        if r.get("id") == clean["id"]:
            # Preserve created_at on update.
            clean["created_at"] = r.get("created_at") or clean["created_at"]
            rows[i] = clean
            _write_raw(rows)
            return clean
    rows.append(clean)
    _write_raw(rows)
    return clean


def delete_partner(partner_id: str) -> bool:
    """Remove the partner. Doesn't touch the partner's contacts / notes —
    those stores have their own per-partner files; caller decides whether
    to cascade-delete."""
    pid = _slugify(partner_id)
    rows = _load_raw()
    new_rows = [r for r in rows if r.get("id") != pid]
    if len(new_rows) == len(rows):
        return False
    _write_raw(new_rows)
    return True
