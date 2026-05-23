"""v1.0.0at — Account engagement score.

ICP score (existing) tells you how good a lead is intrinsically.
Engagement score (new) tells you how well we're actually working it.
Same 0–100 scale so AEs can read both at a glance.

Why a separate module
---------------------
The existing forecast/scoring modules deal with intrinsic lead quality
(revenue, employees, tech-stack fit). This is operational: are we
touching the right people, often enough, with the right depth? Different
inputs, different consumer (AE attention allocation, not deal-stage
routing), so a separate module keeps both surfaces readable.

Formula (deliberately simple — explainable on a single screen)
---------------------------------------------------------------
Five signals sum to 100, capped at [0, 100]:

  1. COVERAGE         (max 30 pts) — % of active contacts touched at
                                      all (0 → 0pts, 100% → 30pts)
  2. RECENCY          (max 30 pts) — days since most recent touch
                                      0d=30, 7d=25, 14d=20, 30d=15,
                                      60d=8, 90d+=0
  3. ACTIVITY VOLUME  (max 25 pts) — count of notes + calls in last 30d
                                      0=0, 5=12, 10+=25
  4. OVERDUE PENALTY  (max -15 pts) — -5 per overdue contact, capped
  5. KEY CONTACT      (max 10 pts) — +10 if any is_primary contact has
                                      been touched in the last 30 days

Bands (gives the UI a colour without re-deciding):
  ≥75  → "strong"   (green)
  ≥50  → "warm"     (yellow)
  ≥25  → "weak"     (orange)
  <25  → "cold"     (red)

A `signals` block is returned alongside the score so the UI can render
"why this number" tooltips without recomputing.

The scorer is a pure function: it takes pre-fetched contacts +
event timestamps + a today_iso, no I/O. The caller is responsible
for the data pull (see server.api_engagement_score). This keeps the
unit tests fast and lets us simulate the calendar.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable


def _days_between(a_iso: str, b_iso: str) -> int | None:
    """Whole-day count from `a_iso` to `b_iso` (b - a). Returns None if
    either input is unparseable. Both expected in our ISO-Z format."""
    try:
        a = datetime.fromisoformat(a_iso.replace("Z", "+00:00"))
        b = datetime.fromisoformat(b_iso.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return (b.date() - a.date()).days


def compute_engagement_score(
    *,
    contacts: list[dict[str, Any]],
    recent_event_isos: Iterable[str] = (),
    today_iso: str | None = None,
) -> dict[str, Any]:
    """Score a single account on 0–100.

    Args
    ----
    contacts:
        List of contact dicts, each with at least:
          - id, name, status, is_primary
          - last_touched_at  (iso8601 | None)
          - overdue          (bool, from contacts_store.annotate_touch_state)
    recent_event_isos:
        ISO timestamps of every engagement event (notes + calls) for
        the account. Used for the activity-volume signal — we count
        how many fall within the last 30 days of `today_iso`.
    today_iso:
        ISO date (yyyy-mm-dd) treated as "today". Defaults to UTC now.
        Injectable so tests can drive the calendar deterministically.

    Returns
    -------
    {
      "score":   int 0..100,
      "band":    "strong" | "warm" | "weak" | "cold",
      "signals": {
        "coverage_pct":        int 0..100,
        "coverage_points":     int 0..30,
        "days_since_touch":    int | None,
        "recency_points":      int 0..30,
        "events_30d":          int,
        "activity_points":     int 0..25,
        "overdue_count":       int,
        "overdue_penalty":     int -15..0,
        "key_touched_30d":     bool,
        "key_bonus":           int 0..10,
        "active_contacts":     int,
        "considered_contacts": int,
      },
    }
    """
    if today_iso is None:
        today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_full = today_iso + "T00:00:00Z" if "T" not in today_iso else today_iso

    # Only score against active contacts — left/dormant contacts shouldn't
    # drag the coverage % down (they're not part of the buying group right now).
    active = [c for c in contacts if (c.get("status") or "active") == "active"]

    # --- 1. Coverage ---
    if not active:
        coverage_pct = 0
    else:
        touched = sum(1 for c in active if c.get("last_touched_at"))
        coverage_pct = round(100 * touched / len(active))
    coverage_points = round(30 * coverage_pct / 100)

    # --- 2. Recency ---
    latest_touch_iso: str | None = None
    for c in active:
        ts = c.get("last_touched_at")
        if ts and (latest_touch_iso is None or ts > latest_touch_iso):
            latest_touch_iso = ts
    days_since_touch = _days_between(latest_touch_iso, today_full) if latest_touch_iso else None
    if days_since_touch is None:
        recency_points = 0
    elif days_since_touch <= 0:
        recency_points = 30
    elif days_since_touch <= 7:
        recency_points = 25
    elif days_since_touch <= 14:
        recency_points = 20
    elif days_since_touch <= 30:
        recency_points = 15
    elif days_since_touch <= 60:
        recency_points = 8
    else:
        recency_points = 0

    # --- 3. Activity volume (notes + calls in last 30 days) ---
    events_30d = 0
    for ev_iso in recent_event_isos:
        d = _days_between(ev_iso, today_full)
        if d is not None and 0 <= d <= 30:
            events_30d += 1
    # 0 events → 0 pts; ramps to 25 at 10+ events. Linear with cap.
    activity_points = min(25, round(events_30d * 2.5))

    # --- 4. Overdue penalty ---
    overdue_count = sum(1 for c in active if c.get("overdue"))
    overdue_penalty = max(-15, -5 * overdue_count)

    # --- 5. Key contact bonus ---
    key_touched_30d = False
    for c in active:
        if not c.get("is_primary"):
            continue
        ts = c.get("last_touched_at")
        if not ts:
            continue
        d = _days_between(ts, today_full)
        if d is not None and 0 <= d <= 30:
            key_touched_30d = True
            break
    key_bonus = 10 if key_touched_30d else 0

    raw = (coverage_points + recency_points + activity_points
           + overdue_penalty + key_bonus)
    score = max(0, min(100, raw))

    if score >= 75:
        band = "strong"
    elif score >= 50:
        band = "warm"
    elif score >= 25:
        band = "weak"
    else:
        band = "cold"

    return {
        "score": int(score),
        "band":  band,
        "signals": {
            "coverage_pct":        coverage_pct,
            "coverage_points":     coverage_points,
            "days_since_touch":    days_since_touch,
            "recency_points":      recency_points,
            "events_30d":          events_30d,
            "activity_points":     activity_points,
            "overdue_count":       overdue_count,
            "overdue_penalty":     overdue_penalty,
            "key_touched_30d":     key_touched_30d,
            "key_bonus":           key_bonus,
            "active_contacts":     len(active),
            "considered_contacts": len(contacts),
        },
    }
