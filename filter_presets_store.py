"""v1.0.0ay — Saved filter presets per user.

The partner contacts table has 8 filter dimensions (territory, region,
country, industry, status, sentiment, tier, seniority, +my-contacts).
Repeated combos ("My Champions in QSR", "Strategic AEs in EU") get
typed again and again. This store lets a user save a named preset
once and recall it with one click.

Design
------
- One JSON file per user slug (slugified MR-owner display name).
- Each preset carries an opaque `filters` payload — the UI defines
  the shape, the store treats it as a black box. Today's payload is
  the partner-contacts filter dict, but the same store can power
  pipeline-filter presets tomorrow via the `scope` field.
- Names must be unique per (user, scope). Duplicate save → 400-style
  error from the caller's perspective (PresetExists). Updates are
  by id, not name.

Shape
-----
    {
      "id":         "<uuid4>",
      "user":       "Ben Ojuolape",
      "user_slug":  "ben-ojuolape",
      "scope":      "partner_contacts",  # which surface this applies to
      "name":       "My Champions in QSR",
      "filters":    {...arbitrary payload...},
      "created_at": "2026-05-23T19:45:00Z",
      "updated_at": "2026-05-23T19:45:00Z",
    }

API
---
    list_for(user, *, scope=None) -> list[dict]
    create(user, name, filters, *, scope="partner_contacts") -> dict
    update(user, preset_id, **fields) -> dict | None
    delete(user, preset_id) -> bool
    get(user, preset_id) -> dict | None
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DIR = Path(__file__).parent / "cache" / "filter_presets"
_LOCK = threading.Lock()
_MAX_PRESETS_PER_USER = 50  # generous cap; the UI gets unusable past this


class FilterPresetsStoreError(RuntimeError):
    pass


class PresetExists(FilterPresetsStoreError):
    """Raised when a create() would collide with an existing
    (user, scope, name) triple."""


def _store_dir() -> Path:
    override = os.environ.get("FILTER_PRESETS_STORE_DIR")
    d = Path(override) if override else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slugify(value: str) -> str:
    if not value:
        return "unknown"
    s = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return s.strip("-") or "unknown"


def _path(user: str) -> Path:
    return _store_dir() / f"{_slugify(user)}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_raw(user: str) -> list[dict[str, Any]]:
    p = _path(user)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
        if not isinstance(data, list):
            return []
        return data
    except (OSError, ValueError):
        return []


def _save_raw(user: str, rows: list[dict[str, Any]]) -> None:
    p = _path(user)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows, indent=2, ensure_ascii=False))


def _normalise(p: dict[str, Any]) -> dict[str, Any]:
    out = dict(p)
    out.setdefault("id", uuid.uuid4().hex)
    out.setdefault("scope", "partner_contacts")
    out.setdefault("name", "(unnamed)")
    out.setdefault("filters", {})
    out.setdefault("created_at", _now())
    out.setdefault("updated_at", out["created_at"])
    out.setdefault("user", out.get("user") or "Unknown")
    out.setdefault("user_slug", _slugify(out["user"]))
    return out


# ---- core API -------------------------------------------------------------

def list_for(user: str, *, scope: str | None = None) -> list[dict[str, Any]]:
    """Return all presets for `user`, optionally filtered to one
    surface. Sorted by name ASC so the picker dropdown is stable."""
    if not user:
        return []
    with _LOCK:
        rows = [_normalise(r) for r in _load_raw(user)]
    if scope:
        rows = [r for r in rows if r.get("scope") == scope]
    rows.sort(key=lambda r: (r.get("name") or "").lower())
    return rows


def get(user: str, preset_id: str) -> dict[str, Any] | None:
    if not (user and preset_id):
        return None
    with _LOCK:
        for r in _load_raw(user):
            if r.get("id") == preset_id:
                return _normalise(r)
    return None


def create(user: str, name: str, filters: dict[str, Any], *,
            scope: str = "partner_contacts") -> dict[str, Any]:
    """Create a new preset. Raises PresetExists if (user, scope, name)
    is already taken — name uniqueness within scope is enforced so the
    picker dropdown can be keyed by name without ambiguity."""
    if not (user or "").strip():
        raise FilterPresetsStoreError("user required")
    name = (name or "").strip()
    if not name:
        raise FilterPresetsStoreError("name required")
    if len(name) > 80:
        raise FilterPresetsStoreError("name too long (max 80 chars)")
    if not isinstance(filters, dict):
        raise FilterPresetsStoreError("filters must be an object")
    with _LOCK:
        rows = _load_raw(user)
        # Uniqueness check inside the same scope.
        name_lower = name.lower()
        for r in rows:
            if (r.get("scope") == scope and
                (r.get("name") or "").strip().lower() == name_lower):
                raise PresetExists(
                    f"A preset named {name!r} already exists in this scope")
        if len(rows) >= _MAX_PRESETS_PER_USER:
            raise FilterPresetsStoreError(
                f"Cap reached ({_MAX_PRESETS_PER_USER} presets per user). "
                f"Delete some before adding more.")
        preset = _normalise({
            "id":         uuid.uuid4().hex,
            "user":       user.strip(),
            "scope":      scope,
            "name":       name,
            "filters":    filters,
            "created_at": _now(),
            "updated_at": _now(),
        })
        rows.append(preset)
        _save_raw(user, rows)
        return preset


def update(user: str, preset_id: str, **fields: Any) -> dict[str, Any] | None:
    """Patch fields on a preset. Allowed: name, filters. Updating
    `name` to one that collides with another preset in the same scope
    raises PresetExists."""
    if not (user and preset_id):
        return None
    allowed = {"name", "filters"}
    bad = set(fields) - allowed
    if bad:
        raise FilterPresetsStoreError(f"unknown fields: {sorted(bad)}")
    with _LOCK:
        rows = _load_raw(user)
        target = None
        for r in rows:
            if r.get("id") == preset_id:
                target = r
                break
        if target is None:
            return None
        if "name" in fields:
            new_name = (fields["name"] or "").strip()
            if not new_name:
                raise FilterPresetsStoreError("name cannot be empty")
            if len(new_name) > 80:
                raise FilterPresetsStoreError("name too long (max 80 chars)")
            # Uniqueness check (skip self).
            scope = target.get("scope", "partner_contacts")
            name_lower = new_name.lower()
            for r in rows:
                if r.get("id") == preset_id:
                    continue
                if (r.get("scope") == scope and
                    (r.get("name") or "").strip().lower() == name_lower):
                    raise PresetExists(
                        f"A preset named {new_name!r} already exists in this scope")
            target["name"] = new_name
        if "filters" in fields:
            if not isinstance(fields["filters"], dict):
                raise FilterPresetsStoreError("filters must be an object")
            target["filters"] = fields["filters"]
        target["updated_at"] = _now()
        _save_raw(user, rows)
        return _normalise(target)


def delete(user: str, preset_id: str) -> bool:
    if not (user and preset_id):
        return False
    with _LOCK:
        rows = _load_raw(user)
        new = [r for r in rows if r.get("id") != preset_id]
        if len(new) == len(rows):
            return False
        _save_raw(user, new)
    return True
