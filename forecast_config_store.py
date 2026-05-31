"""
Forecast configuration (v1.0.0n).

Editable knobs for the pipeline forecast:
- Stage → probability mapping (what % to weight each sales_stage at)
- Quarterly bookings target (for coverage-ratio calculation)
- Currency presentation (MR runs in GBP)

Stored at cache/forecast_config.json. Defaults applied on load so the
forecast works out of the box; users override via PATCH /api/forecast/config
from the settings panel.
"""
from __future__ import annotations

import json
import json_file_store
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path(__file__).parent / "cache" / "forecast_config.json"
_LOCK = threading.Lock()


# Industry-standard defaults tuned to MR's stage names. These are the
# weights applied to each stage when summing weighted pipeline.
#
# v1.0.0s: "Intro Call" was previously in this map but `PIPELINE_STAGES`
# excludes it — meaning the knob did nothing. We've removed it: Intro
# Call is pre-pipeline by design. If you want it in the forecast, add
# it to BOTH this map AND `PIPELINE_STAGES` below.
DEFAULT_STAGE_PROBABILITIES: dict[str, float] = {
    "Discovery":          0.20,
    "Technical Fit":      0.35,
    "Proposal":           0.50,
    "Negotiation":        0.70,
    "Legal/Procurement":  0.85,
    "Verbal Commit":      0.95,
    "Signature":          1.00,
}

# Stage groupings for the Commit / Best / Pipeline buckets that every
# sales leader expects to see.
COMMIT_STAGES = {"Verbal Commit", "Signature"}
BEST_CASE_STAGES = {"Negotiation", "Legal/Procurement", "Verbal Commit", "Signature"}
PIPELINE_STAGES = {
    "Discovery", "Technical Fit", "Proposal",
    "Negotiation", "Legal/Procurement",
    "Verbal Commit", "Signature",
}

DEFAULT_QUARTERLY_TARGET_GBP = 500_000  # £500k/Q starting point


def _path() -> Path:
    override = os.environ.get("FORECAST_CONFIG_PATH")
    p = Path(override) if override else _DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load() -> dict[str, Any]:
    """Load config, applying defaults for any missing keys so the
    forecast logic doesn't have to handle Nones."""
    p = _path()
    raw: dict[str, Any] = {}
    if p.exists():
        try:
            with _LOCK:
                raw = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            raw = {}
    # Merge per-stage probabilities — user overrides win, defaults fill gaps.
    stage_probs = dict(DEFAULT_STAGE_PROBABILITIES)
    user_probs = raw.get("stage_probabilities") or {}
    for stage, prob in user_probs.items():
        try:
            p_val = float(prob)
            stage_probs[stage] = max(0.0, min(1.0, p_val))
        except (TypeError, ValueError):
            continue  # keep default
    return {
        "stage_probabilities": stage_probs,
        "quarterly_target_gbp": int(raw.get("quarterly_target_gbp")
                                       or DEFAULT_QUARTERLY_TARGET_GBP),
        "updated_at": raw.get("updated_at"),
    }


def save(updates: dict[str, Any]) -> dict[str, Any]:
    """Merge user-supplied updates over the current config. Only keys we
    recognise are persisted — anything else is ignored (defensive)."""
    current = load()
    if "stage_probabilities" in updates and isinstance(updates["stage_probabilities"], dict):
        for stage, prob in updates["stage_probabilities"].items():
            try:
                p_val = float(prob)
                current["stage_probabilities"][stage] = max(0.0, min(1.0, p_val))
            except (TypeError, ValueError):
                continue
    if "quarterly_target_gbp" in updates:
        try:
            current["quarterly_target_gbp"] = max(0, int(updates["quarterly_target_gbp"]))
        except (TypeError, ValueError):
            pass
    current["updated_at"] = _now_iso()
    with _LOCK:
        json_file_store.write_json(_path(), current)
    return current
