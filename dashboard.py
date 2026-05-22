"""
Team activity dashboard (v1.0.0t).

Aggregates partnership + sales activity across MR owners + partners
over a configurable time window. Used by the Dashboard view in the
UI — manager surface so Ben can scan team workload + coverage in
one pass.

Attribution model: by `mr_owner` on partner contacts and `owner` on
leads. Note author (X-Actor header) is unreliable today — most notes
end up authored as "anon" — so we attribute activity to the
*current* MR owner of the contact/lead. Semantic match for a manager:
"how much work has Daniel done" means "touches on Daniel's book",
which follows the contact even if the typing was done by someone
else (Ben covering, intern logging on behalf, etc.).

Time window: ISO date filtering applied to `created_at`. We don't try
to slice by exact hours — daily granularity is what a manager scans.

Pure logic — no Flask, no Notion. Takes data already loaded from
stores + an optional pipeline-rows iterable.
"""
from __future__ import annotations

import collections
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import calls_store
import lead_agencies_store  # noqa: F401  (kept for future "agency activity" tile)
import mr_owners
import partner_contacts_store
import partner_notes_store
import partners_store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: str | None) -> datetime | None:
    """Tolerant ISO parse — handles both Z-suffixed + offset-formatted
    timestamps the various stores emit."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _in_window(created_at: str | None, since: datetime) -> bool:
    dt = _parse_iso(created_at)
    return dt is not None and dt >= since


def _empty_owner_bucket() -> dict[str, Any]:
    return {
        "touches":              0,    # all activity types combined
        "by_type":              collections.Counter(),
        "partner_contacts":     0,    # how many contacts this owner is mr_owner of
        "partner_contacts_overdue": 0,
        "leads_owned":          0,
        "leads_active":         0,    # excluding Disqualified / Closed Lost / On Hold
    }


def _empty_partner_bucket() -> dict[str, Any]:
    return {
        "touches":          0,
        "by_type":          collections.Counter(),
        "contacts":         0,
        "contacts_overdue": 0,
        "contacts_never_touched": 0,
        # Counted separately because a lead can be "sourced_for" multiple
        # partners — we credit each.
        "leads_sourced":    0,
    }


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

_EXCLUDED_LEAD_STATUSES = {"Disqualified", "On Hold", "Closed Lost"}


def build_dashboard(
    *,
    window_days: int = 7,
    owner_filter: str | None = None,
    pipeline_rows: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the dashboard payload.

    window_days: how far back to count touches (default 7).
    owner_filter: if set, scope the totals to a single MR owner.
    pipeline_rows: list of lead dicts (from `NotionSync.list_pipeline`).
        Optional — passed in so the server endpoint can fetch once + reuse.
        Without it we just skip lead-side aggregations.

    Returns:
        {
          "window_days": 7,
          "since": ISO,
          "generated_at": ISO,
          "owner_filter": str | None,

          # KPIs
          "totals": {
            "touches": int, "partner_notes": int, "lead_calls": int,
            "new_leads": int, "by_type": {"call": n, "email": n, ...},
            "cadence_compliance_pct": float,
          },
          "coverage": {
            "active_contacts": int, "overdue": int, "never_touched": int,
            "within_cadence": int, "compliance_pct": float,
          },

          # Per-MR-owner table
          "by_owner": [
            {"name": "...", "role": "...", "region": "...",
             "touches": int, "by_type": {...},
             "partner_contacts": int, "partner_contacts_overdue": int,
             "leads_owned": int, "leads_active": int}, ...
          ],

          # Per-partner table
          "by_partner": [
            {"name": "Braze", "id": "braze",
             "touches": int, "by_type": {...},
             "contacts": int, "contacts_overdue": int,
             "contacts_never_touched": int, "leads_sourced": int}, ...
          ],

          # Quick stats
          "note_types_seen": list[str],
        }
    """
    now = _now()
    since = now - timedelta(days=window_days)

    # ── Walk all partner contacts to collect their notes + cadence state ──
    all_contacts = partner_contacts_store.list_all_contacts()
    # Annotate touch state so we know overdue + never_touched flags
    annotated_contacts = [
        partner_contacts_store.annotate_touch_state(dict(c)) for c in all_contacts
    ]
    if owner_filter:
        annotated_contacts = [
            c for c in annotated_contacts
            if (c.get("mr_owner") or "").lower() == owner_filter.lower()
        ]

    # ── Pull partner records once so we can resolve partner_id → name ──
    partners_list = partners_store.list_partners()
    partners_by_id = {p["id"]: p for p in partners_list}

    # ── Build the per-owner + per-partner accumulators ──
    by_owner: dict[str, dict[str, Any]] = {}
    by_partner: dict[str, dict[str, Any]] = {
        p["id"]: _empty_partner_bucket() for p in partners_list
    }
    for pid, bucket in by_partner.items():
        bucket["name"] = partners_by_id[pid].get("name") or pid
        bucket["id"]   = pid

    # ── Seed owner buckets with the full MR roster so empty owners
    #     still appear in the table (manager can see who's NOT active) ──
    for owner in mr_owners.list_owners(active_only=True):
        if owner_filter and owner["name"].lower() != owner_filter.lower():
            continue
        by_owner[owner["name"]] = _empty_owner_bucket()
        by_owner[owner["name"]]["name"]   = owner["name"]
        by_owner[owner["name"]]["role"]   = owner["role"]
        by_owner[owner["name"]]["region"] = owner["region"]

    # ── Accumulate partner-contact-level stats ──
    note_types_seen: set[str] = set()
    coverage = {
        "active_contacts": 0,
        "overdue":         0,
        "never_touched":   0,
        "within_cadence":  0,
    }

    partner_notes_total = 0
    partner_notes_by_type: collections.Counter = collections.Counter()

    for contact in annotated_contacts:
        pid    = contact.get("partner_id")
        cid    = contact.get("id")
        owner  = contact.get("mr_owner") or ""
        status = contact.get("status") or "active"
        if status != "active":
            continue  # dormant / left contacts don't count toward coverage

        # Coverage
        coverage["active_contacts"] += 1
        if contact.get("overdue"):
            coverage["overdue"] += 1
        else:
            coverage["within_cadence"] += 1
        if not contact.get("last_touched_at"):
            coverage["never_touched"] += 1

        # Per-owner partner-contact counts
        if owner and owner in by_owner:
            by_owner[owner]["partner_contacts"] += 1
            if contact.get("overdue"):
                by_owner[owner]["partner_contacts_overdue"] += 1

        # Per-partner contact counts
        if pid and pid in by_partner:
            by_partner[pid]["contacts"] += 1
            if contact.get("overdue"):
                by_partner[pid]["contacts_overdue"] += 1
            if not contact.get("last_touched_at"):
                by_partner[pid]["contacts_never_touched"] += 1

        # Notes inside the window
        if not (pid and cid):
            continue
        try:
            notes = partner_notes_store.list_notes(pid, cid)
        except Exception:
            notes = []
        for n in notes:
            if not _in_window(n.get("created_at"), since):
                continue
            ntype = (n.get("type") or "other").lower()
            note_types_seen.add(ntype)
            partner_notes_total += 1
            partner_notes_by_type[ntype] += 1
            if owner and owner in by_owner:
                by_owner[owner]["touches"] += 1
                by_owner[owner]["by_type"][ntype] += 1
            if pid in by_partner:
                by_partner[pid]["touches"] += 1
                by_partner[pid]["by_type"][ntype] += 1

    # ── Lead-side calls within the window ──
    lead_calls_total = 0
    lead_calls_by_type: collections.Counter = collections.Counter()
    new_leads_total = 0

    if pipeline_rows:
        for lead in pipeline_rows:
            lead_id = lead.get("id")
            owner   = lead.get("owner") or ""
            if owner_filter and owner.lower() != owner_filter.lower():
                continue

            # Lead-level counts (owner table)
            if owner and owner in by_owner:
                by_owner[owner]["leads_owned"] += 1
                if (lead.get("status") or "") not in _EXCLUDED_LEAD_STATUSES:
                    by_owner[owner]["leads_active"] += 1

            # Partner-level sourcing credit
            for partner_name in (lead.get("sourced_for_partners") or []):
                # Match by name OR by slug — partners_store keys are slugs.
                target_id = None
                for p in partners_list:
                    if p.get("name", "").lower() == partner_name.lower():
                        target_id = p["id"]; break
                if target_id and target_id in by_partner:
                    by_partner[target_id]["leads_sourced"] += 1

            # New leads sourced inside the window
            if _in_window(lead.get("last_edited") or lead.get("created"), since):
                # Best-effort heuristic — Notion exposes last_edited; we
                # don't have a clean "first_seen". Until we add a
                # first_seen field this counts "recently touched leads"
                # which is close-enough for the dashboard.
                new_leads_total += 1

            # Lead-side calls
            if not lead_id:
                continue
            try:
                calls = calls_store.list_calls(lead_id)
            except Exception:
                calls = []
            for c in calls:
                if not _in_window(c.get("created_at"), since):
                    continue
                ctype = (c.get("type") or "call").lower()
                note_types_seen.add(ctype)
                lead_calls_total += 1
                lead_calls_by_type[ctype] += 1
                if owner and owner in by_owner:
                    by_owner[owner]["touches"] += 1
                    by_owner[owner]["by_type"][ctype] += 1

    # ── Coverage compliance % ──
    if coverage["active_contacts"] > 0:
        coverage["compliance_pct"] = round(
            100.0 * coverage["within_cadence"] / coverage["active_contacts"], 1,
        )
    else:
        coverage["compliance_pct"] = 0.0

    # ── Stitch totals ──
    total_by_type: collections.Counter = collections.Counter()
    total_by_type.update(partner_notes_by_type)
    total_by_type.update(lead_calls_by_type)

    totals = {
        "touches":        partner_notes_total + lead_calls_total,
        "partner_notes":  partner_notes_total,
        "lead_calls":     lead_calls_total,
        "new_leads":      new_leads_total,
        "by_type":        dict(total_by_type),
        "cadence_compliance_pct": coverage["compliance_pct"],
    }

    # ── Convert Counters to plain dicts for JSON ──
    def _bucket_to_dict(b: dict[str, Any]) -> dict[str, Any]:
        out = dict(b)
        if isinstance(out.get("by_type"), collections.Counter):
            out["by_type"] = dict(out["by_type"])
        return out

    by_owner_list = sorted(
        [_bucket_to_dict(b) for b in by_owner.values()],
        key=lambda r: r["touches"], reverse=True,
    )
    by_partner_list = sorted(
        [_bucket_to_dict(b) for b in by_partner.values()],
        key=lambda r: r["touches"], reverse=True,
    )

    return {
        "window_days":  window_days,
        "since":        since.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "generated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "owner_filter": owner_filter,
        "totals":       totals,
        "coverage":     coverage,
        "by_owner":     by_owner_list,
        "by_partner":   by_partner_list,
        "note_types_seen": sorted(note_types_seen),
    }
