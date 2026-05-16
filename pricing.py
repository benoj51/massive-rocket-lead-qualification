"""
Pricing calculator for Massive Rocket engagements.

Codifies the logic behind the Summary Sheet of the existing Pricing Calculator
spreadsheet. Two role rate tiers, three phases (Understand / Execute /
Accelerate), per-role monthly allocations that scale with the phase.

The reference deal (12-month enterprise engagement that produced the
$1,111,360 net total in the source CSV) is the calibration test —
reproduced exactly in tests/test_pricing.py.

Public surface:
    compute_quote(scope)        -> full quote (monthly + totals + breakdown)
    apply_discount(monthly_fn)  -> hook for non-standard discount schedules
    role_catalogue()            -> the role rate book

The catalogue + team templates below are the SOURCE OF TRUTH for pricing.
Edit here when the rate card changes; tests will keep the maths honest.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Rate catalogue
# ---------------------------------------------------------------------------
# Reverse-engineered from the reference Summary Sheet: MR's client-facing
# rate book is a single blended USD/hour figure with per-role FTE varying
# by phase. Internal cost accounting uses different per-role rates (not
# captured here — TODO: a margin view once finance shares them).

USD_PER_GBP = 1.27  # rough; refresh per quarter

CLIENT_BLENDED_RATE_USD_PER_HOUR = 200  # single rate across every role

# Roles are catalogued so the UI can render the team — the cost calc uses
# the blended rate above; per-role rates here are placeholders that match
# the blended figure.
ROLE_RATES_USD_PER_HOUR = {
    "Client Partner":     CLIENT_BLENDED_RATE_USD_PER_HOUR,
    "CRM Strategist":     CLIENT_BLENDED_RATE_USD_PER_HOUR,
    "CRM Architect":      CLIENT_BLENDED_RATE_USD_PER_HOUR,
    "CRM Developer":      CLIENT_BLENDED_RATE_USD_PER_HOUR,
    "Architect":          CLIENT_BLENDED_RATE_USD_PER_HOUR,
    "Program Manager":    CLIENT_BLENDED_RATE_USD_PER_HOUR,
    "UX/UI Designer":     CLIENT_BLENDED_RATE_USD_PER_HOUR,
    "Data Architect":     CLIENT_BLENDED_RATE_USD_PER_HOUR,
    "Data Engineer":      CLIENT_BLENDED_RATE_USD_PER_HOUR,
    "Analytics Engineer": CLIENT_BLENDED_RATE_USD_PER_HOUR,
    "Software Engineer":  CLIENT_BLENDED_RATE_USD_PER_HOUR,
    "Engineering Lead":   CLIENT_BLENDED_RATE_USD_PER_HOUR,
    "Solution Architect": CLIENT_BLENDED_RATE_USD_PER_HOUR,
}

# Standard working assumption: 1 FTE month = 160 hours (~ 20 working days).
HOURS_PER_FTE_MONTH = 160


# ---------------------------------------------------------------------------
# Phase definitions
# ---------------------------------------------------------------------------

PHASES = ("Understand", "Execute", "Accelerate")
DEFAULT_PHASE_MONTHS = {"Understand": 3, "Execute": 6, "Accelerate": 3}

# Standard early-phase discount the reference deal uses: 15% on M1-M6,
# 0% from M7. Bundled here so a quote stays reproducible.
DEFAULT_DISCOUNT_RULES = [
    ("Understand", 0.15),  # 15% off every Understand month
    ("Execute_first_half", 0.15),  # 15% off the first half of Execute
]


# ---------------------------------------------------------------------------
# Team templates per project type
# ---------------------------------------------------------------------------
# Each entry maps a role to its FTE allocation in each phase. These templates
# are the *baseline* — Project Build's scope answers nudge them via the role
# drivers in scope.py.
#
# FTE values are expressed as fractions: 0.25 = a quarter of a person.
# A role can also scale up at a phase boundary (e.g. CRM Architect going from
# 0.5 -> 0.75 -> 1.0 across the phases).

TeamTemplate = dict[str, dict[str, float]]  # {role: {phase: fte}}

TEAM_TEMPLATES: dict[str, TeamTemplate] = {
    # Reference engagement that produced the $1.11M net in the source CSV.
    # FTEs calibrated against the Summary Sheet — each value back-calculated
    # from (monthly_cost / $200 / 160h).
    "crm_build": {
        "Client Partner":   {"Understand": 0.20, "Execute": 0.20, "Accelerate": 0.20},
        "CRM Strategist":   {"Understand": 0.50, "Execute": 0.50, "Accelerate": 0.50},
        "CRM Architect":    {"Understand": 0.50, "Execute": 0.625, "Accelerate": 1.00},  # ramps with complexity
        "CRM Developer":    {"Understand": 0.10, "Execute": 0.25, "Accelerate": 0.25},
        "Architect":        {"Understand": 0.20, "Execute": 0.20, "Accelerate": 0.20},
        "Program Manager":  {"Understand": 0.42, "Execute": 0.54, "Accelerate": 0.61},
        "UX/UI Designer":   {"Understand": 0.20, "Execute": 0.30, "Accelerate": 0.40},
        "CRM Strategist ":  {"Understand": 0.40, "Execute": 0.50, "Accelerate": 0.50},  # 2nd strategist
    },
    "crm_strategy": {
        "Client Partner":   {"Understand": 0.25, "Execute": 0.25, "Accelerate": 0.25},
        "CRM Strategist":   {"Understand": 0.75, "Execute": 0.50, "Accelerate": 0.25},
        "CRM Architect":    {"Understand": 0.25, "Execute": 0.25, "Accelerate": 0.25},
        "Program Manager":  {"Understand": 0.25, "Execute": 0.25, "Accelerate": 0.25},
    },
    "crm_execute": {
        "Client Partner":   {"Understand": 0.25, "Execute": 0.25, "Accelerate": 0.25},
        "CRM Strategist":   {"Understand": 0.25, "Execute": 0.50, "Accelerate": 0.50},
        "CRM Developer":    {"Understand": 0.50, "Execute": 1.00, "Accelerate": 1.00},
        "Program Manager":  {"Understand": 0.50, "Execute": 0.75, "Accelerate": 0.75},
    },
    "data_work": {
        "Client Partner":   {"Understand": 0.25, "Execute": 0.25, "Accelerate": 0.25},
        "Solution Architect": {"Understand": 0.50, "Execute": 0.50, "Accelerate": 0.50},
        "Data Architect":   {"Understand": 0.50, "Execute": 0.75, "Accelerate": 0.50},
        "Data Engineer":    {"Understand": 0.25, "Execute": 1.00, "Accelerate": 0.50},
        "Analytics Engineer": {"Understand": 0.25, "Execute": 0.50, "Accelerate": 0.50},
        "Program Manager":  {"Understand": 0.42, "Execute": 0.54, "Accelerate": 0.42},
    },
    "engineering": {
        "Client Partner":   {"Understand": 0.25, "Execute": 0.25, "Accelerate": 0.25},
        "Engineering Lead": {"Understand": 0.50, "Execute": 0.50, "Accelerate": 0.50},
        "Software Engineer": {"Understand": 0.25, "Execute": 1.00, "Accelerate": 1.00},
        "Architect":        {"Understand": 0.50, "Execute": 0.25, "Accelerate": 0.25},
        "Program Manager":  {"Understand": 0.42, "Execute": 0.54, "Accelerate": 0.42},
    },
}


# ---------------------------------------------------------------------------
# Quote model
# ---------------------------------------------------------------------------

@dataclass
class QuoteInputs:
    """What the AE picks to compute a quote.

    v0.8 added rate-card aware lookups + Project Ops + Contingency uplifts.
    Defaults preserve v0.4 behaviour: MR Default rate card, USD,
    no uplifts, 15% first-half discount.
    """
    project_types: list[str]   # ["crm_build", "data_work"] etc.
    months: int = 12           # total project length
    phase_months: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_PHASE_MONTHS))
    discount_pct_first_half: float = 0.15
    discount_pct_second_half: float = 0.0
    currency: str = "USD"
    role_overrides: dict[str, dict[str, float]] = field(default_factory=dict)
    effort_multipliers: dict[str, float] = field(default_factory=dict)
    # v0.8 additions
    rate_card: str = "MR Default"
    project_ops_pct: float = 0.0      # uplift on gross
    contingency_pct: float = 0.0      # uplift on gross + ops
    # Staff Augmentation needs region + seniority; if rate_card is "Staff
    # Augmentation" these supply the defaults when role-specific overrides
    # don't carry them. Keys are role names; values are {region, seniority}.
    role_staffing: dict[str, dict[str, str]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# The maths
# ---------------------------------------------------------------------------

def _phase_for_month(month_idx: int, phase_months: dict[str, int]) -> str:
    """Map a 1-indexed month to its phase label."""
    cursor = 0
    for phase in PHASES:
        cursor += phase_months.get(phase, 0)
        if month_idx <= cursor:
            return phase
    return PHASES[-1]


def _merge_team_templates(project_types: Iterable[str]) -> TeamTemplate:
    """When a deal has multiple project types, merge their team templates by
    taking the max FTE per role per phase (a single role serves both streams)."""
    merged: TeamTemplate = {}
    for pt in project_types:
        template = TEAM_TEMPLATES.get(pt, {})
        for role, by_phase in template.items():
            base = merged.setdefault(role, {})
            for phase, fte in by_phase.items():
                base[phase] = max(base.get(phase, 0.0), fte)
    return merged


def _apply_role_overrides(team: TeamTemplate, overrides: dict[str, dict[str, float]]) -> TeamTemplate:
    """Allow the AE to bump roles up/down before final pricing."""
    if not overrides:
        return team
    merged = {role: dict(by_phase) for role, by_phase in team.items()}
    for role, by_phase in overrides.items():
        merged.setdefault(role, {}).update(by_phase)
    return merged


def _apply_effort_multipliers(team: TeamTemplate, multipliers: dict[str, float]) -> TeamTemplate:
    """Scope criteria can multiply role effort (e.g. "lots of templates"
    pushes CRM Developer up by 1.4x). Multipliers are applied across all
    phases for the named role."""
    if not multipliers:
        return team
    merged = {role: dict(by_phase) for role, by_phase in team.items()}
    for role, factor in multipliers.items():
        if role not in merged:
            continue
        for phase in merged[role]:
            merged[role][phase] = round(merged[role][phase] * factor, 4)
    return merged


def _resolve_rate(role: str, inputs: QuoteInputs) -> float:
    """Look up the hourly rate for a role under the chosen rate card + currency.
    Falls back to MR Default rate if the role isn't on the chosen card."""
    import rate_cards
    staffing = inputs.role_staffing.get(role, {}) if inputs.rate_card == "Staff Augmentation" else {}
    rate = rate_cards.rate_lookup(
        inputs.rate_card, role, inputs.currency,
        region=staffing.get("region"), seniority=staffing.get("seniority"),
    )
    if rate is None:
        # Fallback: MR Default in same currency.
        rate = rate_cards.rate_lookup("MR Default", role, inputs.currency)
    return float(rate["hourly"]) if rate else 0.0


def _resolve_internal_cost(role: str, inputs: QuoteInputs) -> float:
    """Hourly internal cost for a role under the chosen staffing."""
    import internal_costs
    staffing = inputs.role_staffing.get(role, {})
    cost = internal_costs.internal_cost_lookup(
        role, inputs.currency,
        region=staffing.get("region"), seniority=staffing.get("seniority"),
    )
    return float(cost["hourly"]) if cost else 0.0


def _monthly_breakdown(team: TeamTemplate, inputs: QuoteInputs) -> list[dict[str, Any]]:
    months = inputs.months
    breakdown: list[dict[str, Any]] = []
    role_rates = {role.strip(): _resolve_rate(role.strip(), inputs) for role in team.keys()}
    role_costs = {role.strip(): _resolve_internal_cost(role.strip(), inputs) for role in team.keys()}
    for m in range(1, months + 1):
        phase = _phase_for_month(m, inputs.phase_months)
        rows: list[dict[str, Any]] = []
        month_total_usd = 0.0
        month_hours = 0.0
        month_internal_cost = 0.0
        for role, by_phase in team.items():
            role_name = role.strip()
            fte = by_phase.get(phase, 0.0)
            if fte <= 0:
                continue
            hours = fte * HOURS_PER_FTE_MONTH
            rate = role_rates.get(role_name, 0)
            internal_rate = role_costs.get(role_name, 0)
            cost = hours * rate
            internal_cost = hours * internal_rate
            rows.append({
                "role": role_name,
                "fte": fte,
                "hours": hours,
                "rate_usd_per_hour": rate,  # name kept for backward compat; reflects selected currency
                "internal_rate_per_hour": internal_rate,
                "cost_usd": round(cost, 2),
                "internal_cost_usd": round(internal_cost, 2),
            })
            month_total_usd += cost
            month_hours += hours
            month_internal_cost += internal_cost

        # Project Ops uplift (proportional fee on top of gross)
        ops_usd = month_total_usd * inputs.project_ops_pct
        # Contingency uplift (on gross + ops, per the spec)
        contingency_usd = (month_total_usd + ops_usd) * inputs.contingency_pct
        # All-inclusive subtotal before discount
        subtotal_usd = month_total_usd + ops_usd + contingency_usd

        discount_pct = inputs.discount_pct_first_half if m <= months // 2 else inputs.discount_pct_second_half
        discount_usd = subtotal_usd * discount_pct
        net_usd = subtotal_usd - discount_usd

        breakdown.append({
            "month": m,
            "phase": phase,
            "rows": rows,
            "gross_usd": round(month_total_usd, 2),
            "ops_usd": round(ops_usd, 2),
            "contingency_usd": round(contingency_usd, 2),
            "subtotal_usd": round(subtotal_usd, 2),
            "hours": round(month_hours, 1),
            "internal_cost_usd": round(month_internal_cost, 2),
            "discount_pct": discount_pct,
            "discount_usd": round(discount_usd, 2),
            "net_usd": round(net_usd, 2),
        })
    return breakdown


def compute_quote(inputs: QuoteInputs) -> dict[str, Any]:
    """Build the full quote. The output mirrors the Summary Sheet shape."""
    if not inputs.project_types:
        raise ValueError("compute_quote requires at least one project_type")

    base_team = _merge_team_templates(inputs.project_types)
    team = _apply_role_overrides(base_team, inputs.role_overrides)
    team = _apply_effort_multipliers(team, inputs.effort_multipliers)

    months = _monthly_breakdown(team, inputs)
    gross_total = sum(m["gross_usd"] for m in months)
    ops_total = sum(m["ops_usd"] for m in months)
    contingency_total = sum(m["contingency_usd"] for m in months)
    subtotal_total = sum(m["subtotal_usd"] for m in months)
    discount_total = sum(m["discount_usd"] for m in months)
    net_total = sum(m["net_usd"] for m in months)
    hours_total = sum(m["hours"] for m in months)
    internal_cost_total = sum(m["internal_cost_usd"] for m in months)
    blended_rate = (net_total / hours_total) if hours_total else 0
    margin_pct = ((net_total - internal_cost_total) / net_total) if net_total else 0

    import internal_costs as _ic
    margin_block = {
        "gross_profit_usd": round(net_total - internal_cost_total, 2),
        "internal_cost_usd": round(internal_cost_total, 2),
        "margin_pct": round(margin_pct, 4),
        "band": _ic.margin_band(margin_pct),
        "thresholds": _ic.margin_thresholds(),
        "is_placeholder": _ic.is_placeholder_data(),
    }

    return {
        "inputs": {
            "project_types": inputs.project_types,
            "months": inputs.months,
            "phase_months": inputs.phase_months,
            "discount_first_half_pct": inputs.discount_pct_first_half,
            "currency": inputs.currency,
            "rate_card": inputs.rate_card,
            "project_ops_pct": inputs.project_ops_pct,
            "contingency_pct": inputs.contingency_pct,
        },
        "team": {role.strip(): by_phase for role, by_phase in team.items()},
        "monthly": months,
        "totals": {
            "gross_usd": round(gross_total, 2),
            "ops_usd": round(ops_total, 2),
            "contingency_usd": round(contingency_total, 2),
            "subtotal_usd": round(subtotal_total, 2),
            "discount_usd": round(discount_total, 2),
            "net_usd": round(net_total, 2),
            "hours": round(hours_total, 1),
            "blended_rate_usd_per_hour": round(blended_rate, 2),
        },
        "margin": margin_block,
    }


def role_catalogue() -> dict[str, dict[str, Any]]:
    """Public read of the rate book — for the UI to render."""
    return {
        role: {
            "rate_usd_per_hour": rate,
            "tier": "A" if rate >= 200 else "B",
        }
        for role, rate in ROLE_RATES_USD_PER_HOUR.items()
    }


def list_team_templates() -> dict[str, list[str]]:
    """Surface available templates for the UI."""
    return {key: sorted({r.strip() for r in tmpl}) for key, tmpl in TEAM_TEMPLATES.items()}
