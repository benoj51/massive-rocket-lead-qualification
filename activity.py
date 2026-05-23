"""v1.0.0ap — Team activity feed formatter.

Reads the raw `audit.jsonl` log and converts it into a list of display
rows suitable for rendering on the Home view. The audit log captures
many low-level events (pricing previews, internal sync attempts) that
aren't user-relevant; this module filters to the subset that matters
and turns each into a short readable line with a link back to the
entity that changed.

Why a separate module
---------------------
- Keeps the event-type → summary-string mapping in one reviewable
  place, not buried in server.py.
- Pure functions, easy to unit-test without a Flask request context.
- The set of "interesting" event types is intentionally curated;
  changes belong in this file with a comment explaining the call.

The returned shape is stable so the UI can render without a schema
dance:

    {
      "ts":      "2026-05-23T19:45:00Z",
      "type":    "partner_updated",          # raw event type
      "actor":   "Ben Ojuolape",
      "summary": "renamed Braze to BRAZE Inc",
      "link":    None | { "kind": ..., "lead_id"|"partner_id": ... }
    }
"""
from __future__ import annotations

from typing import Any, Iterable

# Curated allowlist. Anything else is hidden from the feed. Order is
# not significant — this is a membership test only.
INTERESTING_EVENT_TYPES = frozenset({
    # Lead lifecycle
    "qualified",
    "lead_updated",
    "lead_rescored",
    # Calls / notes
    "call_added",
    "call_updated",
    "lead_contact_note_added",
    # Project scope
    "scope_saved",
    "scope_transition",
    # SOW
    "sow_drafted",
    # Partner lifecycle
    "partner_saved",
    "partner_updated",
    "partner_deleted",
    "partner_contact_saved",
    "partner_contact_deleted",
    "partner_contact_touched",
    "partner_contact_assigned",
    "partner_contact_unassigned",
    "partner_note_added",
    # Lead-side contacts
    "contact_saved",
    "contact_deleted",
    "contact_touched",
    "contact_set_primary",
    # Lead agencies
    "lead_agency_saved",
    "lead_agency_updated",
    "lead_agency_deleted",
})


def _short_id(value: str | None, n: int = 8) -> str:
    """Trim a UUID/page-id to its first N chars for display."""
    if not value:
        return ""
    return str(value)[:n]


def _link_for(event: dict[str, Any]) -> dict[str, Any] | None:
    """Best-effort entity link for an event. Returns None when the
    event doesn't carry enough info to navigate (e.g. settings
    changes, raw qualifier runs without a saved lead)."""
    t = event.get("type")
    pid = event.get("page_id") or event.get("lead_id")
    partner_id = event.get("partner_id")
    contact_id = event.get("contact_id")
    if t in {"lead_updated", "lead_rescored", "call_added", "call_updated",
              "lead_contact_note_added", "scope_saved", "scope_transition",
              "sow_drafted", "contact_saved", "contact_deleted",
              "contact_touched", "contact_set_primary",
              "lead_agency_saved", "lead_agency_updated",
              "lead_agency_deleted"} and pid:
        return {"kind": "lead", "lead_id": pid}
    if t in {"partner_contact_saved", "partner_contact_deleted",
              "partner_contact_touched", "partner_contact_assigned",
              "partner_contact_unassigned", "partner_note_added"} \
       and partner_id:
        link = {"kind": "partner_contact", "partner_id": partner_id}
        if contact_id:
            link["contact_id"] = contact_id
        return link
    if t in {"partner_saved", "partner_updated", "partner_deleted"} \
       and partner_id:
        return {"kind": "partner", "partner_id": partner_id}
    return None


def _summary_for(event: dict[str, Any], *,
                  partner_names: dict[str, str] | None = None,
                  lead_names: dict[str, str] | None = None) -> str:
    """Compose a human-readable summary string. Falls back to a
    type-only message if the event is malformed."""
    t = event.get("type") or "unknown"
    partner_names = partner_names or {}
    lead_names = lead_names or {}
    pid = event.get("page_id") or event.get("lead_id")
    partner_id = event.get("partner_id")
    pname = partner_names.get(partner_id, partner_id) if partner_id else ""
    lname = (lead_names.get(pid) or event.get("company") or _short_id(pid)) if pid else ""

    if t == "qualified":
        company = event.get("company") or lname or "(unknown)"
        score = event.get("score")
        status = event.get("status") or ""
        return f"qualified {company}" + (f" — {score} ({status})" if score else "")
    if t == "lead_updated":
        fields = event.get("fields") or []
        if "company" in fields:
            return f"renamed lead → {lname}"
        if "owner" in fields:
            return f"reassigned {lname}"
        if "status" in fields:
            return f"updated status on {lname}"
        return f"updated {lname}" + (f" ({len(fields)} field{'s' if len(fields) != 1 else ''})" if fields else "")
    if t == "lead_rescored":
        score = event.get("new_score")
        return f"re-scored {lname}" + (f" → {score}/10" if score is not None else "")
    if t == "call_added":
        kind = event.get("call_type") or "call"
        return f"logged {kind} on {lname}"
    if t == "call_updated":
        return f"edited a call on {lname}"
    if t == "lead_contact_note_added":
        return f"added a contact note on {lname}"
    if t == "scope_saved":
        return f"saved project scope for {event.get('company') or lname}"
    if t == "scope_transition":
        new = event.get("new_status") or event.get("status") or ""
        return f"moved {lname} scope to {new}" if new else f"moved {lname} scope"
    if t == "sow_drafted":
        v = event.get("version") or ""
        return f"drafted SOW {('v'+str(v)) if v else ''} for {lname}".strip()
    if t == "partner_saved":
        return f"added partner {event.get('name') or pname}"
    if t == "partner_updated":
        fields = event.get("fields") or []
        if "name" in fields:
            return f"renamed partner → {pname}"
        return f"updated partner {pname}" + (f" ({len(fields)} field{'s' if len(fields) != 1 else ''})" if fields else "")
    if t == "partner_deleted":
        return f"deleted partner {pname}"
    if t == "partner_contact_saved":
        cname = event.get("name") or "(contact)"
        return f"saved {cname} ({pname})"
    if t == "partner_contact_deleted":
        return f"removed a contact from {pname}"
    if t == "partner_contact_touched":
        return f"marked a contact at {pname} as touched"
    if t == "partner_contact_assigned":
        to = event.get("assigned_to") or "(someone)"
        return f"assigned a partner contact at {pname} to {to}"
    if t == "partner_contact_unassigned":
        return f"unassigned a partner contact at {pname}"
    if t == "partner_note_added":
        return f"noted on a contact at {pname}"
    if t == "contact_saved":
        return f"saved a lead contact on {lname}"
    if t == "contact_deleted":
        return f"removed a lead contact from {lname}"
    if t == "contact_touched":
        return f"touched a lead contact on {lname}"
    if t == "contact_set_primary":
        return f"set a primary contact on {lname}"
    if t == "lead_agency_saved":
        return f"saved an agency on {lname}"
    if t == "lead_agency_updated":
        return f"updated an agency on {lname}"
    if t == "lead_agency_deleted":
        return f"removed an agency from {lname}"
    # Allowlisted but un-described — surface the raw type so we know
    # to add it here later.
    return f"({t})"


def format_events(events: Iterable[dict[str, Any]], *,
                    partner_names: dict[str, str] | None = None,
                    lead_names: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Convert a stream of raw audit events into display rows. Filters
    out anything not in INTERESTING_EVENT_TYPES. The caller is
    responsible for sort order — this function preserves input order."""
    out: list[dict[str, Any]] = []
    for e in events:
        t = e.get("type")
        if t not in INTERESTING_EVENT_TYPES:
            continue
        out.append({
            "ts":      e.get("ts"),
            "type":    t,
            "actor":   e.get("actor") or "(unknown)",
            "summary": _summary_for(e, partner_names=partner_names,
                                       lead_names=lead_names),
            "link":    _link_for(e),
        })
    return out
