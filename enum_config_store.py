"""
Editable enum configuration (v1.0.0ac).

The UI populates dropdowns + chip groups from a small set of "enum"
lists: industries, territories, regions, statuses, partner sentiments,
tiers, seniorities. Historically those lived as Python constants in
`partner_contacts_store`, which meant adding a new option (e.g. a new
vertical like Gaming) required a code change + deploy.

This module loads those lists from `cache/enum_config.json`, merging
user customisations over the in-code defaults. The Settings panel in
the UI PATCHes to a thin endpoint that writes here.

Defaults are sourced from the existing module so changing them in
code is still valid for the seed case — but the JSON file wins where
present, so the UI can add / remove / reorder without a redeploy.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import partner_contacts_store

_DEFAULT_PATH = Path(__file__).parent / "cache" / "enum_config.json"
_LOCK = threading.Lock()


# Which enum keys this store supports. Keep this list aligned with
# the constants on partner_contacts_store. Adding a new enum is a
# two-line change: append it here + add the constant in the store.
_ENUM_KEYS = {
    "industries":         "INDUSTRIES",
    "territories":        "TERRITORIES",
    "regions":            "REGIONS",
    "statuses":           "STATUSES",
    "partner_sentiments": "PARTNER_SENTIMENTS",
    "tiers":              "TIERS",
    "seniorities":        "SENIORITIES",
}


def _path() -> Path:
    override = os.environ.get("ENUM_CONFIG_PATH")
    p = Path(override) if override else _DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _defaults() -> dict[str, list[str]]:
    """Pull the in-code defaults from partner_contacts_store. Read every
    time so module reloads in tests don't snapshot stale values."""
    out: dict[str, list[str]] = {}
    for ui_key, const_name in _ENUM_KEYS.items():
        out[ui_key] = list(getattr(partner_contacts_store, const_name, []))
    return out


def load() -> dict[str, list[str]]:
    """Return the effective enum lists: user overrides where set,
    in-code defaults otherwise. Always returns every key with a list."""
    defaults = _defaults()
    p = _path()
    if not p.exists():
        return defaults
    try:
        with _LOCK:
            raw = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return defaults
    if not isinstance(raw, dict):
        return defaults
    out: dict[str, list[str]] = {}
    for key, default_list in defaults.items():
        v = raw.get(key)
        # User list wins if it's a list of strings; otherwise fall back.
        if isinstance(v, list) and all(isinstance(x, str) for x in v):
            cleaned = [s.strip() for s in v if s and s.strip()]
            # Dedupe while preserving order — sloppy paste in the settings
            # UI shouldn't break the dropdown.
            seen: set[str] = set()
            deduped: list[str] = []
            for s in cleaned:
                if s not in seen:
                    seen.add(s)
                    deduped.append(s)
            out[key] = deduped if deduped else default_list
        else:
            out[key] = default_list
    return out


def save(updates: dict[str, Any]) -> dict[str, list[str]]:
    """Merge a partial update over the current state. Only keys we
    recognise are persisted; unknown keys are ignored. Returns the
    full effective config after the merge."""
    current = load()
    for key, value in (updates or {}).items():
        if key not in _ENUM_KEYS:
            continue
        if not isinstance(value, list):
            continue
        cleaned = [str(s).strip() for s in value if str(s).strip()]
        seen: set[str] = set()
        deduped: list[str] = []
        for s in cleaned:
            if s not in seen:
                seen.add(s)
                deduped.append(s)
        # Empty list resets to default — handy "I broke it, give me
        # the defaults back" escape hatch.
        if not deduped:
            current[key] = list(_defaults()[key])
        else:
            current[key] = deduped
    payload = dict(current)
    payload["updated_at"] = _now_iso()
    with _LOCK:
        _path().write_text(json.dumps(payload, indent=2))
    # Strip metadata from the returned dict (only return enum lists).
    return {k: v for k, v in payload.items() if k in _ENUM_KEYS}


def reset_key(key: str) -> dict[str, list[str]]:
    """Reset a single enum key to its in-code default. Useful "undo my
    mess" path for the settings UI."""
    if key not in _ENUM_KEYS:
        raise ValueError(f"Unknown enum key: {key}")
    return save({key: list(_defaults()[key])})
