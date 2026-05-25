"""v1.0.0bk — Per-project quarterly OKRs.

Each live project (from live_projects_store) has zero-or-more OKRs.
An OKR is one Objective for a quarter, with measurable Key Results.

Shape
-----
    {
      "id":         "<uuid4>",
      "project_id": "<live project id>",
      "quarter":    "Q2 2026",        # display label; free-form
      "objective":  "Launch loyalty MVP across UK estate",
      "key_results": [
        {
          "id":          "<uuid4>",
          "description": "Roll out to 10% of stations",
          "metric":      "rollout_pct",  # optional short key
          "unit":        "%",            # optional display unit
          "target":      "10",
          "current":     "5",
          "status":      "on_track",  # on_track | at_risk | missed | done
          "notes":       None,
        }
      ],
      "created_at": "...",
      "updated_at": "...",
    }

API
---
    list_for_project(project_id) -> list[dict]    # newest-first by quarter
    get(okr_id) -> dict | None
    create(project_id, quarter, objective, *, key_results=None) -> dict
    update(okr_id, **fields) -> dict | None
    delete(okr_id) -> bool

    # Key result helpers (nested under their OKR but addressable):
    add_key_result(okr_id, payload) -> dict
    update_key_result(okr_id, kr_id, **fields) -> dict | None
    delete_key_result(okr_id, kr_id) -> bool

    # Roll-ups for the UI:
    summarise(okr) -> dict     # {total_krs, on_track, at_risk, missed, done,
                                  health_pct}
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

_DEFAULT_DIR = Path(__file__).parent / "cache" / "live_project_okrs"
_LOCK = threading.Lock()

KR_STATUSES = ("on_track", "at_risk", "missed", "done")
_ALLOWED_UPDATE = {"quarter", "objective", "key_results"}
_ALLOWED_KR_UPDATE = {"description", "metric", "unit", "target",
                       "current", "status", "notes"}


class LiveProjectOkrsStoreError(RuntimeError):
    pass


def _store_dir() -> Path:
    override = os.environ.get("LIVE_PROJECT_OKRS_STORE_DIR")
    d = Path(override) if override else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _safe_id(value: str) -> str:
    """v1.0.0bz: strict ID guard — same pattern as live_projects_store."""
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise LiveProjectOkrsStoreError(f"invalid id: {value!r}")
    return value


def _path(okr_id: str) -> Path:
    return _store_dir() / f"{_safe_id(okr_id)}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_raw(okr_id: str) -> dict[str, Any] | None:
    p = _path(okr_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def _save_raw(okr: dict[str, Any]) -> None:
    p = _path(okr["id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(okr, indent=2, ensure_ascii=False))


def _normalise_kr(kr: dict[str, Any]) -> dict[str, Any]:
    out = dict(kr)
    out.setdefault("id", uuid.uuid4().hex[:12])
    out.setdefault("description", "")
    out.setdefault("metric", None)
    out.setdefault("unit", None)
    out.setdefault("target", None)
    out.setdefault("current", None)
    out.setdefault("status", "on_track")
    out.setdefault("notes", None)
    return out


def _validate_kr(kr: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(kr, dict):
        raise LiveProjectOkrsStoreError("key_result must be an object")
    desc = (kr.get("description") or "").strip()
    if not desc:
        raise LiveProjectOkrsStoreError("key_result.description required")
    status = (kr.get("status") or "on_track").strip()
    if status not in KR_STATUSES:
        raise LiveProjectOkrsStoreError(
            f"key_result.status must be one of {KR_STATUSES}; got {status!r}")
    # target/current are free-form strings (could be "10%", "$5M",
    # "50 users", "Q2 launch"); coerce to str if scalar.
    target = kr.get("target")
    current = kr.get("current")
    out = {
        "id":          (kr.get("id") or uuid.uuid4().hex[:12]),
        "description": desc[:300],
        "metric":      ((kr.get("metric") or "").strip() or None),
        "unit":        ((kr.get("unit") or "").strip() or None),
        "target":      (str(target).strip() if target is not None else None),
        "current":     (str(current).strip() if current is not None else None),
        "status":      status,
        "notes":       ((kr.get("notes") or "").strip() or None),
    }
    return out


def _normalise(okr: dict[str, Any]) -> dict[str, Any]:
    out = dict(okr)
    out.setdefault("id", uuid.uuid4().hex)
    out.setdefault("project_id", "")
    out.setdefault("quarter", "")
    out.setdefault("objective", "")
    out.setdefault("key_results", [])
    out["key_results"] = [_normalise_kr(k) for k in out["key_results"]]
    out.setdefault("created_at", _now())
    out.setdefault("updated_at", out["created_at"])
    return out


# ---- core API -------------------------------------------------------------

def list_for_project(project_id: str) -> list[dict[str, Any]]:
    """All OKRs for a project. Sorted newest-quarter-first based on
    the lexical sort of quarter string (works for 'Q2 2026' style
    because we sort by year+quarter — see _quarter_sort_key)."""
    if not project_id:
        return []
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
                if data.get("project_id") != project_id:
                    continue
                out.append(_normalise(data))
            except (OSError, ValueError):
                continue
    out.sort(key=_quarter_sort_key, reverse=True)
    return out


def _quarter_sort_key(okr: dict[str, Any]) -> tuple:
    """Sort key that handles 'Q1 2026', 'Q2 2026', 'H1 2026' etc.
    Pulls a year (4-digit) and falls back to created_at."""
    q = okr.get("quarter") or ""
    import re as _re
    year_m = _re.search(r"\b(\d{4})\b", q)
    year = int(year_m.group(1)) if year_m else 0
    quarter_m = _re.search(r"Q(\d)", q)
    quarter = int(quarter_m.group(1)) if quarter_m else 0
    return (year, quarter, okr.get("created_at") or "")


def get(okr_id: str) -> dict[str, Any] | None:
    if not okr_id:
        return None
    raw = _load_raw(okr_id)
    return _normalise(raw) if raw else None


def create(project_id: str, quarter: str, objective: str, *,
            key_results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if not (project_id or "").strip():
        raise LiveProjectOkrsStoreError("project_id required")
    if not (quarter or "").strip():
        raise LiveProjectOkrsStoreError("quarter required")
    if not (objective or "").strip():
        raise LiveProjectOkrsStoreError("objective required")
    krs = [_validate_kr(k) for k in (key_results or [])]
    okr = _normalise({
        "id":          uuid.uuid4().hex,
        "project_id":  project_id.strip(),
        "quarter":     quarter.strip()[:40],
        "objective":   objective.strip()[:300],
        "key_results": krs,
        "created_at":  _now(),
        "updated_at":  _now(),
    })
    with _LOCK:
        _save_raw(okr)
    return okr


def update(okr_id: str, **fields: Any) -> dict[str, Any] | None:
    if not okr_id:
        return None
    bad = set(fields) - _ALLOWED_UPDATE
    if bad:
        raise LiveProjectOkrsStoreError(
            f"unknown fields: {sorted(bad)}. Allowed: {sorted(_ALLOWED_UPDATE)}")
    with _LOCK:
        raw = _load_raw(okr_id)
        if raw is None:
            return None
        if "quarter" in fields:
            q = (fields["quarter"] or "").strip()
            if not q:
                raise LiveProjectOkrsStoreError("quarter cannot be empty")
            raw["quarter"] = q[:40]
        if "objective" in fields:
            o = (fields["objective"] or "").strip()
            if not o:
                raise LiveProjectOkrsStoreError("objective cannot be empty")
            raw["objective"] = o[:300]
        if "key_results" in fields:
            krs = fields["key_results"]
            if not isinstance(krs, list):
                raise LiveProjectOkrsStoreError("key_results must be a list")
            raw["key_results"] = [_validate_kr(k) for k in krs]
        raw["updated_at"] = _now()
        _save_raw(raw)
        return _normalise(raw)


def delete(okr_id: str) -> bool:
    if not okr_id:
        return False
    with _LOCK:
        p = _path(okr_id)
        if not p.exists():
            return False
        p.unlink()
    return True


# ---- per-KR helpers ------------------------------------------------------
# Nested under their OKR but addressable individually so the UI can
# add/edit/remove without round-tripping the whole list.

def add_key_result(okr_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        raw = _load_raw(okr_id)
        if raw is None:
            raise LiveProjectOkrsStoreError(f"okr {okr_id!r} not found")
        kr = _validate_kr({**payload, "id": uuid.uuid4().hex[:12]})
        raw.setdefault("key_results", []).append(kr)
        raw["updated_at"] = _now()
        _save_raw(raw)
        return kr


def update_key_result(okr_id: str, kr_id: str, **fields: Any) -> dict[str, Any] | None:
    bad = set(fields) - _ALLOWED_KR_UPDATE
    if bad:
        raise LiveProjectOkrsStoreError(
            f"unknown KR fields: {sorted(bad)}")
    with _LOCK:
        raw = _load_raw(okr_id)
        if raw is None:
            return None
        krs = raw.get("key_results") or []
        for i, kr in enumerate(krs):
            if kr.get("id") == kr_id:
                merged = {**kr, **fields, "id": kr_id}
                krs[i] = _validate_kr(merged)
                raw["key_results"] = krs
                raw["updated_at"] = _now()
                _save_raw(raw)
                return krs[i]
    return None


def delete_key_result(okr_id: str, kr_id: str) -> bool:
    with _LOCK:
        raw = _load_raw(okr_id)
        if raw is None:
            return False
        krs = raw.get("key_results") or []
        new = [k for k in krs if k.get("id") != kr_id]
        if len(new) == len(krs):
            return False
        raw["key_results"] = new
        raw["updated_at"] = _now()
        _save_raw(raw)
    return True


# ---- roll-up -------------------------------------------------------------

def summarise(okr: dict[str, Any]) -> dict[str, Any]:
    """Counts per status + a simple health_pct so the UI can render
    a 'X of Y on track' line and a colour."""
    krs = okr.get("key_results") or []
    total = len(krs)
    counts = {s: 0 for s in KR_STATUSES}
    for k in krs:
        s = k.get("status")
        if s in counts:
            counts[s] += 1
    # Health = (on_track + done) / total, 0 when no KRs.
    healthy = counts["on_track"] + counts["done"]
    health_pct = round(100 * healthy / total) if total else 0
    return {
        "total_krs":   total,
        "on_track":    counts["on_track"],
        "at_risk":     counts["at_risk"],
        "missed":      counts["missed"],
        "done":        counts["done"],
        "health_pct":  health_pct,
    }
