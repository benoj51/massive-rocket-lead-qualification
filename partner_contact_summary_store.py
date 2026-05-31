"""
Cached partner-contact AI synthesis per contact (v1.0.0m).

Mirrors `lead_summary_store` but for the partner-side. When Ben adds a
note to a partner contact (e.g. Marina at Braze), we run Claude across
the contact's full note history and cache the structured synthesis:

    summary, accounts_discussed, updates_on_prior_accounts,
    territory_info, challenges, opportunities, additional_info

The cache means the notes modal doesn't re-run Claude on every open —
it just loads the cached payload until the next note save invalidates
it.

Storage: cache/partner_contact_summaries/<partner_slug>/<contact_id>.json
— same per-partner-then-per-contact layout `partner_notes_store` uses,
so the file shape stays predictable.
"""
from __future__ import annotations

import json
import json_file_store
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DIR = Path(__file__).parent / "cache" / "partner_contact_summaries"
_LOCK = threading.Lock()


def _store_dir() -> Path:
    override = os.environ.get("PARTNER_CONTACT_SUMMARY_STORE_DIR")
    d = Path(override) if override else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slugify(value: str) -> str:
    import project_store
    return project_store.slugify(value)


def _path(partner_id: str, contact_id: str) -> Path:
    d = _store_dir() / _slugify(partner_id)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{_slugify(contact_id)}.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load(partner_id: str, contact_id: str) -> dict[str, Any] | None:
    p = _path(partner_id, contact_id)
    if not p.exists():
        return None
    try:
        with _LOCK:
            return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save(partner_id: str, contact_id: str, summary: dict[str, Any]) -> dict[str, Any]:
    payload = dict(summary)
    payload["generated_at"] = _now_iso()
    with _LOCK:
        json_file_store.write_json(_path(partner_id, contact_id), payload)
    return payload


def delete(partner_id: str, contact_id: str) -> bool:
    p = _path(partner_id, contact_id)
    if not p.exists():
        return False
    try:
        with _LOCK:
            p.unlink()
        return True
    except OSError:
        return False
