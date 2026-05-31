"""v1.0.0bc — Daily engagement-score snapshots per lead.

A single engagement score (v1.0.0at) tells you the state today. A
sequence of daily snapshots tells you whether the account is going
up or down — and we can notify the owner when it crosses a band
downward ("Acme dropped from warm to cold").

Design
------
- One JSON file per lead slug.
- Append-only by day: at most ONE snapshot per (lead, YYYY-MM-DD)
  date. Re-running the scorer twice on the same day updates the
  existing row in place (so the snapshot represents end-of-day
  state, not first-of-day).
- Ring-buffered at 30 entries per lead — engagement trends past a
  month aren't actionable in our workflow.

Shape
-----
    {
      "date":           "2026-05-23",
      "ts":             "2026-05-23T19:45:00Z",  # when we recorded it
      "score":          75,
      "band":           "strong",
      "contacts_total": 8,
      "contacts_engaged": 5,
      "events_30d":     12,
    }

API
---
    record(lead_id, score_payload, *, today_iso=None) -> dict
        Idempotent insert-or-update for today's snapshot.

    history(lead_id, *, limit=30) -> list[dict]
        All snapshots for the lead, newest-first.

    delta(lead_id, *, days_ago=7) -> dict | None
        Score now vs N days ago. Returns
        {now, then, delta, then_band, now_band, direction} or None
        if there's no comparable history.

    previous_snapshot(lead_id, *, before_date) -> dict | None
        The snapshot immediately before `before_date`. Used by the
        notification trigger to compare today's band against the
        most recent prior snapshot (which may not be exactly
        yesterday — accounts aren't scored every day).
"""
from __future__ import annotations

import json
import json_file_store
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DIR = Path(__file__).parent / "cache" / "engagement_snapshots"
_LOCK = threading.Lock()
_RING_CAP = 30  # per-lead cap


class EngagementSnapshotsStoreError(RuntimeError):
    pass


def _store_dir() -> Path:
    override = os.environ.get("ENGAGEMENT_SNAPSHOTS_STORE_DIR")
    d = Path(override) if override else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slugify(value: str) -> str:
    if not value:
        return "unknown"
    s = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return s.strip("-") or "unknown"


def _path(lead_id: str) -> Path:
    return _store_dir() / f"{_slugify(lead_id)}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_raw(lead_id: str) -> list[dict[str, Any]]:
    p = _path(lead_id)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
        if not isinstance(data, list):
            return []
        return data
    except (OSError, ValueError):
        return []


def _save_raw(lead_id: str, rows: list[dict[str, Any]]) -> None:
    p = _path(lead_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    json_file_store.write_json(p, rows)


def record(lead_id: str, score_payload: dict[str, Any], *,
            today_iso: str | None = None) -> dict[str, Any]:
    """Insert-or-update today's snapshot for `lead_id`.

    `score_payload` is the dict from engagement.compute_engagement_score
    (or _compute_engagement_for_lead) — at minimum {score, band, signals}.

    `today_iso` is injectable so tests can simulate the calendar.

    Returns the snapshot row that ended up in the file. Idempotent on
    same-day calls: a second call today UPDATES the existing row in
    place, doesn't append.
    """
    if not lead_id:
        raise EngagementSnapshotsStoreError("lead_id required")
    if not isinstance(score_payload, dict):
        raise EngagementSnapshotsStoreError("score_payload must be a dict")
    today = today_iso or _today()
    sig = score_payload.get("signals") or {}
    snapshot = {
        "date":            today,
        "ts":              _now(),
        "score":           int(score_payload.get("score") or 0),
        "band":            score_payload.get("band") or "cold",
        "contacts_total":  sig.get("considered_contacts", 0),
        "contacts_engaged": sig.get("active_contacts", 0)
                              and round(sig.get("active_contacts", 0)
                                          * (sig.get("coverage_pct", 0) / 100))
                              or 0,
        "events_30d":      sig.get("events_30d", 0),
    }
    with _LOCK:
        rows = _load_raw(lead_id)
        # In-place update if today's snapshot already exists.
        replaced = False
        for i, r in enumerate(rows):
            if r.get("date") == today:
                rows[i] = snapshot
                replaced = True
                break
        if not replaced:
            rows.append(snapshot)
        # Sort by date ascending (file order); cap at _RING_CAP newest.
        rows.sort(key=lambda r: r.get("date") or "")
        if len(rows) > _RING_CAP:
            rows = rows[-_RING_CAP:]
        _save_raw(lead_id, rows)
    return snapshot


def history(lead_id: str, *, limit: int = 30) -> list[dict[str, Any]]:
    """All snapshots, newest first. Bounded by `limit`."""
    if not lead_id:
        return []
    with _LOCK:
        rows = _load_raw(lead_id)
    rows.sort(key=lambda r: r.get("date") or "", reverse=True)
    if limit and limit > 0:
        rows = rows[:limit]
    return rows


def previous_snapshot(lead_id: str, *,
                       before_date: str) -> dict[str, Any] | None:
    """The most-recent snapshot dated strictly before `before_date`.

    Used by the band-drop notification: compare today's band against
    the band we last saw on a different day. Returns None if there's
    no prior history.
    """
    if not lead_id:
        return None
    with _LOCK:
        rows = _load_raw(lead_id)
    prev = [r for r in rows if r.get("date") and r["date"] < before_date]
    if not prev:
        return None
    prev.sort(key=lambda r: r["date"], reverse=True)
    return prev[0]


def delta(lead_id: str, *, days_ago: int = 7) -> dict[str, Any] | None:
    """Compute a score delta vs ~N days ago.

    "~N" because accounts aren't scored every day — we find the snapshot
    closest to N days back (preferring on-or-before that date), then
    compare. Returns None if there's nothing to compare against
    (single snapshot or no history).

    Shape:
      {
        now:       int (today's score),
        then:      int (score N days ago),
        delta:     int (now - then),
        now_band:  str,
        then_band: str,
        direction: "up" | "down" | "flat",
        days_compared: int (actual gap in days),
      }
    """
    if not lead_id or days_ago < 1:
        return None
    with _LOCK:
        rows = _load_raw(lead_id)
    if len(rows) < 2:
        return None
    rows.sort(key=lambda r: r.get("date") or "", reverse=True)
    now = rows[0]
    # Find a snapshot N days back (or the next-oldest if not exact).
    try:
        now_date = datetime.fromisoformat(now["date"])
    except (ValueError, TypeError):
        return None
    target_date = now_date.replace(day=now_date.day)  # immutable copy
    from datetime import timedelta
    target = (now_date - timedelta(days=days_ago)).date().isoformat()
    # Walk from oldest first, take the closest to `target` not after `now`.
    then = None
    for r in rows[1:]:
        d = r.get("date")
        if not d:
            continue
        if d <= target:
            then = r
            break
    if then is None:
        # Not enough history back — fall back to the oldest available
        # snapshot that isn't `now`.
        then = rows[-1] if rows[-1].get("date") != now.get("date") else None
    if then is None:
        return None
    diff = (int(now.get("score") or 0) - int(then.get("score") or 0))
    direction = "up" if diff > 0 else ("down" if diff < 0 else "flat")
    try:
        then_date = datetime.fromisoformat(then["date"])
        days_compared = (now_date - then_date).days
    except (ValueError, TypeError):
        days_compared = days_ago
    return {
        "now":           int(now.get("score") or 0),
        "then":          int(then.get("score") or 0),
        "delta":         diff,
        "now_band":      now.get("band"),
        "then_band":     then.get("band"),
        "direction":     direction,
        "days_compared": days_compared,
    }


# Band ordering used for downgrade detection.
_BAND_RANK = {"strong": 3, "warm": 2, "weak": 1, "cold": 0}


def band_downgraded(prev_band: str | None, now_band: str | None) -> bool:
    """True iff `now_band` is strictly worse than `prev_band` on the
    {strong > warm > weak > cold} ordering. Unknown bands compare as
    equal (returns False) so a future band insertion doesn't spam
    notifications retroactively."""
    if not prev_band or not now_band:
        return False
    p = _BAND_RANK.get(prev_band)
    n = _BAND_RANK.get(now_band)
    if p is None or n is None:
        return False
    return n < p
