"""v1.0.0bk — Live Projects store.

A "live project" is an account that has moved past the sales pipeline
into delivery / account management. It carries:
- the link back to the source lead (so contacts / agencies / tech
  stack stay shared — no double-entry)
- a status (active | paused | completed | archived)
- an owner (MR project lead)
- start/end dates
- a free-form summary the project lead maintains

OKRs live in a sibling store (live_project_okrs_store) and reference
this project's id.

The relationship with `project_store.ProjectScope` (scope.py)
-----------------------------------------------------------
ProjectScope is the SCOPING artefact — pre-sale criteria checking,
SOW build, pricing. A LiveProject is the POST-sale delivery
artefact. A lead can have a scope (filled during sales) AND, once
won, a live project (filled during delivery). Two different
lifecycles, two different stores.

Shape
-----
    {
      "id":         "<uuid4>",
      "lead_id":    "page-abc",        # links back to Notion lead
      "name":       "Shell Loyalty Build",
      "status":     "active",          # active | paused | completed | archived
      "owner":      "Ben Ojuolape",    # MR project lead (display name)
      "started_at": "2026-04-01",      # YYYY-MM-DD
      "ended_at":   None,              # set when completed/archived
      "summary":    "Loyalty rebuild Phase 1 + CRM execute…",
      "tags":       ["loyalty", "braze"],
      "created_at": "2026-05-24T09:00:00Z",
      "updated_at": "2026-05-24T09:00:00Z",
    }

API
---
    list_all(*, status=None) -> list[dict]
    get(project_id) -> dict | None
    get_by_lead(lead_id) -> dict | None     # at most one live project per lead
    create(lead_id, name, *, owner=None, started_at=None,
            summary=None, tags=None) -> dict
    update(project_id, **fields) -> dict | None
    set_status(project_id, status) -> dict | None
    delete(project_id) -> bool             # hard delete; archive is preferred
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

_DEFAULT_DIR = Path(__file__).parent / "cache" / "live_projects"
_LOCK = threading.Lock()

STATUSES = ("active", "paused", "completed", "archived")
_ALLOWED_UPDATE = {"name", "owner", "started_at", "ended_at",
                    "summary", "tags", "status"}


class LiveProjectsStoreError(RuntimeError):
    pass


def _store_dir() -> Path:
    override = os.environ.get("LIVE_PROJECTS_STORE_DIR")
    d = Path(override) if override else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _safe_id(value: str) -> str:
    """v1.0.0bz: strict ID guard — same pattern as expansion_targets_store.
    See that file's _safe_id docstring for rationale."""
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise LiveProjectsStoreError(f"invalid id: {value!r}")
    return value


def _path(project_id: str) -> Path:
    return _store_dir() / f"{_safe_id(project_id)}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_raw(project_id: str) -> dict[str, Any] | None:
    p = _path(project_id)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        if not isinstance(data, dict):
            return None
        return data
    except (OSError, ValueError):
        return None


def _save_raw(project: dict[str, Any]) -> None:
    pid = project["id"]
    p = _path(pid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(project, indent=2, ensure_ascii=False))


def _normalise(p: dict[str, Any]) -> dict[str, Any]:
    out = dict(p)
    out.setdefault("id", uuid.uuid4().hex)
    out.setdefault("lead_id", "")
    out.setdefault("name", "")
    out.setdefault("status", "active")
    out.setdefault("owner", None)
    out.setdefault("started_at", None)
    out.setdefault("ended_at", None)
    out.setdefault("summary", None)
    out.setdefault("tags", [])
    out.setdefault("created_at", _now())
    out.setdefault("updated_at", out["created_at"])
    return out


def _validate_status(s: Any) -> str:
    if not isinstance(s, str) or s not in STATUSES:
        raise LiveProjectsStoreError(
            f"status must be one of {STATUSES}; got {s!r}")
    return s


def _validate_date(d: Any) -> str | None:
    """YYYY-MM-DD or None. Empty string → None."""
    if d in (None, ""):
        return None
    if not isinstance(d, str):
        raise LiveProjectsStoreError(
            f"date must be YYYY-MM-DD string or None; got {type(d).__name__}")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
        raise LiveProjectsStoreError(
            f"date must be YYYY-MM-DD; got {d!r}")
    return d


# ---- core API -------------------------------------------------------------

def list_all(*, status: str | None = None) -> list[dict[str, Any]]:
    """All live projects. Optional `status` filter. Sorted by
    started_at descending (most recent active first), then by
    updated_at descending."""
    d = _store_dir()
    if not d.exists():
        return []
    out: list[dict[str, Any]] = []
    with _LOCK:
        for f in d.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                if not isinstance(data, dict):
                    continue
                out.append(_normalise(data))
            except (OSError, ValueError):
                continue
    if status:
        out = [p for p in out if p.get("status") == status]
    out.sort(key=lambda p: (
        p.get("started_at") or "",
        p.get("updated_at") or "",
    ), reverse=True)
    return out


def get(project_id: str) -> dict[str, Any] | None:
    if not project_id:
        return None
    with _LOCK:
        raw = _load_raw(project_id)
    return _normalise(raw) if raw else None


def get_by_lead(lead_id: str) -> dict[str, Any] | None:
    """At most one live project per lead. Returns the first match
    (there shouldn't be more than one — create() enforces)."""
    if not lead_id:
        return None
    for p in list_all():
        if p.get("lead_id") == lead_id:
            return p
    return None


def create(lead_id: str, name: str, *,
            owner: str | None = None,
            started_at: str | None = None,
            summary: str | None = None,
            tags: list[str] | None = None) -> dict[str, Any]:
    """Create a new live project. Raises if `lead_id` already has one
    (a lead has at most one live project — additional engagements
    on the same account should be separate leads)."""
    if not (lead_id or "").strip():
        raise LiveProjectsStoreError("lead_id required")
    if not (name or "").strip():
        raise LiveProjectsStoreError("name required")
    if get_by_lead(lead_id):
        raise LiveProjectsStoreError(
            f"Lead {lead_id!r} already has a live project. "
            f"Update or archive the existing one first.")
    started_iso = _validate_date(started_at) or _now()[:10]
    project = _normalise({
        "id":         uuid.uuid4().hex,
        "lead_id":    lead_id.strip(),
        "name":       name.strip()[:200],
        "status":     "active",
        "owner":      (owner or "").strip() or None,
        "started_at": started_iso,
        "ended_at":   None,
        "summary":    (summary or "").strip() or None,
        "tags":       list(tags or []),
        "created_at": _now(),
        "updated_at": _now(),
    })
    with _LOCK:
        _save_raw(project)
    return project


def update(project_id: str, **fields: Any) -> dict[str, Any] | None:
    if not project_id:
        return None
    bad = set(fields) - _ALLOWED_UPDATE
    if bad:
        raise LiveProjectsStoreError(
            f"unknown fields: {sorted(bad)}. Allowed: {sorted(_ALLOWED_UPDATE)}")
    with _LOCK:
        raw = _load_raw(project_id)
        if raw is None:
            return None
        # Field-level validation.
        if "status" in fields:
            raw["status"] = _validate_status(fields["status"])
            # Auto-set ended_at when moving to completed/archived
            # (only if caller didn't supply one).
            if raw["status"] in ("completed", "archived") and not raw.get("ended_at"):
                raw["ended_at"] = _now()[:10]
            # Clear ended_at when moving back to active/paused.
            if raw["status"] in ("active", "paused"):
                raw["ended_at"] = None
        if "started_at" in fields:
            raw["started_at"] = _validate_date(fields["started_at"]) or raw.get("started_at")
        if "ended_at" in fields:
            raw["ended_at"] = _validate_date(fields["ended_at"])
        if "name" in fields:
            name = (fields["name"] or "").strip()
            if not name:
                raise LiveProjectsStoreError("name cannot be empty")
            raw["name"] = name[:200]
        if "owner" in fields:
            raw["owner"] = (fields["owner"] or "").strip() or None
        if "summary" in fields:
            raw["summary"] = (fields["summary"] or "").strip() or None
        if "tags" in fields:
            tags = fields["tags"]
            if not isinstance(tags, list):
                raise LiveProjectsStoreError("tags must be a list")
            raw["tags"] = [str(t).strip() for t in tags if str(t).strip()]
        raw["updated_at"] = _now()
        _save_raw(raw)
        return _normalise(raw)


def set_status(project_id: str, status: str) -> dict[str, Any] | None:
    """Convenience wrapper used by the API status-transition endpoint."""
    return update(project_id, status=status)


def delete(project_id: str) -> bool:
    if not project_id:
        return False
    with _LOCK:
        p = _path(project_id)
        if not p.exists():
            return False
        p.unlink()
    return True
