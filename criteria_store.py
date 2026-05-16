"""
Editable criteria library.

Replaces the hardcoded CRITERIA_LIBRARY in scope.py with a JSON-backed store
the team can edit at runtime through the platform UI. On first read with no
file present, seeds from scope.DEFAULT_CRITERIA_LIBRARY (the original
hardcoded values from v0.4.0), so deployments remain self-bootstrapping.

Storage: cache/scope_criteria.json
Override: CRITERIA_STORE_PATH env var (used by tests).

Public surface:
    load()                          -> {project_type: [criteria]} full library
    save(library)                   -> persist a full library
    upsert_criterion(pt, criterion) -> add or replace one criterion
    delete_criterion(pt, key)       -> remove one criterion
    reset_project_type(pt)          -> restore defaults for one stream
    reset_all()                     -> restore defaults for every stream

Each criterion dict has these keys:
    key            : stable id (unique within a project type)
    label          : prompt the AE sees
    hint           : optional clarifier
    role_driver    : which pricing role this scales (or None)
    scale_factor   : float, how strongly value scales effort (0 = no driver)
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path(__file__).parent / "cache" / "scope_criteria.json"
_LOCK = threading.Lock()

REQUIRED_KEYS = {"key", "label"}
OPTIONAL_KEYS = {"hint", "role_driver", "scale_factor"}


class CriteriaStoreError(RuntimeError):
    pass


def _path() -> Path:
    override = os.environ.get("CRITERIA_STORE_PATH")
    p = Path(override) if override else _DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _defaults() -> dict[str, list[dict[str, Any]]]:
    # Lazy import to avoid circular dependency at module import time.
    import scope
    # Snapshot of the v0.4.0 hardcoded values — preserved as DEFAULT_CRITERIA_LIBRARY
    # in scope.py so resets work even after edits.
    return {pt: list(criteria) for pt, criteria in scope.DEFAULT_CRITERIA_LIBRARY.items()}


def _validate_criterion(c: dict[str, Any]) -> dict[str, Any]:
    missing = REQUIRED_KEYS - set(c.keys())
    if missing:
        raise CriteriaStoreError(f"Criterion missing keys: {missing}")
    # Drop unknown keys, coerce types.
    clean = {
        "key": str(c["key"]).strip(),
        "label": str(c["label"]).strip(),
        "hint": str(c.get("hint") or "").strip(),
        "role_driver": (c.get("role_driver") or None) or None,
        "scale_factor": float(c.get("scale_factor") or 0.0),
    }
    if not clean["key"]:
        raise CriteriaStoreError("Criterion key cannot be empty")
    if not clean["label"]:
        raise CriteriaStoreError("Criterion label cannot be empty")
    return clean


def load() -> dict[str, list[dict[str, Any]]]:
    """Return the full library. Seeds defaults on first call."""
    path = _path()
    if not path.exists():
        defaults = _defaults()
        save(defaults)
        return defaults
    try:
        with _LOCK:
            data = json.loads(path.read_text())
        return data
    except (json.JSONDecodeError, OSError):
        # Corrupt file → fall back to defaults but don't overwrite the corrupt
        # file automatically (preserves evidence for debugging).
        return _defaults()


def save(library: dict[str, list[dict[str, Any]]]) -> None:
    """Persist the whole library. Validates each criterion."""
    cleaned: dict[str, list[dict[str, Any]]] = {}
    for pt, criteria in library.items():
        cleaned_list: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for c in (criteria or []):
            c = _validate_criterion(c)
            if c["key"] in seen_keys:
                raise CriteriaStoreError(
                    f"Duplicate criterion key {c['key']!r} in project type {pt!r}"
                )
            seen_keys.add(c["key"])
            cleaned_list.append(c)
        cleaned[pt] = cleaned_list
    path = _path()
    with _LOCK:
        path.write_text(json.dumps(cleaned, indent=2))


def upsert_criterion(project_type: str, criterion: dict[str, Any]) -> dict[str, Any]:
    """Add or replace a criterion within a project type. Returns the saved entry."""
    library = load()
    if project_type not in library:
        library[project_type] = []
    clean = _validate_criterion(criterion)
    found = False
    for i, c in enumerate(library[project_type]):
        if c["key"] == clean["key"]:
            library[project_type][i] = clean
            found = True
            break
    if not found:
        library[project_type].append(clean)
    save(library)
    return clean


def delete_criterion(project_type: str, key: str) -> bool:
    library = load()
    if project_type not in library:
        return False
    before = len(library[project_type])
    library[project_type] = [c for c in library[project_type] if c["key"] != key]
    if len(library[project_type]) == before:
        return False
    save(library)
    return True


def reorder(project_type: str, keys: list[str]) -> None:
    """Reorder criteria for a project type. Missing keys are appended in their
    existing order; unknown keys raise."""
    library = load()
    current = {c["key"]: c for c in library.get(project_type, [])}
    unknown = [k for k in keys if k not in current]
    if unknown:
        raise CriteriaStoreError(f"Unknown criterion keys: {unknown}")
    ordered = [current[k] for k in keys]
    remaining = [c for k, c in current.items() if k not in keys]
    library[project_type] = ordered + remaining
    save(library)


def reset_project_type(project_type: str) -> list[dict[str, Any]]:
    """Restore defaults for one stream. Returns the restored list."""
    defaults = _defaults()
    if project_type not in defaults:
        raise CriteriaStoreError(f"Unknown project type {project_type!r}")
    library = load()
    library[project_type] = list(defaults[project_type])
    save(library)
    return library[project_type]


def reset_all() -> dict[str, list[dict[str, Any]]]:
    defaults = _defaults()
    save(defaults)
    return defaults
