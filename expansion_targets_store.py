"""v1.0.0bo — Account expansion targets.

The land-and-expand motion. MR wins Shell North America (the
"anchor account") — now the team should be working Shell UK, Shell
EMEA, Shell APAC as expansion opportunities. Each target sits
between "we know about it" and "it's a real lead in the pipeline":
captures the early-stage research, contact mapping, and notes that
inform when (and how) to formally qualify it.

Why a separate store
--------------------
- Targets aren't leads yet (no Notion page, no scoring, no SOW).
  Forcing them through the lead pipeline before they're ready would
  pollute the pipeline metrics + force premature qualification.
- They aren't live projects either (nothing to deliver).
- They're a third thing: pre-qualification research, anchored to a
  won account.

Once a target is ready to enter the pipeline, the convert-to-lead
flow creates the real lead in Notion + marks the target as
`converted_to_lead` with a reference to the new lead id — so the
expansion history stays intact for audit.

Shape
-----
    {
      "id":              "<uuid4>",
      "anchor_lead_id":  "shell-na-page-id",   # the WON lead that
                                                # motivates this target
      "name":            "Shell UK",
      "region":          "UK",                  # free-form
      "vertical":        "Energy",              # optional
      "status":          "greenfield",
      "notes":           "<markdown>",
      "contacts": [
        {"id": "<uuid8>", "name": "Sarah Johnson",
         "title": "Head of Loyalty UK", "email": "...",
         "source": "via Marina at Braze"},
      ],
      "converted_lead_id": None | "<page-id>",
      "converted_at":      None | iso,
      "created_at":     iso,
      "updated_at":     iso,
    }

Statuses (sorted by progression)
--------------------------------
- `greenfield`         — known opportunity, no work started
- `researching`        — gathering contacts + intel
- `qualifying`         — actively talking to people, building case
- `converted_to_lead`  — became a real lead in the pipeline
- `dropped`            — decided not to pursue

API
---
    list_all(*, status=None) -> list[dict]      # sorted by anchor + name
    list_by_anchor(anchor_lead_id) -> list[dict]
    get(target_id) -> dict | None
    create(anchor_lead_id, name, *, region=None, vertical=None,
            notes=None) -> dict
    update(target_id, **fields) -> dict | None
    delete(target_id) -> bool
    add_contact(target_id, payload) -> dict
    update_contact(target_id, contact_id, **fields) -> dict | None
    delete_contact(target_id, contact_id) -> bool
    mark_converted(target_id, lead_id) -> dict | None
"""
from __future__ import annotations

import json
import json_file_store
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DIR = Path(__file__).parent / "cache" / "expansion_targets"
_LOCK = threading.Lock()

STATUSES = ("greenfield", "researching", "qualifying",
            "converted_to_lead", "dropped")
_ALLOWED_UPDATE = {"name", "region", "vertical", "status",
                    "notes", "contacts"}
_ALLOWED_CONTACT_UPDATE = {"name", "title", "email", "source", "notes"}


class ExpansionTargetsStoreError(RuntimeError):
    pass


def _store_dir() -> Path:
    override = os.environ.get("EXPANSION_TARGETS_STORE_DIR")
    d = Path(override) if override else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _safe_id(value: str) -> str:
    """v1.0.0bz: strict ID guard. IDs are generated server-side as
    uuid4 hex (32 chars of [0-9a-f]). A client-supplied id that
    doesn't match the safe alphabet is rejected outright — defends
    against `../../etc/passwd` style escapes from any future code
    path that ever calls _path with non-URL input."""
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise ExpansionTargetsStoreError(f"invalid id: {value!r}")
    return value


def _path(target_id: str) -> Path:
    return _store_dir() / f"{_safe_id(target_id)}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_raw(target_id: str) -> dict[str, Any] | None:
    p = _path(target_id)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _save_raw(target: dict[str, Any]) -> None:
    p = _path(target["id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    json_file_store.write_json(p, target)


def _normalise_contact(c: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(c, dict):
        raise ExpansionTargetsStoreError("contact must be an object")
    name = (c.get("name") or "").strip()
    if not name:
        raise ExpansionTargetsStoreError("contact.name required")
    return {
        "id":     c.get("id") or uuid.uuid4().hex[:10],
        "name":   name,
        "title":  (c.get("title") or "").strip() or None,
        "email":  (c.get("email") or "").strip() or None,
        "source": (c.get("source") or "").strip() or None,
        "notes":  (c.get("notes") or "").strip() or None,
    }


def _normalise(t: dict[str, Any]) -> dict[str, Any]:
    out = dict(t)
    out.setdefault("id", uuid.uuid4().hex)
    out.setdefault("anchor_lead_id", "")
    out.setdefault("name", "")
    out.setdefault("region", None)
    out.setdefault("vertical", None)
    out.setdefault("status", "greenfield")
    out.setdefault("notes", None)
    out.setdefault("contacts", [])
    out.setdefault("converted_lead_id", None)
    out.setdefault("converted_at", None)
    out.setdefault("created_at", _now())
    out.setdefault("updated_at", out["created_at"])
    # Don't validate contact shape here — _validate_contact only runs
    # on writes. _normalise just ensures the field exists.
    return out


def _validate_status(s: Any) -> str:
    if not isinstance(s, str) or s not in STATUSES:
        raise ExpansionTargetsStoreError(
            f"status must be one of {STATUSES}; got {s!r}")
    return s


# ---- core API -------------------------------------------------------------

def list_all(*, status: str | None = None) -> list[dict[str, Any]]:
    """All targets across all anchors. Sorted by anchor_lead_id then
    by name so the UI's anchor-grouped render comes out ordered."""
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
        out = [t for t in out if t.get("status") == status]
    out.sort(key=lambda t: (
        t.get("anchor_lead_id") or "",
        (t.get("name") or "").lower(),
    ))
    return out


def list_by_anchor(anchor_lead_id: str) -> list[dict[str, Any]]:
    if not anchor_lead_id:
        return []
    return [t for t in list_all()
            if t.get("anchor_lead_id") == anchor_lead_id]


def get(target_id: str) -> dict[str, Any] | None:
    if not target_id:
        return None
    raw = _load_raw(target_id)
    return _normalise(raw) if raw else None


def create(anchor_lead_id: str, name: str, *,
            region: str | None = None,
            vertical: str | None = None,
            notes: str | None = None) -> dict[str, Any]:
    if not (anchor_lead_id or "").strip():
        raise ExpansionTargetsStoreError("anchor_lead_id required")
    if not (name or "").strip():
        raise ExpansionTargetsStoreError("name required")
    target = _normalise({
        "id":             uuid.uuid4().hex,
        "anchor_lead_id": anchor_lead_id.strip(),
        "name":           name.strip()[:200],
        "region":         (region or "").strip() or None,
        "vertical":       (vertical or "").strip() or None,
        "status":         "greenfield",
        "notes":          (notes or "").strip() or None,
        "contacts":       [],
        "created_at":     _now(),
        "updated_at":     _now(),
    })
    with _LOCK:
        _save_raw(target)
    return target


def update(target_id: str, **fields: Any) -> dict[str, Any] | None:
    if not target_id:
        return None
    bad = set(fields) - _ALLOWED_UPDATE
    if bad:
        raise ExpansionTargetsStoreError(
            f"unknown fields: {sorted(bad)}. Allowed: {sorted(_ALLOWED_UPDATE)}")
    with _LOCK:
        raw = _load_raw(target_id)
        if raw is None:
            return None
        if "status" in fields:
            raw["status"] = _validate_status(fields["status"])
        if "name" in fields:
            name = (fields["name"] or "").strip()
            if not name:
                raise ExpansionTargetsStoreError("name cannot be empty")
            raw["name"] = name[:200]
        if "region" in fields:
            raw["region"] = (fields["region"] or "").strip() or None
        if "vertical" in fields:
            raw["vertical"] = (fields["vertical"] or "").strip() or None
        if "notes" in fields:
            raw["notes"] = (fields["notes"] or "").strip() or None
        if "contacts" in fields:
            contacts = fields["contacts"]
            if not isinstance(contacts, list):
                raise ExpansionTargetsStoreError("contacts must be a list")
            raw["contacts"] = [_normalise_contact(c) for c in contacts]
        raw["updated_at"] = _now()
        _save_raw(raw)
        return _normalise(raw)


def delete(target_id: str) -> bool:
    if not target_id:
        return False
    with _LOCK:
        p = _path(target_id)
        if not p.exists():
            return False
        p.unlink()
    return True


def add_contact(target_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Append a contact + persist. Returns the new contact entry."""
    with _LOCK:
        raw = _load_raw(target_id)
        if raw is None:
            raise ExpansionTargetsStoreError(f"target {target_id!r} not found")
        contact = _normalise_contact({**payload,
                                        "id": uuid.uuid4().hex[:10]})
        raw.setdefault("contacts", []).append(contact)
        raw["updated_at"] = _now()
        _save_raw(raw)
        return contact


def update_contact(target_id: str, contact_id: str,
                    **fields: Any) -> dict[str, Any] | None:
    bad = set(fields) - _ALLOWED_CONTACT_UPDATE
    if bad:
        raise ExpansionTargetsStoreError(
            f"unknown contact fields: {sorted(bad)}")
    with _LOCK:
        raw = _load_raw(target_id)
        if raw is None:
            return None
        contacts = raw.get("contacts") or []
        for i, c in enumerate(contacts):
            if c.get("id") == contact_id:
                merged = _normalise_contact({**c, **fields, "id": contact_id})
                contacts[i] = merged
                raw["contacts"] = contacts
                raw["updated_at"] = _now()
                _save_raw(raw)
                return merged
    return None


def delete_contact(target_id: str, contact_id: str) -> bool:
    with _LOCK:
        raw = _load_raw(target_id)
        if raw is None:
            return False
        contacts = raw.get("contacts") or []
        new = [c for c in contacts if c.get("id") != contact_id]
        if len(new) == len(contacts):
            return False
        raw["contacts"] = new
        raw["updated_at"] = _now()
        _save_raw(raw)
    return True


def mark_converted(target_id: str, lead_id: str) -> dict[str, Any] | None:
    """Mark a target as converted-to-lead and stash the new lead id
    so the expansion history preserves the lineage."""
    if not (target_id and lead_id):
        return None
    with _LOCK:
        raw = _load_raw(target_id)
        if raw is None:
            return None
        raw["status"] = "converted_to_lead"
        raw["converted_lead_id"] = lead_id
        raw["converted_at"] = _now()
        raw["updated_at"] = _now()
        _save_raw(raw)
        return _normalise(raw)
