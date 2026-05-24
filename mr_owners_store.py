"""v1.0.0bq — writable MR owners store.

Originally (v1.0.0o) the MR owners list was a hard-coded Python
constant in `mr_owners.py`. That worked while the roster was stable,
but adding/removing/renaming a teammate meant a code change + Railway
deploy — too slow when someone joins or moves teams.

This module persists owners as a single JSON file
(`cache/mr_owners/owners.json`) and exposes CRUD that the Settings
UI calls. `mr_owners.py` now delegates its public API
(`list_owners` / `get_owner` / `names`) here, so every caller
(notifications, owner dropdowns, scoring) transparently sees the
live edits.

Seed
----
On first read (no file yet), the store seeds itself from the
`SEED_OWNERS` list — the same 12 names the old hard-coded module
had — so an upgrade from v1.0.0bp to v1.0.0bq is invisible to
existing users. Subsequent edits are appended to the JSON only;
the seed list is never re-read.

Shape
-----
    {
      "id":     "<uuid8>",     # stable id even across renames
      "name":   "Thierry Sequeira",
      "role":   "CEO UK",
      "region": "Global",
      "email":  "thierry@massiverocket.com",
      "active": True,
      "created_at": iso,
      "updated_at": iso,
    }

API
---
    list_owners(*, active_only=True) -> list[dict]   # sorted by display order
    get_owner(name_or_id) -> dict | None             # case-insensitive name OR id
    create_owner(payload) -> dict
    update_owner(owner_id, **fields) -> dict | None
    delete_owner(owner_id) -> bool                   # hard delete; prefer deactivate
    deactivate_owner(owner_id) -> dict | None
    activate_owner(owner_id) -> dict | None
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DIR = Path(__file__).parent / "cache" / "mr_owners"
_FILE_NAME = "owners.json"
_LOCK = threading.Lock()

_ALLOWED_UPDATE = {"name", "role", "region", "email", "active"}


# Seed list — mirrors the v1.0.0o hard-coded OWNERS so the first-run
# experience is unchanged. New installs and existing upgrades both
# land here.
SEED_OWNERS: list[dict[str, Any]] = [
    {"name": "Thierry Sequeira", "role": "CEO UK",
     "region": "Global", "email": "thierry@massiverocket.com"},
    {"name": "Daniel Craig", "role": "Director of Growth",
     "region": "Global", "email": "daniel.craig@massiverocket.com"},
    {"name": "Ben Ojuolape",
     "role": "Growth Lead (Partnerships + GTM)", "region": "UK → US",
     "email": "ben@massiverocket.com"},
    {"name": "Daniel Ergueta", "role": "Account Manager",
     "region": "AMER", "email": "daniel.ergueta@massiverocket.com"},
    {"name": "Tsveti Grncarova", "role": "Account Manager",
     "region": "EMEA", "email": "tsvetelina.rancheva@massiverocket.com"},
    {"name": "Jorge Arrechea",
     "role": "AMER AM, transitioning to AE", "region": "AMER",
     "email": "jorge.arrechea@massiverocket.com"},
    {"name": "Marija Veljanova",
     "role": "AMER AM, transitioning to AE", "region": "EMEA",
     "email": "marija.veljanova@massiverocket.com"},
    {"name": "Darren Addy",
     "role": "EMEA AM, transitioning to AE", "region": "EMEA",
     "email": "darren.addy@massiverocket.com"},
    {"name": "Claudia Lima", "role": "Partner Manager, AMER",
     "region": "AMER", "email": "claudia.lima@massiverocket.com"},
    {"name": "Sonal Dalia", "role": "Partner Manager",
     "region": "EMEA", "email": ""},
    {"name": "Jamie MacDow",
     "role": "Marketing — co-owns New Accounts OKR",
     "region": "Global", "email": "jamie.macdow@massiverocket.com"},
    {"name": "Lea", "role": "Marketing",
     "region": "Global", "email": "lea@massiverocket.com"},
]


class MrOwnersStoreError(RuntimeError):
    pass


def _store_dir() -> Path:
    override = os.environ.get("MR_OWNERS_STORE_DIR")
    d = Path(override) if override else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path() -> Path:
    return _store_dir() / _FILE_NAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalise(o: dict[str, Any], *, position: int = 0) -> dict[str, Any]:
    out = dict(o)
    out.setdefault("id", uuid.uuid4().hex[:10])
    out["name"] = str(out.get("name") or "").strip()
    out["role"] = str(out.get("role") or "").strip()
    out["region"] = str(out.get("region") or "").strip()
    out["email"] = str(out.get("email") or "").strip()
    out["active"] = bool(out.get("active", True))
    out.setdefault("created_at", _now())
    out.setdefault("updated_at", out["created_at"])
    # `order` preserves the original display ordering. Stored once,
    # not modified by edits — that way reorderings are explicit, not
    # incidental.
    if "order" not in out:
        out["order"] = position
    return out


def _load_all() -> list[dict[str, Any]]:
    """Read the file. On first run (no file yet), seed from
    SEED_OWNERS and persist immediately so the seed is captured
    rather than re-evaluated on every read."""
    p = _path()
    if not p.exists():
        seeded = [_normalise({**o, "active": True}, position=i)
                  for i, o in enumerate(SEED_OWNERS)]
        _write_all(seeded)
        return seeded
    try:
        data = json.loads(p.read_text())
        if not isinstance(data, list):
            return []
        return [_normalise(o, position=i) for i, o in enumerate(data)]
    except (OSError, ValueError):
        return []


def _write_all(owners: list[dict[str, Any]]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(owners, indent=2, ensure_ascii=False))


# ---- public API ----------------------------------------------------------

def list_owners(*, active_only: bool = True) -> list[dict[str, Any]]:
    """Return owners in their stored display order."""
    with _LOCK:
        owners = _load_all()
    owners.sort(key=lambda o: o.get("order", 9999))
    if active_only:
        owners = [o for o in owners if o.get("active", True)]
    return owners


def names(*, active_only: bool = True) -> list[str]:
    return [o["name"] for o in list_owners(active_only=active_only)]


def get_owner(name_or_id: str) -> dict[str, Any] | None:
    """Lookup by stable id OR by name (case-insensitive). Name lookup
    keeps backward-compat with code that resolves a lead.owner string
    back to its email/role."""
    if not name_or_id:
        return None
    needle = name_or_id.strip().lower()
    if not needle:
        return None
    with _LOCK:
        owners = _load_all()
    for o in owners:
        if o.get("id", "").lower() == needle:
            return o
        if o.get("name", "").lower() == needle:
            return o
    return None


def create_owner(payload: dict[str, Any]) -> dict[str, Any]:
    name = (payload.get("name") or "").strip()
    if not name:
        raise MrOwnersStoreError("name required")
    with _LOCK:
        owners = _load_all()
        # Reject duplicate names (case-insensitive). Prevents two
        # "Daniel Ergueta" rows that would confuse the owner-dropdown
        # consumers downstream.
        if any(o.get("name", "").lower() == name.lower() for o in owners):
            raise MrOwnersStoreError(f"owner named {name!r} already exists")
        new_order = (max((o.get("order", 0) for o in owners), default=-1) + 1)
        owner = _normalise({**payload, "name": name,
                            "order": new_order, "active": True})
        owners.append(owner)
        _write_all(owners)
    return owner


def update_owner(owner_id: str, **fields: Any) -> dict[str, Any] | None:
    bad = set(fields) - _ALLOWED_UPDATE
    if bad:
        raise MrOwnersStoreError(
            f"unknown fields: {sorted(bad)}. Allowed: {sorted(_ALLOWED_UPDATE)}")
    if not owner_id:
        return None
    with _LOCK:
        owners = _load_all()
        for i, o in enumerate(owners):
            if o.get("id") == owner_id:
                if "name" in fields:
                    new_name = (fields["name"] or "").strip()
                    if not new_name:
                        raise MrOwnersStoreError("name cannot be empty")
                    # Duplicate-check against other rows.
                    for other in owners:
                        if (other.get("id") != owner_id
                                and other.get("name", "").lower() == new_name.lower()):
                            raise MrOwnersStoreError(
                                f"owner named {new_name!r} already exists")
                    o["name"] = new_name
                for key in ("role", "region", "email"):
                    if key in fields:
                        o[key] = (fields[key] or "").strip()
                if "active" in fields:
                    o["active"] = bool(fields["active"])
                o["updated_at"] = _now()
                owners[i] = o
                _write_all(owners)
                return o
    return None


def delete_owner(owner_id: str) -> bool:
    """Hard delete. Prefer `deactivate_owner` so historical
    lead.owner = "Old Name" rows still resolve back to an email/role."""
    if not owner_id:
        return False
    with _LOCK:
        owners = _load_all()
        new = [o for o in owners if o.get("id") != owner_id]
        if len(new) == len(owners):
            return False
        _write_all(new)
    return True


def deactivate_owner(owner_id: str) -> dict[str, Any] | None:
    return update_owner(owner_id, active=False)


def activate_owner(owner_id: str) -> dict[str, Any] | None:
    return update_owner(owner_id, active=True)
