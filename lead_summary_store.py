"""
Cached lead-level AI synthesis per lead.

Storing the Claude-generated lead summary so the drawer doesn't re-run
the synthesis on every open. Refreshes on demand via the ✨ button or
implicitly when meaningful state changes (new call, new contact).

Storage: cache/lead_summaries/<lead_id>.json
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DIR = Path(__file__).parent / "cache" / "lead_summaries"
_LOCK = threading.Lock()


def _store_dir() -> Path:
    override = os.environ.get("LEAD_SUMMARY_STORE_DIR")
    d = Path(override) if override else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(lead_id: str) -> Path:
    import project_store
    return _store_dir() / f"{project_store.slugify(lead_id)}.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load(lead_id: str) -> dict[str, Any] | None:
    p = _path(lead_id)
    if not p.exists():
        return None
    try:
        with _LOCK:
            return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save(lead_id: str, summary: dict[str, Any]) -> dict[str, Any]:
    payload = dict(summary)
    payload["generated_at"] = _now_iso()
    with _LOCK:
        _path(lead_id).write_text(json.dumps(payload, indent=2))
    return payload


def delete(lead_id: str) -> bool:
    p = _path(lead_id)
    if not p.exists():
        return False
    try:
        with _LOCK:
            p.unlink()
        return True
    except OSError:
        return False
