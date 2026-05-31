"""
Project roadmap — phased timeline + extended engagement plan per lead.

A roadmap is the AE-facing planning artefact that lives between scope and
SOW. Two parts:

  1. Milestones — list of {workstream, title, month_offset, duration_months,
     phase, description}. Renders as a Gantt-lite timeline in the UI and
     a structured section in the SOW.

  2. Extended engagement — list of {year, package_key | custom, title,
     description, estimated_hours, estimated_price}. The "Beyond Year 1"
     pitch: what else the prospect could do with MR over a longer
     relationship.

Roadmap also carries `start_date` and `end_date` (ISO YYYY-MM-DD) so the
month_offset values resolve to real dates ("M3" → "May 2026").

Persistence: JSON file per lead at cache/roadmaps/<lead_id>.json.

Public surface:
    load(lead_id)                                 -> Roadmap | None
    save(lead_id, roadmap_dict)                   -> Roadmap (round-tripped)
    new_roadmap(lead_id, *, months, start_date)   -> Roadmap (empty)
    seed_milestones_from_package(roadmap, pkg)    -> Roadmap (in place)
    workstreams_from_scope(project_scope)         -> list[str]
"""
from __future__ import annotations

import json
import json_file_store
import os
import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DIR = Path(__file__).parent / "cache" / "roadmaps"
_LOCK = threading.Lock()

# Known workstream labels. Match the project_types in scope.py so milestones
# can be filtered/grouped consistently. The label is the user-facing string.
DEFAULT_WORKSTREAMS = ["CRM Strategy", "CRM Build", "CRM Execute",
                       "Data", "Engineering", "Cross-cutting"]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@dataclass
class Milestone:
    workstream: str = "Cross-cutting"
    title: str = ""
    month_offset: int = 0       # 0 = project start month
    duration_months: int = 1    # >= 1
    phase: str = "Execute"      # Understand / Execute / Accelerate / Cross-cutting
    description: str = ""
    id: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:10]
        self.month_offset = max(0, int(self.month_offset or 0))
        self.duration_months = max(1, int(self.duration_months or 1))


@dataclass
class ExtendedItem:
    year: int = 2                      # 2, 3, etc.
    title: str = ""
    description: str = ""
    package_key: str | None = None
    estimated_hours: int = 0
    estimated_price_usd: float = 0.0
    id: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:10]
        self.year = max(2, int(self.year or 2))


@dataclass
class Roadmap:
    lead_id: str
    months: int = 12
    start_date: str = ""              # ISO YYYY-MM-DD; empty == not set yet
    end_date: str = ""                # ISO YYYY-MM-DD; derived if empty
    milestones: list[Milestone] = field(default_factory=list)
    extended_engagement: list[ExtendedItem] = field(default_factory=list)
    updated_at: str = ""

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat(
            timespec="seconds").replace("+00:00", "Z")
        # Auto-derive end_date if missing but start is set.
        if self.start_date and not self.end_date:
            self.end_date = _add_months_iso(self.start_date, self.months)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _store_dir() -> Path:
    override = os.environ.get("ROADMAP_STORE_DIR")
    d = Path(override) if override else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(lead_id: str) -> Path:
    import project_store
    return _store_dir() / f"{project_store.slugify(lead_id)}.json"


def _add_months_iso(iso_date: str, months: int) -> str:
    """Add N months to an ISO date string. Simple month arithmetic."""
    try:
        d = date.fromisoformat(iso_date)
    except ValueError:
        return ""
    total_months = d.month - 1 + months
    new_year = d.year + total_months // 12
    new_month = total_months % 12 + 1
    # Clamp day to month's last day
    import calendar
    last_day = calendar.monthrange(new_year, new_month)[1]
    new_day = min(d.day, last_day)
    return date(new_year, new_month, new_day).isoformat()


def workstreams_from_scope(project_streams: list[str]) -> list[str]:
    """Map scope project_type keys to roadmap workstream labels."""
    label_map = {
        "crm_strategy": "CRM Strategy",
        "crm_build": "CRM Build",
        "crm_execute": "CRM Execute",
        "data_work": "Data",
        "engineering": "Engineering",
    }
    out = [label_map.get(s, s.title()) for s in (project_streams or [])]
    return out or ["Cross-cutting"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def new_roadmap(lead_id: str, *, months: int = 12,
                start_date: str = "") -> Roadmap:
    r = Roadmap(lead_id=lead_id, months=int(months or 12),
                start_date=start_date or "")
    r.touch()
    return r


def to_dict(roadmap: Roadmap) -> dict[str, Any]:
    d = asdict(roadmap)
    return d


def _safe_milestone(m: dict[str, Any]) -> Milestone:
    fields = {"workstream", "title", "month_offset", "duration_months",
              "phase", "description", "id"}
    return Milestone(**{k: v for k, v in m.items() if k in fields})


def _safe_extended(e: dict[str, Any]) -> ExtendedItem:
    fields = {"year", "title", "description", "package_key",
              "estimated_hours", "estimated_price_usd", "id"}
    return ExtendedItem(**{k: v for k, v in e.items() if k in fields})


def from_dict(data: dict[str, Any]) -> Roadmap:
    milestones = [_safe_milestone(m) for m in (data.get("milestones") or [])]
    extended = [_safe_extended(e) for e in (data.get("extended_engagement") or [])]
    r = Roadmap(
        lead_id=data["lead_id"],
        months=int(data.get("months") or 12),
        start_date=data.get("start_date", "") or "",
        end_date=data.get("end_date", "") or "",
        milestones=milestones,
        extended_engagement=extended,
        updated_at=data.get("updated_at", ""),
    )
    return r


def load(lead_id: str) -> Roadmap | None:
    p = _path(lead_id)
    if not p.exists():
        return None
    try:
        with _LOCK:
            return from_dict(json.loads(p.read_text()))
    except (json.JSONDecodeError, OSError, KeyError):
        return None


def save(lead_id: str, payload: dict[str, Any] | Roadmap) -> Roadmap:
    """Persist a roadmap, normalising on the way in."""
    if isinstance(payload, Roadmap):
        rm = payload
    else:
        rm = from_dict({"lead_id": lead_id, **payload})
    rm.lead_id = lead_id
    rm.touch()
    with _LOCK:
        json_file_store.write_json(_path(lead_id), to_dict(rm))
    return rm


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


# ---------------------------------------------------------------------------
# Package -> milestones seeding
# ---------------------------------------------------------------------------

def seed_milestones_from_package(roadmap: Roadmap, package: dict[str, Any]) -> Roadmap:
    """Generate milestones from a package's components. Each component becomes
    a milestone spanning the package duration, tagged with a workstream
    inferred from the role + activity."""
    duration = max(1, int(package.get("duration_months") or 1))
    workstream_for_role = {
        "Client Partner": "Cross-cutting",
        "CRM Strategist": "CRM Strategy",
        "CRM Consultant": "CRM Build",
        "CRM Architect": "CRM Build",
        "CRM Developer": "CRM Build",
        "Architect": "Cross-cutting",
        "Solution Architect": "Cross-cutting",
        "Program Manager": "Cross-cutting",
        "Project coordinator": "Cross-cutting",
        "UX/UI Designer": "CRM Build",
        "Braze Trainer": "CRM Strategy",
        "Senior Braze Trainer": "CRM Strategy",
        "Braze Architect": "CRM Build",
        "CDM Architect": "Data",
        "Data Engineer": "Data",
        "Analytics Engineer": "Data",
        "Engineering Lead": "Engineering",
        "Software Engineer": "Engineering",
        "Engineer": "Engineering",
        "Product Owner": "Engineering",
        "Onboarding Consultant": "CRM Strategy",
        "Technical Architect": "Engineering",
        "Consultant": "CRM Strategy",
    }
    # Group components by activity title so we don't produce 8 overlapping
    # bars for a single phase.
    grouped: dict[str, dict[str, Any]] = {}
    for c in (package.get("components") or []):
        activity = c.get("activity") or "Delivery"
        role = c.get("role") or ""
        key = activity
        if key not in grouped:
            grouped[key] = {
                "title": activity,
                "workstream": workstream_for_role.get(role, "Cross-cutting"),
                "roles": set(),
                "hours": 0,
            }
        grouped[key]["roles"].add(role)
        grouped[key]["hours"] += c.get("hours") or 0

    # Sort components in a sensible delivery order. Activities containing
    # "Planning" / "Audit" / "Mapping" come first; "QA" / "Training" last.
    def _order_key(item):
        t = item["title"].lower()
        if any(w in t for w in ("audit", "planning", "case", "discovery", "requirements")):
            return 0
        if any(w in t for w in ("training", "documentation", "handover")):
            return 9
        if "quality" in t:
            return 8
        if "project management" in t or "project plan" in t:
            return 7
        return 5

    items = sorted(grouped.values(), key=_order_key)
    # Distribute across the duration. If duration >= len(items), spread one
    # milestone per month; otherwise compress so multiple share a month.
    if not items:
        return roadmap
    # Each milestone gets ~ duration / count months, min 1.
    span = max(1, duration // max(1, len(items)))
    new_milestones = []
    cursor = 0
    for i, item in enumerate(items):
        m_offset = min(cursor, duration - 1)
        m_dur = min(span, duration - m_offset)
        if i == len(items) - 1:
            # Pad the last milestone to reach project end
            m_dur = max(m_dur, duration - m_offset)
        new_milestones.append(Milestone(
            id="",
            workstream=item["workstream"],
            title=item["title"],
            month_offset=m_offset,
            duration_months=m_dur,
            description=f"Roles: {', '.join(sorted(item['roles']))} · ~{item['hours']}h",
        ))
        cursor += span
    # Apply phase labels heuristically.
    for m in new_milestones:
        if m.month_offset < duration / 3:
            m.phase = "Understand"
        elif m.month_offset < 2 * duration / 3:
            m.phase = "Execute"
        else:
            m.phase = "Accelerate"
    roadmap.milestones = new_milestones
    roadmap.months = duration
    roadmap.touch()
    return roadmap
