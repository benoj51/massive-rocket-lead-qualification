"""
Per-lead state backup + restore (v1.0.0g).

Why this exists: Railway's container filesystem is ephemeral. Every
deploy wipes `cache/`, taking calls / projects / contacts / pricing
with it. Until we mount a persistent volume on /app/cache, the
defence is to MIRROR critical state into the lead's Notion page on
every write, then expose a Restore button.

The backup payload is the union of:
  - lead_summary_store (the AI synthesis)
  - calls_store (every call + extracted MEDDPICC)
  - contacts_store (every lead contact)
  - lead_contact_notes_store (per-contact engagement timeline)
  - project_store (scope + streams + criteria)
  - pricing_store (per-lead pricing config)
  - roadmap (milestones + extended items)

We don't back up:
  - Notion-side fields (they're already in Notion)
  - lead_partner_assignments (small, can be re-derived if needed)
  - accounts_graph (single file, regenerated separately)

Format: JSON, gzip-compressed, base64-encoded, then chunked across
multiple Notion rich_text entries in a property called "State Backup"
(2000-char limit per entry; we use 1900 to be safe).

Restore: caller calls `apply_backup(lead_id, payload)` which writes
each store's piece back. Idempotent — applying the same backup twice
produces the same end state.
"""
from __future__ import annotations

import base64
import gzip
import json
from datetime import datetime, timezone
from typing import Any

import calls_store
import contacts_store
import lead_contact_notes_store
import lead_summary_store
import pricing_store
import project_store
import roadmap as roadmap_module
import scope as scope_module


_SCHEMA_VERSION = 1


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def gather(lead_id: str) -> dict[str, Any]:
    """Collect everything we'd want to restore if the cache vanished."""
    # Calls — the most painful loss case.
    calls = calls_store.list_calls(lead_id)

    # Contacts — lead-side.
    contact_rows = contacts_store._load_raw(lead_id)
    # Engagement timeline per contact.
    contact_notes: dict[str, list] = {}
    for c in contact_rows:
        cid = c.get("id")
        if cid:
            contact_notes[cid] = lead_contact_notes_store._load_raw(lead_id, cid)

    # Project scope.
    project = project_store.load(lead_id)
    project_dict = scope_module.to_dict(project) if project is not None else None

    # Pricing config.
    pricing_cfg = pricing_store.load(lead_id) if pricing_store else None

    # Roadmap.
    roadmap_obj = roadmap_module.load(lead_id) if roadmap_module else None
    roadmap_dict = roadmap_module.to_dict(roadmap_obj) if roadmap_obj is not None else None

    # AI summary.
    summary = lead_summary_store.load(lead_id)

    return {
        "schema_version": _SCHEMA_VERSION,
        "lead_id": lead_id,
        "captured_at": _now_iso(),
        "calls": calls,
        "contacts": contact_rows,
        "contact_notes": contact_notes,
        "project": project_dict,
        "pricing": pricing_cfg,
        "roadmap": roadmap_dict,
        "summary": summary,
    }


def encode(payload: dict[str, Any]) -> str:
    """JSON → gzip → base64. Returns a single string safe to embed in
    Notion rich_text (it's just ASCII)."""
    raw = json.dumps(payload, separators=(",", ":"), default=str)
    compressed = gzip.compress(raw.encode("utf-8"), compresslevel=9)
    return base64.b64encode(compressed).decode("ascii")


def decode(blob: str) -> dict[str, Any]:
    """Reverse of `encode`. Raises ValueError if the blob is malformed."""
    if not blob:
        raise ValueError("empty backup blob")
    try:
        compressed = base64.b64decode(blob.encode("ascii"))
        raw = gzip.decompress(compressed)
        return json.loads(raw)
    except (ValueError, OSError, json.JSONDecodeError) as e:
        raise ValueError(f"invalid backup blob: {e}") from e


def chunk_for_notion(blob: str, chunk_size: int = 1900) -> list[str]:
    """Split the encoded blob into Notion-rich_text-safe chunks. Each
    chunk goes into its own rich_text entry; Notion preserves the order
    on read so we can concatenate cleanly."""
    if not blob:
        return []
    return [blob[i:i + chunk_size] for i in range(0, len(blob), chunk_size)]


def join_chunks(chunks: list[str]) -> str:
    """Inverse of chunk_for_notion."""
    return "".join(chunks)


# --- restore ---------------------------------------------------------------

def apply_backup(lead_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Write each store's slice of the backup back to disk.

    Idempotent: applying the same backup twice ends in the same state.
    Returns a summary dict so the caller can report what was restored.
    """
    summary: dict[str, Any] = {
        "calls": 0,
        "contacts": 0,
        "contact_notes": 0,
        "project_restored": False,
        "pricing_restored": False,
        "roadmap_restored": False,
        "summary_restored": False,
    }

    # Calls — direct overwrite of the stored list. Use the store's
    # private write helper because the public surface only appends.
    calls = payload.get("calls") or []
    if calls:
        calls_store._write_raw(lead_id, calls)
        summary["calls"] = len(calls)

    # Contacts.
    contact_rows = payload.get("contacts") or []
    if contact_rows:
        contacts_store._write_raw(lead_id, contact_rows)
        summary["contacts"] = len(contact_rows)

    # Per-contact engagement notes.
    contact_notes = payload.get("contact_notes") or {}
    for cid, notes in contact_notes.items():
        if notes:
            lead_contact_notes_store._write_raw(lead_id, cid, notes)
            summary["contact_notes"] += len(notes)

    # Project — round-trip via scope_module's from_dict to keep the
    # dataclass shape intact.
    project_dict = payload.get("project")
    if project_dict:
        try:
            project = scope_module.from_dict(project_dict)
            project_store.save(project)
            summary["project_restored"] = True
        except Exception as e:
            summary["project_error"] = str(e)

    # Pricing config — straight pass-through.
    pricing_cfg = payload.get("pricing")
    if pricing_cfg:
        try:
            pricing_store.save(lead_id, pricing_cfg)
            summary["pricing_restored"] = True
        except Exception as e:
            summary["pricing_error"] = str(e)

    # Roadmap.
    roadmap_dict = payload.get("roadmap")
    if roadmap_dict:
        try:
            rm = roadmap_module.from_dict(roadmap_dict)
            roadmap_module.save(rm)
            summary["roadmap_restored"] = True
        except Exception as e:
            summary["roadmap_error"] = str(e)

    # AI summary.
    ai_summary_payload = payload.get("summary")
    if ai_summary_payload:
        try:
            lead_summary_store.save(lead_id, ai_summary_payload)
            summary["summary_restored"] = True
        except Exception as e:
            summary["summary_error"] = str(e)

    return summary


def is_empty_cache_for(lead_id: str) -> bool:
    """True iff we have NOTHING locally for this lead — useful for the
    UI to surface a 'Restore from Notion' prompt only when warranted."""
    if calls_store.list_calls(lead_id):
        return False
    if contacts_store._load_raw(lead_id):
        return False
    if project_store.load(lead_id) is not None:
        return False
    return True
