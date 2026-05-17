"""
BANT-S health rollup (v0.10.0j).

Derives a 5-tile health view (Budget / Authority / Need / Timeline / Scope)
from existing MEDDPICC `health` flags + scope state. Single source of
truth: the AE only ever touches MEDDPICC RAGs + scope criteria; the
BANT strip is computed.

Mapping decided in design review:
  Budget    → meddpicc.budget_confirmed.health
  Authority → meddpicc.economic_buyer.health
  Need      → worst of (identify_pain.health, metrics.health)
  Timeline  → meddpicc.decision_process.health
  Scope     → derived from scope state (validated streams / draft / empty)

Health values: "red" | "amber" | "green" | None.
None means "not assessed" and renders as a grey/unknown tile.

This module is pure: no I/O, no DB. Easy to unit-test.
"""
from __future__ import annotations

from typing import Any

# Worst-of comparator: when multiple signals contribute to a single tile,
# the most concerning colour wins. Order: red > amber > green > None.
_HEALTH_RANK = {"red": 3, "amber": 2, "green": 1, None: 0}


def _worst(*signals: str | None) -> str | None:
    """Return the worst (most concerning) health value across signals."""
    best = None
    for s in signals:
        if s not in ("red", "amber", "green"):
            continue
        if _HEALTH_RANK[s] > _HEALTH_RANK[best]:
            best = s
    return best


def _meddpicc_health(meddpicc: dict | None, key: str) -> str | None:
    """Extract the health value for a single MEDDPICC criterion."""
    if not meddpicc:
        return None
    entry = meddpicc.get(key) or {}
    h = entry.get("health")
    return h if h in ("red", "amber", "green") else None


def _meddpicc_value(meddpicc: dict | None, key: str) -> str:
    """Extract the captured value for a MEDDPICC criterion (for tile captions)."""
    if not meddpicc:
        return ""
    entry = meddpicc.get(key) or {}
    return str(entry.get("value") or "").strip()


def _scope_health(scope_state: dict | None) -> tuple[str | None, str]:
    """Compute (health, caption) for the Scope tile from scope_state.

    scope_state shape (flexible — we read what's there):
      {
        "streams": [{"project_type": "crm_build", "validation_status": "validated"}, ...],
        "project_scope": "<free text>",
      }

    Rules:
      - No streams and no project_scope text → red, "Not defined"
      - Streams exist, none validated → amber, "<N> stream(s) drafted"
      - At least one validated stream → green, "<N> stream(s), validated"
      - Free text only → amber, "Scope drafted (free text)"
    """
    # None means "not loaded at all" — return unknown. An empty dict {} means
    # "we looked and there's nothing yet" — that's a real red signal.
    if scope_state is None:
        return None, "Not assessed"
    streams = scope_state.get("streams") or []
    project_scope_text = (scope_state.get("project_scope") or "").strip()
    if not streams and not project_scope_text:
        return "red", "Not defined"
    if not streams and project_scope_text:
        return "amber", "Scope drafted (free text)"
    validated = sum(1 for s in streams if (s.get("validation_status") in ("validated", "qualified")))
    n = len(streams)
    if validated:
        return "green", f"{validated}/{n} stream{'s' if n > 1 else ''} validated"
    return "amber", f"{n} stream{'s' if n > 1 else ''} drafted"


# ---------- public API ----------

def derive_bant_health(meddpicc: dict | None,
                       scope_state: dict | None = None) -> dict[str, dict[str, Any]]:
    """Return a dict of 5 BANT-S tiles, each with health + caption.

    Output shape:
      {
        "budget":    {"health": "red"|"amber"|"green"|None, "caption": "<short>"},
        "authority": {...},
        "need":      {...},
        "timeline":  {...},
        "scope":     {...},
      }
    """
    # Budget — from budget_confirmed
    budget_h = _meddpicc_health(meddpicc, "budget_confirmed")
    budget_v = _meddpicc_value(meddpicc, "budget_confirmed")
    budget_caption = budget_v[:60] if budget_v else _default_caption(budget_h, "budget")

    # Authority — from economic_buyer
    auth_h = _meddpicc_health(meddpicc, "economic_buyer")
    auth_v = _meddpicc_value(meddpicc, "economic_buyer")
    auth_caption = auth_v[:60] if auth_v else _default_caption(auth_h, "authority")

    # Need — worst of identify_pain + metrics
    pain_h = _meddpicc_health(meddpicc, "identify_pain")
    metrics_h = _meddpicc_health(meddpicc, "metrics")
    need_h = _worst(pain_h, metrics_h)
    pain_v = _meddpicc_value(meddpicc, "identify_pain")
    need_caption = pain_v[:60] if pain_v else _default_caption(need_h, "need")

    # Timeline — from decision_process
    time_h = _meddpicc_health(meddpicc, "decision_process")
    time_v = _meddpicc_value(meddpicc, "decision_process")
    time_caption = time_v[:60] if time_v else _default_caption(time_h, "timeline")

    # Scope — derived from scope state
    scope_h, scope_caption = _scope_health(scope_state)

    return {
        "budget":    {"health": budget_h, "caption": budget_caption},
        "authority": {"health": auth_h, "caption": auth_caption},
        "need":      {"health": need_h, "caption": need_caption},
        "timeline":  {"health": time_h, "caption": time_caption},
        "scope":     {"health": scope_h, "caption": scope_caption},
    }


def _default_caption(health: str | None, tile: str) -> str:
    """Caption when there's no captured value yet — use the health colour to hint."""
    if health == "green":
        return "Strong"
    if health == "amber":
        return "Needs work"
    if health == "red":
        return "Concern"
    return "Not assessed"


def overall_score(bant: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Quick aggregate over a derived BANT dict: counts + worst colour + summary string.

    Useful for pipeline-row badges or filter chips later.
    """
    counts = {"red": 0, "amber": 0, "green": 0, "none": 0}
    for tile in bant.values():
        h = tile.get("health")
        if h in counts:
            counts[h] += 1
        else:
            counts["none"] += 1
    worst = "green"
    if counts["red"]:
        worst = "red"
    elif counts["amber"]:
        worst = "amber"
    elif counts["green"] == 0:
        worst = None
    return {"counts": counts, "worst": worst}
