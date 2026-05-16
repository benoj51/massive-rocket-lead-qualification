"""
Versioned SOW store.

Each lead gets a directory at cache/sows/<lead_id>/ with files:
    v1.json, v2.json, ...

A SOW is immutable once written — never overwritten, only appended. To
"update" a SOW, the AE generates a new version. The latest version is
whichever has the highest integer in its filename.

Public surface:
    save(lead_id, snapshot)     -> version_number  (auto-incremented)
    load(lead_id, version)      -> snapshot or None
    list_versions(lead_id)      -> [{"version": int, "generated_at": str}, ...]
    latest(lead_id)             -> snapshot or None
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

_DEFAULT_DIR = Path(__file__).parent / "cache" / "sows"
_LOCK = threading.Lock()
_VERSION_RE = re.compile(r"^v(\d+)\.json$")


def _store_dir() -> Path:
    override = os.environ.get("SOW_STORE_DIR")
    d = Path(override) if override else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _lead_dir(lead_id: str) -> Path:
    # Reuse project_store's slugify for consistent lead_id handling.
    import project_store
    d = _store_dir() / project_store.slugify(lead_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _existing_versions(lead_id: str) -> list[int]:
    out: list[int] = []
    for p in _lead_dir(lead_id).iterdir():
        m = _VERSION_RE.match(p.name)
        if m:
            out.append(int(m.group(1)))
    return sorted(out)


def save(lead_id: str, snapshot: dict[str, Any]) -> int:
    """Persist a snapshot under the next available version number."""
    with _LOCK:
        existing = _existing_versions(lead_id)
        version = (max(existing) + 1) if existing else 1
        path = _lead_dir(lead_id) / f"v{version}.json"
        payload = dict(snapshot)
        payload["version"] = version
        path.write_text(json.dumps(payload, indent=2))
        return version


def load(lead_id: str, version: int) -> dict[str, Any] | None:
    path = _lead_dir(lead_id) / f"v{int(version)}.json"
    if not path.exists():
        return None
    try:
        with _LOCK:
            return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def list_versions(lead_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for v in _existing_versions(lead_id):
        snap = load(lead_id, v)
        if snap is None:
            continue
        rows.append({
            "version": v,
            "generated_at": snap.get("generated_at"),
            "validation_status_at_generation": snap.get("validation_status_at_generation"),
            "net_usd": snap.get("sections", {}).get("investment", {}).get("totals", {}).get("net_usd"),
        })
    rows.sort(key=lambda r: r["version"], reverse=True)
    return rows


def latest(lead_id: str) -> dict[str, Any] | None:
    existing = _existing_versions(lead_id)
    if not existing:
        return None
    return load(lead_id, max(existing))
