"""
Persistent call / note log per lead.

Stores one JSON file per lead at cache/calls/<lead_id>.json, holding a list
of call records. Each record captures the AE's notes from a call or
transcript paste, the AI extraction results, and the timestamp.

Records are immutable once written (except for deletion). To "edit" a
record, the AE adds a new one with corrected content.

Public surface:
    list_calls(lead_id)                -> list[dict] (newest first)
    add_call(lead_id, payload)         -> the persisted record
    delete_call(lead_id, call_id)      -> bool
    aggregate_extractions(lead_id)     -> {meddpicc: {...}, signals: [...], project_scope: str|None}
        Merges extraction results across all calls (newer wins).

Record shape:
    {
        "id":            str,
        "lead_id":       str,
        "created_at":    ISO timestamp,
        "type":          "call" | "note" | "email" | "transcript",
        "title":         str,                   # optional headline
        "attendees":     list[str],             # contact names if known
        "content":       str,                   # the raw notes/transcript
        "extracted":     {meddpicc: {...}, project_scope: str|None}  # optional AI output
    }
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DIR = Path(__file__).parent / "cache" / "calls"


class CallsStoreError(RuntimeError):
    pass


VALID_TYPES = {"call", "note", "email", "transcript"}


def _store_dir() -> Path:
    override = os.environ.get("CALLS_STORE_DIR")
    d = Path(override) if override else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(lead_id: str) -> Path:
    import project_store
    return _store_dir() / f"{project_store.slugify(lead_id)}.json"


def _now() -> str:
    # Microsecond precision so back-to-back saves sort deterministically.
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _load_raw(lead_id: str, *, strict: bool = False) -> list[dict[str, Any]]:
    """Load this lead's call / note log. v1.0.0dp: routed through the
    corruption-aware loader. Mutation callers pass strict=True so a file
    we cannot read aborts the write (translated to CallsStoreError)
    instead of silently clobbering recoverable history; read callers use
    the default lenient mode (returns [], recovers from .bak)."""
    import json_file_store
    try:
        return json_file_store.load_list_safe(_path(lead_id), strict=strict)
    except json_file_store.CorruptStoreError as e:
        raise CallsStoreError(
            "call/note history file is unreadable; refusing to save so "
            "existing notes are not overwritten") from e


def _write_raw(lead_id: str, rows: list[dict[str, Any]]) -> None:
    # v1.0.0cu: atomic write via json_file_store. Audit caught that
    # a crash during write_text() could corrupt the calls file and the
    # load path swallows the JSONDecodeError silently, losing every
    # note for that lead. tempfile + os.replace prevents partial writes.
    # v1.0.0dp: write_json_backup adds a .bak sidecar so a bad write or
    # an accidental wipe stays recoverable.
    import json_file_store
    json_file_store.write_json_backup(_path(lead_id), rows)


def list_calls(lead_id: str) -> list[dict[str, Any]]:
    rows = _load_raw(lead_id)  # read path: lenient (recovers from .bak, never raises)
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return rows


def add_call(lead_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Append a new call/note record. Returns the persisted record."""
    content = (payload.get("content") or "").strip()
    if not content:
        raise CallsStoreError("content is required")
    call_type = (payload.get("type") or "note").strip().lower()
    if call_type not in VALID_TYPES:
        call_type = "note"
    extracted = payload.get("extracted") or None
    # If AI gave us a synthesised note, copy it into `note` as the AE-editable
    # initial value. The AE can edit `note` later; `extracted.synthesised_note`
    # is preserved as the original AI draft.
    note = (payload.get("note") or "").strip()
    if not note and isinstance(extracted, dict):
        note = (extracted.get("synthesised_note") or "").strip()
    record: dict[str, Any] = {
        "id": str(payload.get("id") or "").strip() or uuid.uuid4().hex[:12],
        "lead_id": lead_id,
        "created_at": _now(),
        "updated_at": _now(),
        "type": call_type,
        "title": (payload.get("title") or "").strip(),
        "attendees": [str(a).strip() for a in (payload.get("attendees") or []) if str(a).strip()],
        "content": content,
        "note": note,
        "extracted": extracted,
        # v1.0.0z: attribution. Optional — when set, this note was
        # sourced from a specific partner / partner contact (e.g.
        # "Marina at Braze told us Popeyes Q3 is moving"). Powers
        # rollup views on the partner contact + smarter AI synthesis
        # ("Marina (Braze) flagged ..." vs generic "we heard ...").
        # Shape: {partner_id, contact_id?, partner_name?, contact_name?}.
        # contact_id is optional for "Braze partnership team" attribution.
        "partner_source": _normalise_partner_source(payload.get("partner_source")),
    }
    rows = _load_raw(lead_id, strict=True)
    rows.append(record)
    _write_raw(lead_id, rows)
    return record


def _normalise_partner_source(src: Any) -> dict[str, Any] | None:
    """Coerce caller-supplied partner_source into a clean dict.
    Accepts None, empty dict, or a dict with partner_id / contact_id
    plus optional display names. Returns None when nothing useful is
    present so the field can be safely omitted from older records."""
    if not src or not isinstance(src, dict):
        return None
    partner_id = (src.get("partner_id") or "").strip()
    if not partner_id:
        return None
    out: dict[str, Any] = {"partner_id": partner_id}
    cid = (src.get("contact_id") or "").strip()
    if cid:
        out["contact_id"] = cid
    pname = (src.get("partner_name") or "").strip()
    if pname:
        out["partner_name"] = pname
    cname = (src.get("contact_name") or "").strip()
    if cname:
        out["contact_name"] = cname
    return out


def update_call(lead_id: str, call_id: str, edits: dict[str, Any]) -> dict[str, Any] | None:
    """Apply edits to an existing call (note, title, attendees). The raw
    content + AI-extracted block stay immutable — to change those, delete
    and re-add."""
    rows = _load_raw(lead_id, strict=True)
    for r in rows:
        if r.get("id") != call_id:
            continue
        if "note" in edits:
            r["note"] = (edits["note"] or "").strip()
        if "title" in edits:
            r["title"] = (edits["title"] or "").strip()
        if "attendees" in edits:
            r["attendees"] = [str(a).strip() for a in (edits["attendees"] or [])
                              if str(a).strip()]
        # v1.0.0z: partner_source is editable so an AE who forgot to
        # attribute on first save can fix it later.
        if "partner_source" in edits:
            r["partner_source"] = _normalise_partner_source(edits["partner_source"])
        r["updated_at"] = _now()
        _write_raw(lead_id, rows)
        return r
    return None


def delete_call(lead_id: str, call_id: str) -> bool:
    rows = _load_raw(lead_id, strict=True)
    new_rows = [r for r in rows if r.get("id") != call_id]
    if len(new_rows) == len(rows):
        return False
    _write_raw(lead_id, new_rows)
    return True


# v1.0.0z: cross-lead lookup for partner-sourced notes. Used by the
# "all account intel Marina has contributed" rollup on a partner
# contact's summary surface.
def list_calls_sourced_from(
    *, partner_id: str | None = None, contact_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return every call across every lead whose partner_source
    matches the supplied filter. If contact_id is set, matches that
    specific person; else if only partner_id is set, matches any
    note attributed to that partner generically. Each returned row is
    annotated with the lead_id it belongs to (already on the record)."""
    if not partner_id and not contact_id:
        return []
    out: list[dict[str, Any]] = []
    d = _store_dir()
    if not d.exists():
        return out
    for f in d.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            if not isinstance(data, list):
                continue
        except (json.JSONDecodeError, OSError):
            continue
        for row in data:
            src = row.get("partner_source") or {}
            if contact_id and src.get("contact_id") != contact_id:
                continue
            if partner_id and src.get("partner_id") != partner_id:
                continue
            if not src.get("partner_id"):
                continue
            out.append(row)
    # Newest first — matches list_calls convention.
    out.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return out


def aggregate_extractions(lead_id: str) -> dict[str, Any]:
    """Merge extraction results across all calls. Newer records win.

    Useful for building a "rolling" MEDDPICC view that reflects everything
    we've learned about the lead — not just the most recent qualification.

    v1.0.0bb: also surfaces deduped tech_stack_mentioned + the set of
    agencies mentioned (with the call ids that mentioned each, so the
    UI can link back to the source). MEDDPICC behaviour unchanged.
    """
    calls = sorted(_load_raw(lead_id), key=lambda r: r.get("created_at") or "")
    meddpicc: dict[str, Any] = {}
    project_scope: str | None = None
    # v1.0.0bb: cross-call rollups for tech + agencies. Keyed by
    # case-insensitive name; the value tracks call provenance so the
    # UI can "view the call that mentioned this".
    tech_stack_map: dict[str, dict[str, Any]] = {}
    agencies_map: dict[str, dict[str, Any]] = {}
    for c in calls:
        ext = c.get("extracted") or {}
        for k, v in (ext.get("meddpicc") or {}).items():
            if isinstance(v, dict) and v.get("value"):
                meddpicc[k] = {"value": v["value"]}
        if ext.get("project_scope"):
            project_scope = ext["project_scope"]
        # Tech stack rollup
        for name in (ext.get("tech_stack_mentioned") or []):
            if not isinstance(name, str):
                continue
            key = name.strip().lower()
            if not key:
                continue
            entry = tech_stack_map.setdefault(key, {
                "name": name.strip(),
                "mentions": 0,
                "first_mentioned_at": c.get("created_at"),
                "last_mentioned_at":  c.get("created_at"),
                "call_ids": [],
            })
            entry["mentions"] += 1
            entry["last_mentioned_at"] = c.get("created_at")
            if c.get("id") and c["id"] not in entry["call_ids"]:
                entry["call_ids"].append(c["id"])
        # Agencies rollup — same shape so the UI renders identically.
        for ag in (ext.get("competitive_agencies") or []):
            if not isinstance(ag, dict):
                continue
            name = (ag.get("name") or "").strip()
            if not name:
                continue
            key = name.lower()
            entry = agencies_map.setdefault(key, {
                "name": name,
                "context": ag.get("context"),
                "mentions": 0,
                "first_mentioned_at": c.get("created_at"),
                "last_mentioned_at":  c.get("created_at"),
                "call_ids": [],
            })
            entry["mentions"] += 1
            entry["last_mentioned_at"] = c.get("created_at")
            # Most recent context wins (signal evolves over the call
            # sequence: "evaluating" → "incumbent" etc).
            if ag.get("context"):
                entry["context"] = ag["context"]
            if c.get("id") and c["id"] not in entry["call_ids"]:
                entry["call_ids"].append(c["id"])
    return {
        "meddpicc": meddpicc,
        "project_scope": project_scope,
        "tech_stack_mentioned": sorted(tech_stack_map.values(),
                                         key=lambda e: -e["mentions"]),
        "competitive_agencies": sorted(agencies_map.values(),
                                         key=lambda e: -e["mentions"]),
    }
