"""
End-to-end qualification orchestrator.

qualify(name, url, overrides) is the single entrypoint Flask calls.
It owns the pipeline:
    Apollo enrichment -> map to ICP shape -> score -> signals -> fit summary
    -> stakeholder search -> packaged payload.

The output dict is designed to be the *only* thing the UI needs to render the
full qualification view — no follow-up server calls required.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import apollo
import ai_summary
import parent_detector
from scoring import (
    calculate_icp_score,
    check_hard_disqualifiers,
    identify_positive_signals,
    parse_revenue,
)
from config import OPPORTUNITY_TYPES


# ---------------------------------------------------------------------------
# Heuristics that translate Apollo data into the ICP shape `scoring.py` wants.
# ---------------------------------------------------------------------------

def _estimate_deal_size_gbp_month(annual_revenue_usd: float | None) -> tuple[int | None, str]:
    """Rough deal-size band derived from revenue. Returns (gbp/month, label)."""
    if not annual_revenue_usd:
        return None, "Estimated"
    if annual_revenue_usd >= 1_000_000_000:
        return 55_000, ">£50k/mo (est. from >$1B revenue)"
    if annual_revenue_usd >= 500_000_000:
        return 35_000, "£30k-£50k/mo (est. from $500M-$1B revenue)"
    if annual_revenue_usd >= 100_000_000:
        return 15_000, "£10k-£30k/mo (est. from $100M-$500M revenue)"
    return 5_000, "<£10k/mo (est. from <$100M revenue)"


_COMPLEXITY_HINT_TOKENS = {
    "multi_brand": ("multi-brand", "multibrand", "portfolio", "group", "brands"),
    "multi_market": ("global", "international", "multi-market", "worldwide", "markets", "countries"),
}


def _infer_complexity(org: dict) -> str:
    """Build a complexity hint string from Apollo industry/keywords/description."""
    haystack = " ".join(
        str(x or "").lower()
        for x in (
            org.get("industry"),
            org.get("short_description"),
            " ".join(org.get("keywords") or []),
        )
    )
    multi_brand = any(t in haystack for t in _COMPLEXITY_HINT_TOKENS["multi_brand"])
    multi_market = any(t in haystack for t in _COMPLEXITY_HINT_TOKENS["multi_market"])
    parts = []
    if multi_brand:
        parts.append("multi-brand")
    if multi_market:
        parts.append("multi-market")
    return ", ".join(parts) if parts else "single"


def _infer_vertical(org: dict) -> str:
    """Concatenate Apollo industry + top keywords so scoring.score_vertical can pattern-match."""
    parts = [org.get("industry") or ""]
    parts.extend(org.get("keywords") or [])
    return " ".join(p for p in parts if p)


def _region_label(org: dict) -> str:
    """Region hint string consumed by scoring.score_region (which fuzzy-matches)."""
    region = org.get("region")
    country = org.get("country")
    # If keywords/desc mention multiple regions, surface that for multi-region scoring.
    blob = " ".join(
        str(x or "").lower()
        for x in (org.get("short_description"), " ".join(org.get("keywords") or []))
    )
    multi = any(t in blob for t in ("global", "international", "worldwide", "europe and asia"))
    if multi:
        return f"Global ({country})"
    return f"{region} ({country})" if country else (region or "Unknown")


def _opportunity_play(opportunity_type: str) -> str:
    meta = OPPORTUNITY_TYPES.get(opportunity_type)
    return meta["play"] if meta else ""


def _generate_fit_summary(org: dict, score: dict, disqualifiers: list[str]) -> str:
    name = org.get("name") or "This company"
    revenue = org.get("annual_revenue_printed") or "unknown revenue"
    employees = org.get("estimated_num_employees")
    employees_str = f"{employees:,}" if employees else "unknown headcount"
    region = org.get("region") or "unknown region"
    vertical_label = score["breakdown"]["vertical"]["value"]
    opp_label = score["opportunity_label"]
    opp_desc = score["opportunity_description"]
    status = score["status_display"]
    normalized = score["normalized_score"]

    sentences = [
        f"{name} is a {vertical_label.lower()} business with {revenue} revenue and {employees_str} employees, primarily {region}.",
        f"Opportunity type: {opp_label} — {opp_desc}.",
        f"Status: {status} at {normalized}/10.",
    ]
    if disqualifiers:
        sentences.append("Hard disqualifiers in play: " + "; ".join(disqualifiers) + ".")
    return " ".join(sentences)


def _next_steps(score: dict, disqualifiers: list[str], stakeholders: list[dict]) -> list[str]:
    if disqualifiers:
        return [
            "Mark as Qualify Out — hard disqualifier in play.",
            "Capture rationale in Notion for partner team feedback loop.",
            "If status changes (e.g. Braze adoption), re-run qualification.",
        ]
    status = score["status"]
    opp_type = score["opportunity_type"]
    base_steps: list[str] = []
    if status == "qualify_in":
        base_steps.append("Book a 30-min intro call with the named champion.")
        if opp_type == "retention":
            base_steps.append("Lead with Braze optimisation + Hightouch CDP angle.")
        elif opp_type == "migration":
            base_steps.append("Open with migration risk-mitigation framework + Braze partner intro.")
        elif opp_type == "augmentation":
            base_steps.append("Lead with data layer (Hightouch + warehouse) to extract Braze value.")
        elif opp_type == "greenfield":
            base_steps.append("Lead with full Braze + Hightouch implementation proposal.")
        base_steps.append("Confirm budget cycle + signing authority during discovery.")
    elif status == "borderline":
        base_steps.append("Run a 30-min qualification call before investing further.")
        base_steps.append("Confirm tech stack (Braze? warehouse?) — current score may move with confirmation.")
        base_steps.append("Validate executive sponsor + budget timeline.")
    else:
        base_steps.append("Park lead — revisit if stack/intent signal changes.")

    if not stakeholders:
        base_steps.append("Stakeholder map missing — Apollo returned no decision-makers; manual LinkedIn dig required.")
    return base_steps


def _stakeholder_priority(person: dict) -> str:
    seniority = (person.get("seniority") or "").lower()
    title = (person.get("title") or "").lower()
    if any(t in title for t in ("cmo", "chief marketing")) or seniority in ("c_suite", "founder"):
        return "P1"
    if seniority in ("vp", "head") or "vp " in title or "head of" in title:
        return "P1"
    if seniority == "director":
        return "P2"
    return "P3"


def _stakeholder_why(person: dict) -> str:
    title = (person.get("title") or "").lower()
    if any(t in title for t in ("crm", "lifecycle")):
        return "Owns CRM/lifecycle — direct Braze stakeholder."
    if "growth" in title:
        return "Growth lead — owns activation and retention metrics."
    if any(t in title for t in ("marketing", "cmo")):
        return "Marketing leadership — economic buyer for CEP investment."
    if "data" in title:
        return "Data leadership — owns warehouse + Hightouch decisions."
    return "Influence on lifecycle/CRM agenda."


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

@dataclass
class QualificationOverrides:
    revenue: str | None = None
    employees: str | None = None
    vertical: str | None = None
    tech_stack: str | None = None
    complexity: str | None = None
    region: str | None = None
    deal_size: str | None = None
    stack_confidence: str = "confirmed"
    partner_source: str | None = None
    incumbent_agency: str | None = None
    rfp_active: bool = False
    budget_allocated: bool = False
    extra_signals: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict | None) -> "QualificationOverrides":
        d = d or {}
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def qualify(
    name: str,
    url: str,
    overrides: dict | None = None,
    *,
    apollo_cfg: apollo.ApolloConfig | None = None,
) -> dict:
    """End-to-end qualification. Returns a single payload safe to JSON-encode for the UI."""
    if not name or not url:
        raise ValueError("qualify requires both name and url")

    ov = QualificationOverrides.from_dict(overrides)
    org = apollo.enrich_organization(url, cfg=apollo_cfg)

    # Build the ICP-shape dict scoring.py expects, applying overrides last so
    # the user can always trump Apollo.
    tech_stack_str = ", ".join(org.get("technologies") or [])
    deal_size_gbp, deal_size_label = _estimate_deal_size_gbp_month(org.get("annual_revenue"))

    company_data: dict[str, Any] = {
        "revenue": org.get("annual_revenue") or org.get("annual_revenue_printed"),
        "employees": org.get("estimated_num_employees"),
        "vertical": _infer_vertical(org),
        "tech_stack": tech_stack_str,
        "complexity": _infer_complexity(org),
        "region": _region_label(org),
        "deal_size": deal_size_gbp,
        "stack_confidence": ov.stack_confidence,
        "incumbent_agency": ov.incumbent_agency,
        "rfp_active": ov.rfp_active,
        "budget_allocated": ov.budget_allocated,
        "source": ov.partner_source,
    }

    # Apply user overrides (they trump Apollo).
    for field_name in (
        "revenue", "employees", "vertical", "tech_stack", "complexity",
        "region", "deal_size",
    ):
        override_val = getattr(ov, field_name)
        if override_val not in (None, ""):
            company_data[field_name] = override_val

    score = calculate_icp_score(company_data)
    disqualifiers = check_hard_disqualifiers(company_data)
    signals = identify_positive_signals(company_data)
    signals.extend(ov.extra_signals or [])

    # Stakeholder discovery is best-effort. Apollo's people endpoints have
    # been less stable than org enrich (renames, rate limits) — letting a
    # 502 from people search kill the score would be the wrong tradeoff.
    try:
        stakeholders_raw = apollo.search_people(
            org_id=org.get("apollo_id"),
            org_domain=org.get("domain") or url,
            cfg=apollo_cfg,
        )
    except apollo.ApolloError as e:
        stakeholders_raw = []
        signals.append(f"Stakeholder lookup skipped (Apollo error: {str(e)[:120]})")
    stakeholders = [
        {
            "name": p["name"],
            "title": p["title"],
            "linkedin_url": p["linkedin_url"],
            "email_status": p["email_status"],
            "city": p["city"],
            "country": p["country"],
            "priority": _stakeholder_priority(p),
            "why": _stakeholder_why(p),
        }
        for p in stakeholders_raw
    ]

    heuristic_summary = _generate_fit_summary(org, score, disqualifiers)
    next_steps = _next_steps(score, disqualifiers, stakeholders)

    # Build the preliminary payload so the AI generator can see everything.
    preliminary = {
        "company": {"name": name, "url": url, "apollo": org},
        "discovered": {
            "revenue": org.get("annual_revenue_printed") or company_data["revenue"],
            "employees": org.get("estimated_num_employees"),
            "tech_stack": tech_stack_str,
            "complexity": company_data["complexity"],
            "region": company_data["region"],
        },
        "score": score,
        "signals": signals,
        "disqualifiers": disqualifiers,
        "opportunity": {
            "label": score["opportunity_label"],
            "play": _opportunity_play(score["opportunity_type"]),
        },
    }
    ai_text = ai_summary.generate_fit_summary(preliminary) if ai_summary.is_configured() else None
    fit_summary = ai_text or heuristic_summary
    summary_source = "ai" if ai_text else "heuristic"

    # v0.10.0 Phase B: detect possible parent group from Apollo enrichment.
    # Returns None for standalone accounts; the UI hides the suggestion banner
    # in that case. The AE always confirms before any link is created.
    suggested_parent = parent_detector.suggest_parent(org)

    return {
        "company": {
            "name": name,
            "url": url,
            "apollo": org,  # whole normalised payload incl. raw
        },
        "suggested_parent": suggested_parent,
        "discovered": {
            "revenue": org.get("annual_revenue_printed") or company_data["revenue"],
            "revenue_numeric": org.get("annual_revenue"),
            "employees": org.get("estimated_num_employees"),
            "vertical": org.get("industry"),
            "tech_stack": tech_stack_str,
            "complexity": company_data["complexity"],
            "region": company_data["region"],
            "deal_size_gbp_per_month": deal_size_gbp,
            "deal_size_label": deal_size_label,
            "incumbent_agency": ov.incumbent_agency,
            "stub": bool(org.get("_stub")),
        },
        "score": score,
        "signals": signals,
        "disqualifiers": disqualifiers,
        "fit_summary": fit_summary,
        "fit_summary_source": summary_source,
        "next_steps": next_steps,
        "opportunity": {
            "type": score["opportunity_type"],
            "label": score["opportunity_label"],
            "description": score["opportunity_description"],
            "play": _opportunity_play(score["opportunity_type"]),
        },
        "stakeholders": stakeholders,
        "meddicc": {
            # MEDDPICC — 8 criteria. Empty by default; UI fills in.
            # Keyed as `meddicc` for backward payload-shape compatibility.
            "metrics": {"value": "", "status": "not_started"},
            "economic_buyer": {"value": "", "status": "not_started"},
            "decision_criteria": {"value": "", "status": "not_started"},
            "decision_process": {"value": "", "status": "not_started"},
            "paper_process": {"value": "", "status": "not_started"},
            "identify_pain": {"value": "", "status": "not_started"},
            "champion": {"value": "", "status": "not_started"},
            "competition": {"value": "", "status": "not_started"},
        },
        "notes": "",
        "project_scope": "",
        # Partner sourcing — both directions.
        # opportunity_source: who brought this lead TO us (single value).
        # sourced_for_partners: which partners we're sourcing this account FOR (multi).
        "opportunity_source": ov.partner_source or "",
        "sourced_for_partners": [],
    }


if __name__ == "__main__":
    import json
    import os
    os.environ.setdefault("APOLLO_USE_FIXTURES", "1")
    result = qualify("Deliveroo", "deliveroo.co.uk")
    print(json.dumps({
        "score": result["score"]["normalized_score"],
        "status": result["score"]["status_display"],
        "opportunity": result["opportunity"]["label"],
        "discovered": result["discovered"],
        "fit_summary": result["fit_summary"],
        "stakeholder_count": len(result["stakeholders"]),
        "signals": result["signals"],
        "disqualifiers": result["disqualifiers"],
    }, indent=2, default=str))
