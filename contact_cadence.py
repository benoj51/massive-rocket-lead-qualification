"""v1.0.0cg — shared touch-cadence logic.

The duplication audit caught `contacts_store.annotate_touch_state`
and `partner_contacts_store.annotate_touch_state` as byte-identical.
The contacts-store version literally had the comment "Mirror of
partner_contacts_store.annotate_touch_state." Cadence default
changed once already and the fix had to land in both places.

This module is the one place that knows what "overdue" means.

Public API
----------
    parse_iso(s)                              -> tz-aware datetime | None
    annotate_touch_state(contact, default_cadence=30) -> contact (mutated)
    next_touch_due(contact, default_cadence=30) -> ISO-Z string | None

`annotate_touch_state` mutates the supplied dict in place and also
returns it (chainable). Adds:
    next_touch_due:    iso when the next outreach is due
    days_since_touch:  int days since last real touch (or None)
    days_until_due:    int days until/past due (negative = overdue)
    overdue:           bool
    is_due_soon:       bool — within 7 days of due
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def parse_iso(s: str | None) -> datetime | None:
    """Parse our ISO-Z timestamps back to a tz-aware datetime."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def annotate_touch_state(contact: dict[str, Any],
                          *, default_cadence: int = 30) -> dict[str, Any]:
    """Mutate `contact` with derived touch fields. Returns the same
    dict for chaining.

    Behaviour (matches the original implementations exactly):
    - cadence_days falls back to `default_cadence` (30) when missing
    - baseline = last_touched_at if set, else added_at
    - no baseline → all fields zeroed / null; overdue=False
    - days_since_touch is None when last_touched_at is null (we
      can't claim a touch happened if it never did)
    """
    cadence = int(contact.get("cadence_days") or default_cadence)
    last = parse_iso(contact.get("last_touched_at"))
    baseline = last or parse_iso(contact.get("added_at"))
    if baseline is None:
        contact["next_touch_due"] = None
        contact["days_since_touch"] = None
        contact["days_until_due"] = 0
        contact["overdue"] = False
        contact["is_due_soon"] = False
        return contact
    now = datetime.now(timezone.utc)
    days_since = (now - baseline).days
    due_at = baseline + timedelta(days=cadence)
    days_until_due = (due_at - now).days
    contact["next_touch_due"] = due_at.isoformat(
        timespec="seconds").replace("+00:00", "Z")
    contact["days_since_touch"] = days_since if last else None
    contact["days_until_due"] = days_until_due
    contact["overdue"] = days_until_due < 0
    contact["is_due_soon"] = 0 <= days_until_due <= 7
    return contact


def next_touch_due(contact: dict[str, Any],
                    *, default_cadence: int = 30) -> str | None:
    """Convenience: just compute the next-due ISO string without
    mutating the contact."""
    cadence = int(contact.get("cadence_days") or default_cadence)
    baseline = parse_iso(contact.get("last_touched_at")) \
        or parse_iso(contact.get("added_at"))
    if baseline is None:
        return None
    return (baseline + timedelta(days=cadence)).isoformat(
        timespec="seconds").replace("+00:00", "Z")
