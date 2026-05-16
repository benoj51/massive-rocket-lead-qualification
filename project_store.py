"""
Lightweight JSON-file project store.

Stores one file per lead at cache/projects/<lead_id>.json. Good enough for
v0.4 — single-writer, low volume. Migrate to Postgres when we cross ~10k
projects or need concurrent edits.

lead_id is typically the company's slugified domain (e.g. "deliveroo_co_uk")
so listing projects = listing files.
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Iterable

import scope as scope_module

_DEFAULT_DIR = Path(__file__).parent / "cache" / "projects"
_LOCK = threading.Lock()


def _store_dir() -> Path:
    override = os.environ.get("PROJECT_STORE_DIR")
    d = Path(override) if override else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def slugify(value: str) -> str:
    """Lead IDs are filesystem-safe slugs. Stable across runs."""
    s = value.lower()
    s = re.sub(r"https?://", "", s)
    s = s.replace("www.", "")
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "unknown"


def _path_for(lead_id: str) -> Path:
    return _store_dir() / f"{slugify(lead_id)}.json"


def save(scope: scope_module.ProjectScope) -> None:
    payload = scope_module.to_dict(scope)
    path = _path_for(scope.lead_id)
    with _LOCK:
        path.write_text(json.dumps(payload, indent=2))


def load(lead_id: str) -> scope_module.ProjectScope | None:
    path = _path_for(lead_id)
    if not path.exists():
        return None
    try:
        with _LOCK:
            data = json.loads(path.read_text())
        return scope_module.from_dict(data)
    except (json.JSONDecodeError, OSError, KeyError):
        return None


def delete(lead_id: str) -> bool:
    path = _path_for(lead_id)
    if not path.exists():
        return False
    try:
        with _LOCK:
            path.unlink()
        return True
    except OSError:
        return False


def list_all() -> list[scope_module.ProjectScope]:
    out: list[scope_module.ProjectScope] = []
    d = _store_dir()
    for p in sorted(d.glob("*.json")):
        try:
            with _LOCK:
                data = json.loads(p.read_text())
            out.append(scope_module.from_dict(data))
        except (json.JSONDecodeError, OSError, KeyError):
            continue
    return out


def list_summaries() -> list[dict]:
    return [scope_module.project_summary(s) for s in list_all()]


def list_pending_validation() -> list[dict]:
    return [scope_module.project_summary(s) for s in list_all()
            if s.validation_status == "pending_validation"]
