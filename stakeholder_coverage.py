"""Key stakeholder coverage metric (v1.0.0dd).

Computes whether the partnership team has identified + recently
engaged the critical contacts at each partner org. Lean by design:
the "key" flag is manually toggled per contact, so the metric only
counts what your team has explicitly designated as important.

Definition
----------
- A contact is a **key stakeholder** when `is_key_stakeholder=True`
  on the contact row (set via the partner contacts UI).
- A key stakeholder is **covered** when `last_touched_at` is within
  the engagement window (default 30 days).
- Coverage % = covered key stakeholders / total key stakeholders.

Excludes contacts whose `status` is `left` (they've moved on) so the
denominator stays accurate.

Public API
----------
compute(window_days=30) -> dict
    {
      "window_days":      30,
      "totals": {
        "key_total":       <int>,   # designated key stakeholders
        "covered":         <int>,   # touched within window
        "stale":           <int>,   # key but past cadence
        "never_touched":   <int>,   # key but last_touched_at is None
        "coverage_pct":    <int>,   # covered / key_total * 100
      },
      "by_partner": [
        {
          "partner_id": "braze",
          "partner_name": "Braze",
          "key_total":   <int>,
          "covered":     <int>,
          "stale":       <int>,
          "never_touched": <int>,
          "coverage_pct":  <int>,
          "stakeholders": [<contact summaries>]
        }
      ],
      "stale_contacts":    [<contact summaries>],   # action list
      "never_touched":     [<contact summaries>],
    }
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import partner_contacts_store
import partners_store


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # Tolerates trailing Z and microseconds.
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _summary(contact: dict[str, Any], partner_name: str) -> dict[str, Any]:
    """Trim a contact down to the fields the UI uses for action lists."""
    return {
        "id":              contact.get("id"),
        "name":            contact.get("name"),
        "title":           contact.get("title"),
        "email":           contact.get("email"),
        "partner_id":      contact.get("partner_id"),
        "partner_name":    partner_name,
        "last_touched_at": contact.get("last_touched_at"),
        "tier":            contact.get("tier"),
        "mr_owner":        contact.get("mr_owner"),
    }


def compute(window_days: int = 30) -> dict[str, Any]:
    """Return the full coverage payload. Caller is responsible for
    bounding window_days (server clamps).
    """
    window_days = max(1, int(window_days))
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    partners = {p.get("id"): p for p in partners_store.list_partners()}

    # Pull every contact across every partner. The list_contacts API
    # is per-partner; iterate the partner map so we touch every store
    # file exactly once.
    by_partner: list[dict[str, Any]] = []
    total_key = covered_total = stale_total = never_total = 0
    stale_action: list[dict[str, Any]] = []
    never_action: list[dict[str, Any]] = []

    for partner_id, partner in partners.items():
        contacts = partner_contacts_store.list_contacts(partner_id)
        # Exclude "left" so the denominator reflects who we could
        # actually engage today.
        key_contacts = [c for c in contacts
                        if c.get("is_key_stakeholder")
                        and (c.get("status") or "").lower() != "left"]
        if not key_contacts:
            continue
        partner_name = partner.get("name") or partner_id

        p_total = len(key_contacts)
        p_covered = 0
        p_stale = 0
        p_never = 0
        stakeholders: list[dict[str, Any]] = []
        for c in key_contacts:
            summary = _summary(c, partner_name)
            ts = _parse_iso(c.get("last_touched_at"))
            if ts is None:
                p_never += 1
                summary["coverage_status"] = "never_touched"
                never_action.append(summary)
            elif ts >= cutoff:
                p_covered += 1
                summary["coverage_status"] = "covered"
            else:
                p_stale += 1
                summary["coverage_status"] = "stale"
                stale_action.append(summary)
            stakeholders.append(summary)

        total_key += p_total
        covered_total += p_covered
        stale_total += p_stale
        never_total += p_never

        by_partner.append({
            "partner_id":     partner_id,
            "partner_name":   partner_name,
            "key_total":      p_total,
            "covered":        p_covered,
            "stale":          p_stale,
            "never_touched":  p_never,
            "coverage_pct":   int(round(p_covered / p_total * 100)) if p_total else 0,
            "stakeholders":   stakeholders,
        })

    # Sort partners: worst coverage first (so the AE sees action items
    # at the top). Tie-break alphabetically.
    by_partner.sort(key=lambda r: (r["coverage_pct"], r["partner_name"].lower()))
    # Sort the action lists by staleness (oldest first); never_touched
    # by name.
    stale_action.sort(key=lambda r: (r.get("last_touched_at") or ""))
    never_action.sort(key=lambda r: (r.get("name") or "").lower())

    coverage_pct = (int(round(covered_total / total_key * 100))
                    if total_key else 0)

    return {
        "window_days": window_days,
        "totals": {
            "key_total":     total_key,
            "covered":       covered_total,
            "stale":         stale_total,
            "never_touched": never_total,
            "coverage_pct":  coverage_pct,
        },
        "by_partner":    by_partner,
        "stale_contacts": stale_action[:50],
        "never_touched":  never_action[:50],
    }
