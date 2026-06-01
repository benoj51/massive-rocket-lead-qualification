"""
Scope intake — the data model behind Project Build.

Captures *what* the prospect is buying and how confident we are in the answer.
Each lead can have a Project record with one or more streams (CRM Strategy /
CRM Build / CRM Execute / Data work / Engineering). Each stream has a list
of criteria the AE answers + a 3-state qualification status per criterion.

Once the AE has filled in enough to be confident, they submit the project
for delivery validation. A delivery team member reviews, validates or
rejects (with notes), and the project then unlocks Pricing + Draft SOW.

Persistence: JSON files at cache/projects/<lead_id>.json. Keeps deploy
simple (no DB), portable to Postgres later if needed.

Public surface:
    project_types()              -> definition of the 5 streams
    criteria_library()           -> all criteria, grouped by stream
    discovery_questions()        -> Situation/Pain/Trap framework
    objection_library()          -> standard objection responses
    reference_points()           -> proof points / references
    new_project(lead_id, ...)    -> bootstrap a Project
    transition(project, action)  -> walk the validation state machine
    project_summary(project)     -> roll-up for the UI / Notion
    role_drivers_for_project(p)  -> map scope answers to pricing multipliers
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Project type definitions
# ---------------------------------------------------------------------------

PROJECT_TYPES = {
    "crm_strategy": {
        "label": "CRM Strategy",
        "description": "Ongoing advisory, roadmap, lifecycle maturity assessment.",
        "default_team_template": "crm_strategy",
    },
    "crm_build": {
        "label": "CRM Build",
        "description": "Campaign delivery, template development, migration projects.",
        "default_team_template": "crm_build",
    },
    "crm_execute": {
        "label": "CRM Execute",
        "description": "Massive Rocket operates the CRM platform on the prospect's behalf.",
        "default_team_template": "crm_execute",
    },
    "data_work": {
        "label": "Data Work",
        "description": "CDP setup, warehouse, identity, pipelines, analytics.",
        "default_team_template": "data_work",
    },
    "engineering": {
        "label": "Engineering",
        "description": "Custom integrations, APIs, bespoke applications.",
        "default_team_template": "engineering",
    },
}


# ---------------------------------------------------------------------------
# Criteria library
#
# Every criterion has:
#   - key: stable id
#   - label: prompt the AE sees
#   - hint: clarifies what answer is expected
#   - role_driver: which pricing role this criterion's value scales
#   - scale_factor: how much a "high" value bumps that role (relative)
# ---------------------------------------------------------------------------

# DEFAULT_CRITERIA_LIBRARY is the immutable baseline. The live library lives
# in criteria_store.py (JSON-backed, editable through the UI). This dict is
# the source of truth for "reset to defaults" and the fallback if storage
# can't be read.
DEFAULT_CRITERIA_LIBRARY: dict[str, list[dict[str, Any]]] = {
    "crm_strategy": [
        {"key": "engagement_length", "label": "Engagement length (months)",
         "hint": "Ongoing advisory is usually 6-12 months.",
         "role_driver": "CRM Strategist", "scale_factor": 1.0},
        {"key": "lifecycle_maturity", "label": "Lifecycle maturity (1-5)",
         "hint": "1 = no formal lifecycle programme, 5 = mature multi-channel.",
         "role_driver": "CRM Strategist", "scale_factor": 0.8},
        {"key": "stakeholder_count", "label": "Stakeholders to align",
         "hint": "More stakeholders = more workshop time.",
         "role_driver": "Program Manager", "scale_factor": 0.6},
        {"key": "roadmap_horizon", "label": "Roadmap horizon (months)",
         "hint": "How far out should the roadmap reach?",
         "role_driver": "CRM Strategist", "scale_factor": 0.5},
    ],
    "crm_build": [
        {"key": "migrating_campaigns", "label": "Number of campaigns to migrate",
         "hint": "Existing campaigns moving to the new platform.",
         "role_driver": "CRM Developer", "scale_factor": 1.0},
        {"key": "new_campaigns", "label": "Number of net-new campaigns",
         "hint": "Campaigns to build from scratch.",
         "role_driver": "CRM Developer", "scale_factor": 1.2},
        {"key": "templates_count", "label": "Number of templates to build",
         "hint": "Reusable email/push/SMS templates.",
         "role_driver": "UX/UI Designer", "scale_factor": 1.0},
        {"key": "html_templates_count", "label": "Custom HTML templates required",
         "hint": "Higher than 5 means significant dev effort.",
         "role_driver": "CRM Developer", "scale_factor": 1.5},
        {"key": "channels", "label": "Channels in scope",
         "hint": "e.g. Email, Push, SMS, In-app.",
         "role_driver": "CRM Strategist", "scale_factor": 0.3},
        {"key": "execute_for_them", "label": "Will MR execute campaigns?",
         "hint": "Yes = ongoing run-rate; no = build-and-handover.",
         "role_driver": None, "scale_factor": 0.0},
        {"key": "crm_stakeholder", "label": "Engaged CRM stakeholder",
         "hint": "Name + title of the day-to-day CRM owner.",
         "role_driver": None, "scale_factor": 0.0},
        {"key": "economic_buyer", "label": "Engaged economic buyer",
         "hint": "Name + title of whoever signs the contract.",
         "role_driver": None, "scale_factor": 0.0},
    ],
    "crm_execute": [
        {"key": "monthly_campaign_volume", "label": "Monthly campaign volume",
         "hint": "Campaigns sent per month.",
         "role_driver": "CRM Developer", "scale_factor": 1.0},
        {"key": "qa_required", "label": "QA depth required",
         "hint": "Light / Standard / Heavy.",
         "role_driver": "CRM Developer", "scale_factor": 0.5},
        {"key": "languages_supported", "label": "Languages / locales",
         "hint": "Each adds review + localisation cost.",
         "role_driver": "CRM Strategist", "scale_factor": 0.4},
        {"key": "ops_lead_name", "label": "Day-to-day ops lead",
         "hint": "Who's the primary contact on the prospect's side?",
         "role_driver": None, "scale_factor": 0.0},
    ],
    "data_work": [
        {"key": "use_cases_count", "label": "Number of use cases",
         "hint": "Each adds analytics + activation effort.",
         "role_driver": "Data Engineer", "scale_factor": 1.0},
        {"key": "data_sources_count", "label": "Number of data sources",
         "hint": "CRM, web, mobile, transactional, etc.",
         "role_driver": "Data Engineer", "scale_factor": 1.0},
        {"key": "destinations_count", "label": "Number of destinations",
         "hint": "CEP, ads, analytics, etc.",
         "role_driver": "Analytics Engineer", "scale_factor": 0.8},
        {"key": "channels", "label": "Channels (activation)",
         "hint": "Where activated data lands.",
         "role_driver": None, "scale_factor": 0.0},
        {"key": "data_warehouse", "label": "Data warehouse in place",
         "hint": "Snowflake / BigQuery / Databricks / Redshift / None.",
         "role_driver": "Data Architect", "scale_factor": 0.5},
        {"key": "cdp_in_place", "label": "CDP in place",
         "hint": "Segment / Hightouch / mParticle / Census / None.",
         "role_driver": "Data Architect", "scale_factor": 0.5},
        {"key": "analytics_platform", "label": "Analytics platform",
         "hint": "Amplitude / Mixpanel / Looker / etc.",
         "role_driver": None, "scale_factor": 0.0},
        {"key": "tech_stakeholder", "label": "Engaged technical stakeholder",
         "hint": "Name + title.",
         "role_driver": None, "scale_factor": 0.0},
        {"key": "tech_buyer", "label": "Engaged technical buyer",
         "hint": "Name + title of signing authority.",
         "role_driver": None, "scale_factor": 0.0},
    ],
    "engineering": [
        {"key": "integrations_count", "label": "Number of custom integrations",
         "hint": "Each non-standard integration adds dev effort.",
         "role_driver": "Software Engineer", "scale_factor": 1.0},
        {"key": "apis_to_build", "label": "Number of APIs to build",
         "hint": "Internal or partner-facing APIs.",
         "role_driver": "Software Engineer", "scale_factor": 1.2},
        {"key": "infra_complexity", "label": "Infra complexity (1-5)",
         "hint": "1 = simple cloud-hosted, 5 = multi-region high-availability.",
         "role_driver": "Architect", "scale_factor": 0.8},
        # v0.10.0o: SDK implementation block. Each surface where an SDK
        # lands (Braze, Iterable, mParticle, Firebase, AppsFlyer, etc.)
        # is a distinct piece of work — set-up, identity, event mapping,
        # QA per platform. Asking these as discrete counts keeps the
        # pricing model honest and the AE's discovery question explicit.
        {"key": "sdk_platform", "label": "SDK platform / vendor",
         "hint": "Which SDK(s) we're implementing — Braze, Iterable, mParticle, Segment, Firebase, AppsFlyer, etc. Affects effort per surface.",
         "role_driver": None, "scale_factor": 0.0},
        {"key": "sdk_websites_count", "label": "SDK · number of websites",
         "hint": "Distinct web surfaces needing the SDK (marketing site, logged-in app, microsites, brand variants). Each adds dev + QA cycles.",
         "role_driver": "Software Engineer", "scale_factor": 1.0},
        {"key": "sdk_ios_apps_count", "label": "SDK · number of iOS apps",
         "hint": "iOS native apps. White-label brand variants count separately. Includes SwiftUI / UIKit codebases.",
         "role_driver": "Software Engineer", "scale_factor": 1.2},
        {"key": "sdk_android_apps_count", "label": "SDK · number of Android apps",
         "hint": "Android native apps. White-label brand variants count separately. Includes Compose / View-based codebases.",
         "role_driver": "Software Engineer", "scale_factor": 1.2},
        {"key": "sdk_hybrid_apps_count", "label": "SDK · number of hybrid / cross-platform apps",
         "hint": "React Native, Flutter, Cordova/Ionic, etc. Lower per-app effort than fully native but bridge work still adds up.",
         "role_driver": "Software Engineer", "scale_factor": 0.9},
        {"key": "sdk_other_surfaces", "label": "SDK · other surfaces",
         "hint": "Connected TV, kiosks, in-store touchpoints, voice, watch apps. Free text or count.",
         "role_driver": "Architect", "scale_factor": 0.8},
        {"key": "sdk_complexity", "label": "SDK implementation complexity (1-5)",
         "hint": "1 = greenfield + simple events. 3 = identity merge or custom event mapping. 5 = legacy GTM/Tealium → SDK migration with attribution preservation.",
         "role_driver": "Architect", "scale_factor": 0.6},
        {"key": "engineering_lead_name", "label": "Engaged engineering lead",
         "hint": "Their tech lead / VP Eng.",
         "role_driver": None, "scale_factor": 0.0},
    ],
}


# ---------------------------------------------------------------------------
# Discovery questions, objections, reference points
# ---------------------------------------------------------------------------
# These travel with the project so the AE can review them before each call.

DISCOVERY_QUESTIONS = {
    "situation": [
        "What's the current CRM/marketing tooling stack?",
        "Who currently runs campaign delivery?",
        "What's the team structure (in-house vs agency split)?",
        "What's the renewal/contract timeline for incumbent vendors?",
    ],
    "pain": [
        "What's not working with the current setup?",
        "What's the executive sponsor's #1 pain point?",
        "What have they tried that didn't fix it?",
        "What happens if nothing changes in 12 months?",
    ],
    "trap": [
        "What's the bar for success in year 1?",
        "Who else are they evaluating?",
        "What would make them choose us over an in-house build?",
        "What's their procurement / paper process?",
    ],
}

OBJECTION_LIBRARY = [
    {"objection": "Price is too high",
     "response": "Anchor on the loyalty-revenue uplift our QSR clients see "
                 "(reference: 8-12% incremental revenue). The ROI window is "
                 "typically 9 months."},
    {"objection": "Talking to another vendor",
     "response": "We don't compete on platform features; we compete on "
                 "delivery depth. Offer a 4-week paid POC to demonstrate."},
    {"objection": "We need someone based in the US",
     "response": "Our US Client Partner leads on-the-ground; UK delivery team "
                 "is 5 hours ahead with overlap. Offer references from US "
                 "clients running this model."},
    {"objection": "Could do it internally",
     "response": "Frame the trade: speed-to-value vs hiring time. A team of "
                 "8 with 5+ years on Braze takes 18 months to assemble; we "
                 "ship in 12 weeks."},
    {"objection": "Budget cycle is wrong",
     "response": "Offer a phased SOW: Discovery + Plan in this fiscal, "
                 "Execute + Accelerate in the next. Lock pricing now."},
]

REFERENCE_POINTS = [
    {"industry": "QSR", "customer": "Yum! Brands", "proof_point": "Multi-brand lifecycle migration across KFC, Taco Bell, Pizza Hut"},
    {"industry": "QSR", "customer": "RBI", "proof_point": "Migration from SFMC to Braze across Burger King, Tim Hortons, Popeyes"},
    {"industry": "Travel", "customer": "IHG", "proof_point": "Loyalty programme lifecycle redesign across 6,000+ properties"},
    {"industry": "Delivery", "customer": "Just Eat", "proof_point": "Hyper-segmented retention across 18 markets"},
    {"industry": "Fintech", "customer": "Monzo", "proof_point": "Net-new lifecycle from greenfield to 4M+ users"},
    {"industry": "Convenience", "customer": "GoPuff", "proof_point": "Geo-triggered abandonment + reactivation campaigns"},
    # Tech partners
    {"industry": "Tech Partner", "customer": "Braze", "proof_point": "Top-3 global delivery partner; 50+ certified architects"},
    {"industry": "Tech Partner", "customer": "Hightouch", "proof_point": "Reverse-ETL implementations across QSR + retail"},
    {"industry": "Tech Partner", "customer": "Snowflake", "proof_point": "Warehouse-first activation patterns for consumer brands"},
]


# ---------------------------------------------------------------------------
# Validation state machine
# ---------------------------------------------------------------------------

VALIDATION_STATES = ("draft", "pending_validation", "validated", "rejected")
ALLOWED_TRANSITIONS = {
    "draft":               {"pending_validation"},
    "pending_validation":  {"validated", "rejected", "draft"},   # delivery can bounce
    "validated":           {"draft"},                            # re-open if scope changes
    "rejected":            {"draft"},                            # AE addresses notes + resubmits
}


class ScopeError(RuntimeError):
    """Bad scope transition or malformed input."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CriterionAnswer:
    key: str
    value: str = ""          # free text; numbers stored as strings for simplicity
    status: str = "unqualified"   # unqualified | qualifying | qualified


@dataclass
class ProjectStream:
    project_type: str
    criteria: list[CriterionAnswer] = field(default_factory=list)


@dataclass
class ProjectScope:
    lead_id: str
    company_name: str
    streams: list[ProjectStream] = field(default_factory=list)
    validation_status: str = "draft"
    validation_notes: str = ""
    validated_by: str | None = None
    validated_at: str | None = None
    created_at: str = field(default_factory=lambda: _now_iso())
    updated_at: str = field(default_factory=lambda: _now_iso())

    def touch(self) -> None:
        self.updated_at = _now_iso()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def project_types() -> dict[str, dict[str, Any]]:
    return dict(PROJECT_TYPES)


def criteria_library() -> dict[str, list[dict[str, Any]]]:
    """Live criteria library. Reads from the editable store; falls back to
    DEFAULT_CRITERIA_LIBRARY if the store isn't available."""
    try:
        import criteria_store
        return criteria_store.load()
    except Exception:
        return {pt: list(criteria) for pt, criteria in DEFAULT_CRITERIA_LIBRARY.items()}


def discovery_questions() -> dict[str, list[str]]:
    return {k: list(v) for k, v in DISCOVERY_QUESTIONS.items()}


def objection_library() -> list[dict[str, str]]:
    return list(OBJECTION_LIBRARY)


def reference_points(industry: str | None = None) -> list[dict[str, str]]:
    if not industry:
        return list(REFERENCE_POINTS)
    needle = industry.lower()
    return [r for r in REFERENCE_POINTS if needle in r["industry"].lower()]


def new_project(lead_id: str, company_name: str, project_type_keys: Iterable[str]) -> ProjectScope:
    """Bootstrap a Project with empty criteria for every selected stream."""
    library = criteria_library()
    streams: list[ProjectStream] = []
    for pt in project_type_keys:
        if pt not in PROJECT_TYPES:
            raise ScopeError(f"Unknown project type: {pt}")
        criteria = [CriterionAnswer(key=c["key"]) for c in library.get(pt, [])]
        streams.append(ProjectStream(project_type=pt, criteria=criteria))
    return ProjectScope(lead_id=lead_id, company_name=company_name, streams=streams)


def update_criterion(scope: ProjectScope, project_type: str, key: str, *, value: str | None = None, status: str | None = None) -> ProjectScope:
    """Set value and/or status on a single criterion. Creates the answer
    record if the criterion was added to the library after the project was
    bootstrapped — keeps editable criteria from breaking saves."""
    if status is not None and status not in ("unqualified", "qualifying", "qualified"):
        raise ScopeError(f"Bad status {status!r}")
    target_stream: ProjectStream | None = None
    for stream in scope.streams:
        if stream.project_type == project_type:
            target_stream = stream
            break
    if target_stream is None:
        raise ScopeError(f"Stream {project_type!r} not on project")
    for c in target_stream.criteria:
        if c.key == key:
            if value is not None:
                c.value = value
            if status is not None:
                c.status = status
            scope.touch()
            return scope
    # Criterion didn't exist on this project yet (added to library after
    # bootstrap). Append it now.
    target_stream.criteria.append(CriterionAnswer(
        key=key,
        value=value or "",
        status=status or "unqualified",
    ))
    scope.touch()
    return scope


def transition(scope: ProjectScope, action: str, *, actor: str | None = None, notes: str = "") -> ProjectScope:
    """Walk the validation state machine. `action` is the new state."""
    if action not in VALIDATION_STATES:
        raise ScopeError(f"Unknown action {action!r}")
    allowed = ALLOWED_TRANSITIONS.get(scope.validation_status, set())
    if action not in allowed:
        raise ScopeError(
            f"Cannot move from {scope.validation_status!r} to {action!r}; "
            f"allowed: {sorted(allowed)}"
        )
    scope.validation_status = action
    if action in ("validated", "rejected"):
        scope.validated_by = actor or scope.validated_by
        scope.validated_at = _now_iso()
        if notes:
            scope.validation_notes = notes
    elif action == "draft":
        # Re-open clears prior validation metadata so the next reviewer sees a clean slate.
        scope.validated_by = None
        scope.validated_at = None
        if notes:
            scope.validation_notes = notes
    scope.touch()
    return scope


def _criterion_stats(scope: ProjectScope) -> dict[str, int]:
    qualified = qualifying = unqualified = 0
    for stream in scope.streams:
        for c in stream.criteria:
            if c.status == "qualified":
                qualified += 1
            elif c.status == "qualifying":
                qualifying += 1
            else:
                unqualified += 1
    total = qualified + qualifying + unqualified
    return {
        "total": total,
        "qualified": qualified,
        "qualifying": qualifying,
        "unqualified": unqualified,
        "qualified_pct": round(100 * qualified / total, 1) if total else 0.0,
    }


def project_summary(scope: ProjectScope) -> dict[str, Any]:
    stats = _criterion_stats(scope)
    confidence = "high" if stats["qualified_pct"] >= 70 else ("medium" if stats["qualified_pct"] >= 40 else "low")
    return {
        "lead_id": scope.lead_id,
        "company_name": scope.company_name,
        "streams": [s.project_type for s in scope.streams],
        "validation_status": scope.validation_status,
        "validation_notes": scope.validation_notes,
        "validated_by": scope.validated_by,
        "validated_at": scope.validated_at,
        "stats": stats,
        "confidence": confidence,
        "ready_for_pricing": (scope.validation_status == "validated"),
        "updated_at": scope.updated_at,
    }


def role_drivers_for_project(scope: ProjectScope) -> dict[str, float]:
    """Translate scope answers into pricing role multipliers.

    For each criterion that has a role_driver and a numeric value, we
    contribute a normalised bump to that role's effort multiplier. The
    aggregator is conservative: multipliers cluster around 1.0 and rarely
    move more than ±0.5 per criterion.
    """
    multipliers: dict[str, float] = {}
    live_library = criteria_library()
    for stream in scope.streams:
        library = {c["key"]: c for c in live_library.get(stream.project_type, [])}
        for answer in stream.criteria:
            spec = library.get(answer.key)
            if not spec or not spec.get("role_driver"):
                continue
            role = spec["role_driver"]
            scale = float(spec.get("scale_factor", 0))
            numeric = _coerce_number(answer.value)
            if numeric is None or scale == 0:
                continue
            # v1.0.0ea: counts 0-10 ramp linearly to 1.0 (unchanged). Above
            # 10 the ramp continues gently so a 40-campaign build prices above
            # a 10-campaign one, but it stays bounded (max 1.5) so a single
            # criterion can't dominate the quote. The previous code hard-capped
            # the normaliser at 10, so a 10-template and a 50-template build
            # produced an identical price.
            if numeric <= 10:
                normalised = numeric / 10.0
            else:
                normalised = 1.0 + min((numeric - 10.0) / 80.0, 0.5)
            bump = normalised * scale
            multipliers[role] = max(multipliers.get(role, 1.0) + bump, 0.5)
    return multipliers


def _coerce_number(s: str) -> float | None:
    if not s:
        return None
    cleaned = "".join(ch for ch in str(s) if (ch.isdigit() or ch == "."))
    try:
        return float(cleaned)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def to_dict(scope: ProjectScope) -> dict[str, Any]:
    """JSON-safe dict; use this for persistence."""
    return asdict(scope)


def from_dict(data: dict[str, Any]) -> ProjectScope:
    streams = []
    for s in data.get("streams") or []:
        streams.append(ProjectStream(
            project_type=s["project_type"],
            criteria=[CriterionAnswer(**c) for c in s.get("criteria", [])],
        ))
    return ProjectScope(
        lead_id=data["lead_id"],
        company_name=data.get("company_name", ""),
        streams=streams,
        validation_status=data.get("validation_status", "draft"),
        validation_notes=data.get("validation_notes", ""),
        validated_by=data.get("validated_by"),
        validated_at=data.get("validated_at"),
        created_at=data.get("created_at", _now_iso()),
        updated_at=data.get("updated_at", _now_iso()),
    )
