"""
Pricing configuration per lead.

The pricing inputs (currency, rate card, project ops %, contingency %,
discount %, months, role FTE overrides, Staff Aug staffing) were
client-state-only before v0.9.1. Closing the tab lost them. This module
persists the inputs alongside the scope + roadmap + calls so the AE can
come back to a project and pick up where they left off.

Storage: cache/pricing_configs/<lead_id>.json

Schema (all fields optional, defaults match pricing.QuoteInputs):
    {
      "currency": "USD" | "GBP" | "EUR",
      "rate_card": "MR Default" | "Staff Augmentation" | client name,
      "months": int,
      "project_ops_pct": float (0.0–1.0),
      "contingency_pct": float (0.0–1.0),
      "discount_first_half_pct": float,
      "discount_second_half_pct": float,
      "role_overrides": {role: {phase: fte}},
      "role_staffing": {role: {region, seniority}},
      "selected_package": str (optional — last package picker value),
      "updated_at": ISO timestamp
    }
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DIR = Path(__file__).parent / "cache" / "pricing_configs"
_LOCK = threading.Lock()


def _store_dir() -> Path:
    override = os.environ.get("PRICING_STORE_DIR")
    d = Path(override) if override else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(lead_id: str) -> Path:
    import project_store
    return _store_dir() / f"{project_store.slugify(lead_id)}.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# Keys we'll persist — anything not in this set is dropped on save so the
# store doesn't accumulate stale fields from older clients.
_ALLOWED_KEYS = {
    "currency", "rate_card", "months",
    "project_ops_pct", "contingency_pct",
    "discount_first_half_pct", "discount_second_half_pct",
    "role_overrides", "role_staffing",
    "selected_package",
}


def load(lead_id: str) -> dict[str, Any] | None:
    p = _path(lead_id)
    if not p.exists():
        return None
    try:
        with _LOCK:
            return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save(lead_id: str, config: dict[str, Any]) -> dict[str, Any]:
    """Persist the config. Filters to known keys and stamps updated_at."""
    cleaned = {k: v for k, v in (config or {}).items() if k in _ALLOWED_KEYS}
    cleaned["updated_at"] = _now_iso()
    p = _path(lead_id)
    with _LOCK:
        p.write_text(json.dumps(cleaned, indent=2))
    return cleaned


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
