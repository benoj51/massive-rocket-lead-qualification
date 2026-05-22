"""
Per-lead agency relationships (v1.0.0p).

Tracks the agencies an account has worked with — current (incumbent)
and past (previous). Powers two flows:
  - During qualification: AE captures "who's running their Braze today"
    so the AI synthesis can frame the displacement angle from the
    first call.
  - After the fact: AE adds historical agencies as they surface in
    calls ("they used Razorfish before, fired them in 2023") — useful
    for pattern-matching ("this brand churns agencies every 18mo, be
    careful with year-2 retention").

Storage: one JSON file per lead at cache/lead_agencies/<lead_id>.json —
same pattern as contacts_store / lead_contact_notes_store. Survives
Railway cache wipes because the volume is now mounted, and gets
mirrored into Notion via state_backup like everything else.

Schema per entry:
    {
      "id":         str (uuid),
      "lead_id":    str,
      "name":       str,            # e.g. "VML", "Razorfish", "in-house"
      "type":       str,            # "incumbent" | "previous"
      "scope":      str | None,     # what they do/did — "Braze ops"
      "since":      str | None,     # ISO date — relationship start
      "until":      str | None,     # ISO date — relationship end (none → ongoing)
      "notes":      str | None,     # free text — quality, exec dynamic, etc.
      "added_at":   str,
      "updated_at": str,
    }
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DIR = Path(__file__).parent / "cache" / "lead_agencies"
_LOCK = threading.Lock()


# Type constants — keep the UI dropdown + store validation aligned.
TYPE_INCUMBENT = "incumbent"
TYPE_PREVIOUS = "previous"
AGENCY_TYPES = [TYPE_INCUMBENT, TYPE_PREVIOUS]


class LeadAgenciesStoreError(RuntimeError):
    pass


def _store_dir() -> Path:
    override = os.environ.get("LEAD_AGENCIES_STORE_DIR")
    d = Path(override) if override else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slugify(value: str) -> str:
    import project_store
    return project_store.slugify(value)


def _path(lead_id: str) -> Path:
    return _store_dir() / f"{_slugify(lead_id)}.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_raw(lead_id: str) -> list[dict[str, Any]]:
    p = _path(lead_id)
    if not p.exists():
        return []
    try:
        with _LOCK:
            return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _write_raw(lead_id: str, rows: list[dict[str, Any]]) -> None:
    with _LOCK:
        _path(lead_id).write_text(json.dumps(rows, indent=2))


def _normalise(lead_id: str, payload: dict[str, Any],
                existing: dict[str, Any] | None = None) -> dict[str, Any]:
    name = (payload.get("name") or "").strip()
    if not name:
        raise LeadAgenciesStoreError("Agency name is required")
    t = (payload.get("type") or TYPE_INCUMBENT).strip().lower()
    if t not in AGENCY_TYPES:
        raise LeadAgenciesStoreError(
            f"Agency type must be one of {AGENCY_TYPES}, got {t!r}")
    return {
        "id":         (existing or {}).get("id") or payload.get("id") or uuid.uuid4().hex[:12],
        "lead_id":    _slugify(lead_id),
        "name":       name,
        "type":       t,
        "scope":      (payload.get("scope") or "").strip() or None,
        "since":      (payload.get("since") or "").strip() or None,
        "until":      (payload.get("until") or "").strip() or None,
        "notes":      (payload.get("notes") or "").strip() or None,
        "added_at":   (existing or {}).get("added_at") or _now_iso(),
        "updated_at": _now_iso(),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_agencies(lead_id: str) -> list[dict[str, Any]]:
    """All agency entries for the lead, sorted incumbents-first then
    alphabetical by name (newest historical entries at the bottom so
    the AE reads top-down: current → past)."""
    rows = _load_raw(lead_id)
    rows.sort(key=lambda r: (
        # Incumbents first
        r.get("type") != TYPE_INCUMBENT,
        # Then alpha by name (case-insensitive)
        (r.get("name") or "").lower(),
    ))
    return rows


def get_agency(lead_id: str, agency_id: str) -> dict[str, Any] | None:
    for r in _load_raw(lead_id):
        if r.get("id") == agency_id:
            return r
    return None


def save_agency(lead_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Add or update an agency entry by id."""
    rows = _load_raw(lead_id)
    incoming_id = payload.get("id")
    existing: dict[str, Any] | None = None
    if incoming_id:
        existing = next((r for r in rows if r.get("id") == incoming_id), None)
    clean = _normalise(lead_id, payload, existing=existing)
    if existing:
        for i, r in enumerate(rows):
            if r.get("id") == clean["id"]:
                rows[i] = clean
                break
    else:
        rows.append(clean)
    _write_raw(lead_id, rows)
    return clean


def delete_agency(lead_id: str, agency_id: str) -> bool:
    rows = _load_raw(lead_id)
    new_rows = [r for r in rows if r.get("id") != agency_id]
    if len(new_rows) == len(rows):
        return False
    _write_raw(lead_id, new_rows)
    return True


def delete_all_for_lead(lead_id: str) -> bool:
    """Used by the lead-deletion cleanup path."""
    p = _path(lead_id)
    if not p.exists():
        return False
    try:
        with _LOCK:
            p.unlink()
        return True
    except OSError:
        return False


# Convenience for the AI synthesis layer — flat strings the prompt can
# weave into context: ["VML (incumbent, Braze ops)", "Razorfish (previous, 2019-2022)"].
def summarise_for_ai(lead_id: str) -> list[str]:
    out: list[str] = []
    for r in list_agencies(lead_id):
        parts = [r["name"]]
        meta_bits: list[str] = [r["type"]]
        if r.get("scope"):
            meta_bits.append(r["scope"])
        if r.get("type") == TYPE_PREVIOUS and (r.get("since") or r.get("until")):
            window = " to ".join(filter(None, [r.get("since"), r.get("until")]))
            if window:
                meta_bits.append(window)
        out.append(f"{parts[0]} ({', '.join(meta_bits)})")
    return out
