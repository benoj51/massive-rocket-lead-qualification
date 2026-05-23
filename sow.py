"""
Statement of Work renderer (v1.0.0ai).

v1.0.0ai: rewritten to comply with the MR SOW Training Brief
(May 2026). Every section that the brief flags as mandatory is
emitted: Document Status table, Opening Clause, Timing & Fees,
Executive Summary, Services In/Out of Scope, Commercial Summary
(with 80% consumption + 10% contingency + blended rate clauses),
Project Management, Monitoring Progress, Company's Participation,
Variations & Change in Scope, Changes of Date, General Notes &
Assumptions, Signatures (Thierry Sequeira as MR Director), and
Annex 1: Change Order template.

Snapshot-based, button-triggered. The AE clicks Draft SOW in Project
Build → this module reads the *current* Apollo + scope + pricing
state, freezes it into a versioned snapshot, and emits a print-
friendly HTML page the AE can review + download as PDF.

A snapshot does NOT update when scope or pricing change afterward.
Each version is immutable. Re-clicking Draft SOW creates a new version.

A separate dry-run preview path (build_snapshot + render_html, no
save) powers the "Preview without saving" button so the AE can
iterate before committing a version.

Public surface:
    build_snapshot(lead_id)              -> dict   (full snapshot)
    render_html(snapshot, version)       -> str    (printable HTML)
    compliance_check(snapshot)           -> dict   (warnings + checklist)
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html import escape
from typing import Any

import pricing
import project_store
import scope as scope_module


# ===========================================================================
# Boilerplate text (verbatim per training brief Section 4 + Section 6)
# ===========================================================================

# Legal entity for MR. Override via env if MR's registered name changes.
MR_LEGAL_ENTITY  = "Massive Rocket Limited"
MR_SHORT_NAME    = "Consultant"
MR_SIGNATORY     = "Thierry Sequeira"
MR_SIGNATORY_ROLE = "Director"

# Brief Section 2.3 — Out of Scope: must always include creative,
# engineering, external documentation. Brief Section 3.3 also requires
# platform training to be explicitly excluded.
OUT_OF_SCOPE_BOILERPLATE = [
    "Platform training (Braze, Hightouch, Snowflake, etc.) — delivered by the "
    "platform vendor or the Client's TAM, not Massive Rocket.",
    "Creative Services — concepting, copywriting, design production, asset "
    "creation (covered separately by a Creative SOW when required).",
    "Engineering — application development, custom backend integrations, "
    "production codebase changes (covered separately by an Engineering SOW).",
    "External Documentation — knowledge-base articles, end-user help content, "
    "client-facing playbooks beyond internal handover material.",
    "Hardware procurement, infrastructure hosting fees, and third-party "
    "tooling licences.",
    "Translation or localisation work beyond the languages agreed at kick-off.",
    "On-site presence outside the kick-off and quarterly review days.",
    "Support, maintenance, or new feature delivery after the Acceptance Date "
    "(covered separately by a managed services agreement).",
]

# Brief Section 4.3 — General Notes & Assumptions: required clauses
# (LinkedIn case-study, software licence exclusion, 10% annual fee
# increase clause).
ASSUMPTIONS_BOILERPLATE = [
    "Pricing assumes the team allocation in the Commercial Summary above; any "
    "change in volume, channel mix, or scope post-signature triggers a Change "
    "Order via Annex 1.",
    "Hours quoted are based on an availability window of 0900–1800 UK time, "
    "Monday to Friday, excluding UK bank holidays. Remote-first delivery; "
    "on-site presence is limited to kick-off and quarterly reviews unless "
    "explicitly scoped.",
    "The Company agrees to make a named project owner available for weekly "
    "steering reviews and to respond to Massive Rocket requests within two "
    "business days.",
    "Third-party software licence fees (Braze, Hightouch, Snowflake, "
    "mParticle, Talon.One, etc.) are billed to the Company directly and are "
    "NOT included in the Consultant's fees under this Statement of Work.",
    "All deliverables and source materials produced under this SOW transfer "
    "to the Company on full payment of fees.",
    "Subject to the Company's prior written approval, Massive Rocket may "
    "reference the engagement on its LinkedIn profile and in client-anonymised "
    "case-study material. Logo usage requires separate written approval.",
    "Fees stated apply for the initial twelve (12) months of the engagement. "
    "Massive Rocket reserves the right to increase fees by up to 10% per "
    "annum on ninety (90) days' written notice to reflect inflation and rate-"
    "card revisions.",
]

# Brief Section 4.3 — Commercial Summary required clauses. These are
# legal text; do not paraphrase without input from MR legal.
COMMERCIAL_CLAUSE_80PCT = (
    "Massive Rocket will notify the Company in writing when fees consumed "
    "reach eighty percent (80%) of the agreed budget. This notification "
    "triggers a formal review of remaining scope, pacing, and any necessary "
    "Change Order. Massive Rocket reserves the right to pause work upon "
    "reaching one hundred percent (100%) of the agreed budget pending "
    "Company approval of additional spend."
)
COMMERCIAL_CLAUSE_CONTINGENCY = (
    "The fees set out above include a ten percent (10%) contingency buffer "
    "to absorb the typical level of in-flight refinement that occurs on "
    "engagements of this nature. Material scope changes — defined as work "
    "outside the Services In Scope above — are NOT covered by this buffer "
    "and require a Change Order via Annex 1."
)
COMMERCIAL_CLAUSE_BLENDED_RATE_TPL = (
    "The fees above are calculated against a blended rate of "
    "{symbol}{rate:.0f} {currency} per hour, derived from the role mix and "
    "phase weighting shown in the Team appendix. The Consultant's standard "
    "rate card otherwise applies at {symbol}{full_rate:.0f} {currency} per hour."
)

# Brief Section 2.3 — Project Management section: agile delivery,
# weekly reviews, client participation.
PROJECT_MANAGEMENT_CLAUSE = (
    "Delivery follows an iterative, agile cadence: a five-day planning "
    "cycle for in-flight workstreams, weekly steering reviews with the "
    "Company's project owner, fortnightly delivery readouts to the "
    "Company's executive sponsor, and a monthly RACI + risk-log refresh. "
    "The Consultant uses Jira (or a Company-nominated equivalent) as the "
    "shared work-tracking system; every deliverable receives a work-item-"
    "level sign-off recorded in the audit trail. The Company will "
    "nominate a single point of accountability for sign-offs; in their "
    "absence, the named executive sponsor stands in."
)

# Brief Section 2.3 — Monitoring Progress: standard legal language.
MONITORING_PROGRESS_CLAUSE = (
    "Massive Rocket will notify the Company in writing without undue "
    "delay of any anticipated risk to the delivery schedule, scope, or "
    "fees. The Company will likewise notify the Consultant of any "
    "anticipated change in its own commitments — including dependency "
    "delivery, named resource availability, and decision-making "
    "timelines — that may affect the engagement."
)

# Brief Section 2.3 — Company's Participation: critical risk
# protection clause. Always included verbatim.
COMPANYS_PARTICIPATION_CLAUSE = (
    "The Consultant's ability to deliver the Services depends on the "
    "Company's timely fulfilment of its participation obligations, "
    "including: provision of platform access (Braze, Hightouch, "
    "Snowflake or equivalent) within five (5) business days of kick-off; "
    "nomination of a single project owner; participation in the weekly "
    "steering review; provision of brand, content, and data assets in "
    "the formats agreed at kick-off; and timely sign-off on deliverables "
    "(within five (5) business days of submission). Delays in the "
    "Company's participation that materially impact the schedule will "
    "be handled under the Changes of Date clause below."
)

# Brief Section 2.3 — Variations & Change in Scope: must reference
# Annex 1.
VARIATIONS_CLAUSE = (
    "Any change to the Services In Scope, the Commercial Summary, the "
    "Team composition, or the agreed delivery dates must be agreed "
    "between the parties via a Change Order following the template at "
    "Annex 1 of this Statement of Work. Verbal agreements, email "
    "exchanges, and informal Slack / meeting notes do not constitute a "
    "Change Order. No additional work commences until the Change Order "
    "is countersigned by both parties."
)

# Brief Section 2.3 — Changes of Date: standard text only.
CHANGES_OF_DATE_CLAUSE = (
    "If delivery dates are affected by Company-caused delay — including "
    "but not limited to delayed access, delayed sign-off, dependency "
    "slippage, or change in named resource availability — Massive Rocket "
    "will work with the Company in good faith to re-baseline the "
    "schedule. The Consultant reserves the right to re-quote affected "
    "workstreams should the delay materially impact resource allocation "
    "or third-party scheduling commitments."
)

# Brief Section 2.3 + Annex 1: Change Order template.
ANNEX_1_CHANGE_ORDER_TEMPLATE = {
    "title": "Annex 1 — Change Order Template",
    "intro": (
        "This Annex sets out the mechanism for adding, removing, or "
        "modifying scope under this Statement of Work. Every change — no "
        "matter how small — uses this template. Verbal additions are not "
        "binding until executed via a Change Order."
    ),
    "fields": [
        ("Change Order Number",   "CO-NNN (assigned sequentially)"),
        ("Date Raised",           "DD MMM YYYY"),
        ("Raised By",             "Name · Title · Company"),
        ("Affected Workstream",   "Reference the Services In Scope row(s) impacted"),
        ("Description of Change", "What is being added / removed / modified"),
        ("Rationale",             "Why the change is needed"),
        ("Impact — Scope",        "New deliverables / removed deliverables"),
        ("Impact — Schedule",     "Net change in days; revised milestone dates"),
        ("Impact — Commercials",  "Net change in fees; updated total contract value"),
        ("Impact — Team",         "Role changes; named-resource implications"),
        ("Acceptance",            "Signatures from both Company and Consultant; date of effect"),
    ],
}

# Brief Section 4.3 — Blended rates by currency.
BLENDED_RATE_BY_CURRENCY = {
    "GBP": {"symbol": "£", "blended": 150, "full": 163},
    "EUR": {"symbol": "€", "blended": 175, "full": 190},
    "USD": {"symbol": "$", "blended": 200, "full": 220},
}


# ===========================================================================
# Builder
# ===========================================================================

def _safe_load_apollo(lead_id: str) -> dict[str, Any]:
    """Best-effort: SOW should still render if Apollo cache is empty."""
    try:
        import apollo
        org = apollo.enrich_organization(lead_id)
        return org or {}
    except Exception:
        return {}


def _today_long() -> str:
    """Per brief Section 2.1: 'DD MMM YYYY' format."""
    return datetime.now(timezone.utc).strftime("%d %b %Y")


def _naming_convention(client_name: str) -> str:
    """Per brief Section 2.1: 'Appendix A — [Client] Statement of Work
    — DD MMM YYYY'."""
    return f"Appendix A — {client_name} — Statement of Work — {_today_long()}"


def _document_status_default() -> dict[str, Any]:
    """Per brief Section 2.2: status table at top of every draft."""
    return {
        "status": "Draft",
        "next_steps_client": "Review and provide feedback by [date]; confirm "
                              "MSA date + legal entity name.",
        "next_steps_mr":     "PM review (Billy / Matt) for completeness, RACI "
                              "accuracy, commercial consistency, risk coverage.",
        "remove_before_export": True,
    }


def _opening_clause(client_name: str, msa_date: str | None) -> str:
    """Per brief Section 2.3: references exact MSA date, names both
    legal entities correctly. msa_date is supplied by the AE; if None
    we leave a placeholder + flag it as a compliance warning."""
    msa_ref = msa_date or "[MSA DATE PENDING]"
    return (
        f"This Statement of Work (the \"SOW\") is entered into between "
        f"{MR_LEGAL_ENTITY} (the \"{MR_SHORT_NAME}\") and {client_name} (the "
        f"\"Company\"), and forms part of the Master Services Agreement "
        f"between the parties dated {msa_ref} (the \"MSA\"). In the event "
        f"of conflict between this SOW and the MSA, the terms of the MSA "
        f"prevail save where this SOW expressly states otherwise. The "
        f"Services described herein commence on the date set out under "
        f"Timing & Fees below."
    )


def _timing_and_fees(currency: str, start_date: str | None,
                      months: int) -> dict[str, Any]:
    """Per brief Section 2.3: currency must be specified; start date
    must be a real date, not TBC."""
    return {
        "currency": (currency or "GBP").upper(),
        "start_date": start_date or "",   # validated in compliance_check
        "duration_months": months,
    }


def _executive_summary(project, apollo_org: dict, quote: dict) -> str:
    """Per brief Section 2.3: client-specific (no copy-paste from
    another SOW). Includes a Project Timeline anchor."""
    name = project.company_name
    streams = [
        scope_module.PROJECT_TYPES.get(s.project_type, {}).get("label", s.project_type)
        for s in project.streams
    ]
    streams_str = ""
    if streams:
        if len(streams) > 1:
            streams_str = ", ".join(streams[:-1]) + " and " + streams[-1]
        else:
            streams_str = streams[0]
    industry = apollo_org.get("industry") or "consumer marketing"
    total = quote["totals"]["net_usd"]
    months = quote["inputs"]["months"]
    return (
        f"This engagement delivers a {streams_str.lower()} programme for {name}, "
        f"an industry leader in {industry.lower()}. Massive Rocket's role is to "
        f"establish the data foundation, stakeholder rhythm, and operational "
        f"discipline needed for {name} to compound value across the full "
        f"customer lifecycle. The work runs across {months} months — split into "
        f"Understand, Execute, and Accelerate phases — for a total investment "
        f"of approximately ${total:,.0f}. The Project Timeline below sets out "
        f"the major milestones; the Services In Scope section details exactly "
        f"what the Consultant will deliver."
    )


def _project_timeline_rows(quote: dict) -> list[dict[str, Any]]:
    """Per brief Section 2.3: 'Project Timeline table' in the
    Executive Summary. Derived from phase_months on the quote."""
    pm = quote["inputs"]["phase_months"]
    rows = []
    m = 1
    for phase in ("Understand", "Execute", "Accelerate"):
        n = pm.get(phase, 0)
        if n <= 0:
            continue
        rows.append({
            "phase": phase,
            "months": f"M{m}–M{m + n - 1}" if n > 1 else f"M{m}",
            "duration": f"{n} month{'s' if n != 1 else ''}",
            "headline": _phase_headline(phase),
        })
        m += n
    return rows


def _phase_headline(phase: str) -> str:
    return {
        "Understand":  "Discovery, data foundation, audience definition, "
                       "lifecycle blueprint.",
        "Execute":     "Channel build-out, campaign delivery, "
                       "measurement instrumentation, RACI rhythm.",
        "Accelerate":  "Optimisation, expansion to adjacent channels, "
                       "year-2 roadmap.",
    }.get(phase, "")


def _engagement_overview(project, apollo_org: dict) -> dict[str, Any]:
    return {
        "background": apollo_org.get("short_description") or "",
        "industry": apollo_org.get("industry") or "",
        "region": apollo_org.get("region") or "",
        "estimated_employees": apollo_org.get("estimated_num_employees"),
        "annual_revenue": apollo_org.get("annual_revenue_printed"),
        "stream_labels": [
            {
                "key": s.project_type,
                "label": scope_module.PROJECT_TYPES.get(s.project_type, {}).get("label", s.project_type),
                "description": scope_module.PROJECT_TYPES.get(s.project_type, {}).get("description", ""),
            }
            for s in project.streams
        ],
    }


def _scope_of_work(project) -> list[dict[str, Any]]:
    """Per brief Section 4.2: every service row must have a meaningful
    description. Unqualified items are NOT promised — they surface
    only as open questions on the discovery list.
    """
    out = []
    library = {pt: {c["key"]: c for c in criteria}
               for pt, criteria in scope_module.criteria_library().items()}
    for stream in project.streams:
        spec_lib = library.get(stream.project_type, {})
        in_scope_lines: list[dict[str, str]] = []
        open_questions: list[dict[str, str]] = []
        for ans in stream.criteria:
            crit_def = spec_lib.get(ans.key)
            label = crit_def["label"] if crit_def else ans.key
            description = (crit_def.get("description") if crit_def else "") or ""
            entry = {
                "label": label,
                "value": (ans.value or "").strip(),
                "description": description,
            }
            if ans.status == "qualified":
                entry["confirmed"] = True
                in_scope_lines.append(entry)
            elif ans.status == "qualifying":
                entry["confirmed"] = False
                in_scope_lines.append(entry)
            elif (ans.value or "").strip():
                open_questions.append(entry)
        out.append({
            "project_type": stream.project_type,
            "label": scope_module.PROJECT_TYPES.get(stream.project_type, {}).get("label", stream.project_type),
            "in_scope": in_scope_lines,
            "open_questions": open_questions,
        })
    return out


def _team_and_phases(quote: dict) -> dict[str, Any]:
    return {
        "team_fte": quote["team"],
        "hours_total": quote["totals"]["hours"],
        "phases": list(pricing.PHASES),
        "phase_months": quote["inputs"]["phase_months"],
    }


def _investment_summary(quote: dict) -> dict[str, Any]:
    return {
        "currency": quote["inputs"]["currency"],
        "months": quote["inputs"]["months"],
        "totals": quote["totals"],
        "monthly": quote["monthly"],
    }


def _blended_rate_clause(currency: str) -> str:
    """Format the brief's required blended-rate text using the currency
    of the SOW. Falls back to GBP if unknown."""
    rates = BLENDED_RATE_BY_CURRENCY.get((currency or "GBP").upper(),
                                          BLENDED_RATE_BY_CURRENCY["GBP"])
    return COMMERCIAL_CLAUSE_BLENDED_RATE_TPL.format(
        symbol=rates["symbol"], rate=rates["blended"],
        currency=(currency or "GBP").upper(), full_rate=rates["full"],
    )


# ===========================================================================
# Compliance — surfaces brief-rule violations in the preview
# ===========================================================================

# Brief Section 4: hard rules. The check function returns a list of
# warnings (each: {severity, code, message}) + a checklist of brief
# Section 5 items with their status.

_COMPLIANCE_CHECKLIST = [
    ("naming",              "Naming convention correct (Appendix A — [Client] SOW — DD MMM YYYY)"),
    ("doc_status",          "Document Status table populated"),
    ("opening_msa",         "Opening clause references real MSA date + legal entities"),
    ("currency",            "Currency confirmed and stated (GBP / EUR / USD)"),
    ("start_date",          "Commencement date confirmed (no TBC)"),
    ("exec_summary",        "Executive Summary present + client-specific"),
    ("project_timeline",    "Project Timeline table present"),
    ("services_in_scope",   "Services In Scope populated (no empty streams)"),
    ("services_out_scope",  "Services Out of Scope section included"),
    ("commercial_built",    "Commercial Summary built from pricing calculator"),
    ("blended_rate",        "Blended rate stated"),
    ("clause_80pct",        "80% consumption notification clause included"),
    ("clause_contingency",  "10% contingency buffer clause included"),
    ("clause_annual_inc",   "10% annual fee increase clause included"),
    ("project_management",  "Project Management section included"),
    ("monitoring",          "Monitoring Progress section included"),
    ("company_participation", "Company's Participation section included"),
    ("variations",          "Variations & Change in Scope section included"),
    ("changes_of_date",     "Changes of Date section included"),
    ("general_notes",       "General Notes & Assumptions includes LinkedIn + licence exclusion"),
    ("signatures",          "Signature blocks present (Company + Massive Rocket)"),
    ("annex_1",             "Annex 1: Change Order template included"),
    ("no_tbc_commercials",  "No TBC in commercial / resourcing / deliverable fields"),
]


def compliance_check(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return warnings + checklist for a snapshot. Used by the preview
    to render the compliance side panel."""
    warnings: list[dict[str, str]] = []
    checks: dict[str, bool] = {k: True for k, _ in _COMPLIANCE_CHECKLIST}

    sections = snapshot.get("sections", {})

    # Naming
    naming = snapshot.get("naming_convention") or ""
    if not re.match(r"^Appendix A — .+ — Statement of Work — \d{2} \w{3} \d{4}$", naming):
        checks["naming"] = False
        warnings.append({"severity": "high", "code": "naming",
                          "message": "Naming convention doesn't match the "
                                     "required 'Appendix A — [Client] Statement "
                                     "of Work — DD MMM YYYY' pattern."})

    # Document Status
    ds = snapshot.get("document_status") or {}
    if not ds.get("status"):
        checks["doc_status"] = False
        warnings.append({"severity": "med", "code": "doc_status",
                          "message": "Document Status table is missing."})

    # Opening clause — flag if it still contains the placeholder
    opening = sections.get("opening_clause") or ""
    if "[MSA DATE PENDING]" in opening:
        checks["opening_msa"] = False
        warnings.append({"severity": "high", "code": "opening_msa",
                          "message": "Opening Clause is missing the MSA date. "
                                     "Confirm with the AE + populate before "
                                     "sending externally."})

    # Timing & fees
    tf = sections.get("timing_and_fees") or {}
    if not tf.get("currency"):
        checks["currency"] = False
        warnings.append({"severity": "high", "code": "currency",
                          "message": "Currency not specified."})
    if not (tf.get("start_date") or "").strip():
        checks["start_date"] = False
        warnings.append({"severity": "high", "code": "start_date",
                          "message": "Commencement date is empty. Confirm "
                                     "with the AE — no TBC allowed."})

    # Services In Scope — flag if every stream is empty
    scope = sections.get("scope_of_work") or []
    if not scope or all(not s.get("in_scope") for s in scope):
        checks["services_in_scope"] = False
        warnings.append({"severity": "high", "code": "services_in_scope",
                          "message": "Services In Scope is empty across all "
                                     "streams — qualify some criteria before "
                                     "drafting."})

    # Out of Scope
    if not sections.get("out_of_scope"):
        checks["services_out_scope"] = False
        warnings.append({"severity": "high", "code": "services_out_scope",
                          "message": "Services Out of Scope is missing."})

    # Commercial Summary
    inv = sections.get("investment") or {}
    if not inv.get("totals", {}).get("net_usd"):
        checks["commercial_built"] = False
        warnings.append({"severity": "high", "code": "commercial_built",
                          "message": "Commercial Summary has no net total — "
                                     "did pricing build successfully?"})

    # Project Timeline
    if not (sections.get("project_timeline") or []):
        checks["project_timeline"] = False
        warnings.append({"severity": "med", "code": "project_timeline",
                          "message": "Project Timeline table is empty."})

    # TBC anywhere in scope values
    tbc_re = re.compile(r"\bTBC\b|\btbc\b|\btbd\b", re.IGNORECASE)
    tbc_hits = []
    for stream in scope:
        for item in stream.get("in_scope", []):
            if tbc_re.search(item.get("value", "")):
                tbc_hits.append(f"{stream.get('label', '')} · {item.get('label', '')}")
    if tbc_hits:
        checks["no_tbc_commercials"] = False
        warnings.append({"severity": "high", "code": "no_tbc_commercials",
                          "message": f"TBC found in {len(tbc_hits)} scope "
                                     f"value(s): {'; '.join(tbc_hits[:3])}"
                                     f"{' …' if len(tbc_hits) > 3 else ''}. "
                                     f"Brief Section 3.1 — resolve before issuing."})

    # The remaining checklist items are emitted by build_snapshot
    # itself, so they're True by construction (we always include the
    # standard clauses). Visibility for the checklist is still useful.
    return {
        "warnings": warnings,
        "checklist": [
            {"key": k, "label": label, "passed": checks[k]}
            for k, label in _COMPLIANCE_CHECKLIST
        ],
        "passed": sum(1 for v in checks.values() if v),
        "total": len(checks),
    }


# ===========================================================================
# Builder — full snapshot
# ===========================================================================

def build_snapshot(
    lead_id: str, *, months: int = 12,
    discount_first_half: float = 0.15,
    discount_second_half: float = 0.0,
    msa_date: str | None = None,
    start_date: str | None = None,
    currency: str | None = None,
    company_legal_name: str | None = None,
) -> dict[str, Any]:
    """Freeze current state into a SOW snapshot dict.

    v1.0.0ai: includes every section the training brief mandates.
    msa_date, start_date, currency, company_legal_name can be supplied
    by the caller; if absent we leave placeholders + flag in compliance.

    Raises ValueError if there's no project on file for the lead.
    """
    project = project_store.load(lead_id)
    if project is None:
        raise ValueError(f"No project found for lead_id={lead_id!r}")

    apollo_org = _safe_load_apollo(lead_id)
    company_name = company_legal_name or project.company_name

    multipliers = scope_module.role_drivers_for_project(project)
    quote = pricing.compute_quote(pricing.QuoteInputs(
        project_types=[s.project_type for s in project.streams],
        months=months,
        discount_pct_first_half=discount_first_half,
        discount_pct_second_half=discount_second_half,
        effort_multipliers=multipliers,
    ))

    # Roadmap is optional — render only if the AE built one.
    roadmap_block = None
    try:
        import roadmap as roadmap_module
        rm = roadmap_module.load(lead_id)
        roadmap_block = roadmap_module.to_dict(rm) if rm else None
    except Exception:
        pass

    effective_currency = (currency or quote["inputs"]["currency"] or "GBP").upper()

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "lead_id": lead_id,
        "company_name": company_name,
        "naming_convention": _naming_convention(company_name),
        "document_status": _document_status_default(),
        "validation_status_at_generation": project.validation_status,
        "validation_notes_at_generation": project.validation_notes,
        "summary": scope_module.project_summary(project),
        "sections": {
            "opening_clause":           _opening_clause(company_name, msa_date),
            "timing_and_fees":          _timing_and_fees(effective_currency, start_date, months),
            "executive_summary":        _executive_summary(project, apollo_org, quote),
            "project_timeline":         _project_timeline_rows(quote),
            "engagement_overview":      _engagement_overview(project, apollo_org),
            "scope_of_work":            _scope_of_work(project),
            "out_of_scope":             list(OUT_OF_SCOPE_BOILERPLATE),
            "team_and_phases":          _team_and_phases(quote),
            "investment":               _investment_summary(quote),
            "commercial_clauses": {
                "blended_rate":          _blended_rate_clause(effective_currency),
                "consumption_80pct":     COMMERCIAL_CLAUSE_80PCT,
                "contingency":           COMMERCIAL_CLAUSE_CONTINGENCY,
            },
            "project_management":       PROJECT_MANAGEMENT_CLAUSE,
            "monitoring_progress":      MONITORING_PROGRESS_CLAUSE,
            "companys_participation":   COMPANYS_PARTICIPATION_CLAUSE,
            "variations":               VARIATIONS_CLAUSE,
            "changes_of_date":          CHANGES_OF_DATE_CLAUSE,
            "assumptions":              list(ASSUMPTIONS_BOILERPLATE),
            "roadmap":                  roadmap_block,
            "annex_1_change_order":     dict(ANNEX_1_CHANGE_ORDER_TEMPLATE),
        },
        "signatory_mr": {
            "name":  MR_SIGNATORY,
            "role":  MR_SIGNATORY_ROLE,
            "entity": MR_LEGAL_ENTITY,
        },
    }

    snapshot["compliance"] = compliance_check(snapshot)
    return snapshot


# ===========================================================================
# HTML renderer
# ===========================================================================

_HTML_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>{title}</title>
<style>
  @page {{ size: A4; margin: 18mm 16mm; }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: Georgia, "Times New Roman", serif;
    color: #1a1a24; background: #f6f6f0; margin: 0;
    line-height: 1.5;
  }}
  .layout {{ display: grid; grid-template-columns: 1fr 280px; gap: 24px; max-width: 1180px; margin: 24px auto; padding: 0 16px; align-items: start; }}
  .page {{
    background: #ffffff; border: 1px solid #d8d4c8;
    box-shadow: 0 10px 30px rgba(0,0,0,.08);
    padding: 36px 44px;
  }}
  .sidepanel {{
    position: sticky; top: 64px;
    background: #ffffff; border: 1px solid #d8d4c8;
    border-radius: 6px; padding: 14px 16px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 12px;
  }}
  .sidepanel h4 {{ margin: 0 0 6px; font-size: 12px; text-transform: uppercase;
                  letter-spacing: .08em; color: #6a4a2c; }}
  .sidepanel .warn {{ background: #fde2e2; border-left: 3px solid #8b1f1f;
                     padding: 6px 8px; margin: 6px 0; font-size: 11px; }}
  .sidepanel .warn.med {{ background: #fff3d1; border-left-color: #876300; }}
  .sidepanel ul.chk {{ list-style: none; padding: 0; margin: 8px 0 0;
                       font-size: 11px; }}
  .sidepanel ul.chk li {{ padding: 2px 0; display: flex; gap: 6px; }}
  .sidepanel ul.chk li.pass::before {{ content: '✓'; color: #1f7a3f; }}
  .sidepanel ul.chk li.fail::before {{ content: '✗'; color: #b91c1c; }}
  h1 {{ font-size: 28px; margin: 0 0 4px; letter-spacing: .01em; }}
  h2 {{ font-size: 16px; margin: 28px 0 8px; text-transform: uppercase;
       letter-spacing: .08em; color: #6a4a2c; border-bottom: 1px solid #e3decf;
       padding-bottom: 4px; }}
  h3 {{ font-size: 14px; margin: 18px 0 6px; color: #2a2a3a; }}
  p {{ margin: 6px 0; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 12px; }}
  th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #e6e2d5;
            vertical-align: top; }}
  th {{ font-size: 10px; text-transform: uppercase; letter-spacing: .06em;
       color: #6a4a2c; }}
  ul {{ margin: 6px 0 8px 18px; }}
  li {{ margin: 3px 0; }}
  .meta {{ color: #6a6a80; font-size: 11px; }}
  .pill {{ display: inline-block; padding: 1px 8px; border-radius: 12px;
          font-size: 10px; background: #efe9db; color: #6a4a2c; margin-left: 6px; }}
  .pill.qualifying {{ background: #fff3d1; color: #876300; }}
  .pill.warn {{ background: #fde2e2; color: #8b1f1f; }}
  .pill.draft {{ background: #fde2e2; color: #8b1f1f; }}
  .totals {{ background: #faf6ec; border: 1px solid #e3decf; padding: 12px 16px; margin: 12px 0; }}
  .totals .row {{ display: flex; justify-content: space-between; padding: 3px 0; }}
  .totals .row.grand {{ font-weight: 700; border-top: 1px solid #d8d4c8;
                       margin-top: 6px; padding-top: 8px; font-size: 15px; }}
  .signatures {{ display: grid; grid-template-columns: 1fr 1fr; gap: 32px; margin-top: 36px; }}
  .sigblock {{ border-top: 1px solid #1a1a24; padding-top: 6px; font-size: 11px; }}
  .doc-status-table {{ background: #fde2e2; border: 1px solid #f1c0c0;
                       padding: 10px 12px; margin: 10px 0 18px; }}
  .doc-status-table .row {{ display: flex; gap: 12px; font-size: 12px;
                            padding: 2px 0; }}
  .doc-status-table .row .lbl {{ min-width: 160px; color: #8b1f1f;
                                 font-weight: 600; text-transform: uppercase;
                                 letter-spacing: .04em; font-size: 10px; }}
  .toolbar {{
    position: sticky; top: 0; z-index: 50;
    background: #2a2a3a; color: #fff; padding: 10px 16px;
    display: flex; justify-content: space-between; align-items: center;
  }}
  .toolbar a, .toolbar button {{
    background: #e82b23; color: #fff; border: 0; padding: 6px 14px;
    border-radius: 6px; font-size: 13px; cursor: pointer; text-decoration: none;
    margin-left: 8px;
  }}
  .toolbar .meta {{ color: #c9c9d4; font-size: 11px; }}
  .non-binding-banner {{ background: #fff3d1; border: 1px solid #f0d68b;
                         padding: 8px 12px; margin: 14px 0; font-size: 12px;
                         color: #876300; border-radius: 4px; }}
  @media print {{
    .toolbar, .sidepanel {{ display: none; }}
    body {{ background: #ffffff; }}
    .layout {{ display: block; max-width: none; padding: 0; margin: 0; }}
    .page {{ box-shadow: none; border: 0; margin: 0; padding: 0; }}
    .doc-status-table {{ display: none; }}   /* never export with draft status */
  }}
</style>
</head>
<body>
<div class="toolbar">
  <div>Statement of Work · v{version}<span class="meta"> · generated {generated_at}</span></div>
  <div>
    <button onclick="window.print()" type="button">Print / Save as PDF</button>
  </div>
</div>
<div class="layout">
<article class="page">
"""

_HTML_FOOT = """
</article>
{sidepanel}
</div>
</body>
</html>
"""


def _render_table(rows: list[dict[str, Any]], cols: list[tuple[str, str]]) -> str:
    head = "".join(f"<th>{escape(label)}</th>" for _, label in cols)
    body = []
    for r in rows:
        body.append("<tr>" + "".join(
            f"<td>{escape(str(r.get(key, '')))}</td>" for key, _ in cols
        ) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _render_side_panel(snapshot: dict[str, Any]) -> str:
    """Compliance side panel — visible in preview, hidden on print."""
    c = snapshot.get("compliance", {})
    warnings = c.get("warnings", [])
    checklist = c.get("checklist", [])
    passed = c.get("passed", 0)
    total = c.get("total", 0)
    warn_html = "".join(
        f'<div class="warn {"med" if w["severity"] == "med" else ""}">'
        f'<strong>{escape(w["code"].replace("_", " ").title())}</strong>: '
        f'{escape(w["message"])}</div>'
        for w in warnings
    ) or '<div class="meta">No warnings.</div>'
    checks_html = "".join(
        f'<li class="{"pass" if item["passed"] else "fail"}">{escape(item["label"])}</li>'
        for item in checklist
    )
    return f"""
<aside class="sidepanel">
  <h4>Brief compliance · {passed}/{total}</h4>
  <div>{warn_html}</div>
  <h4 style="margin-top:14px;">Pre-export checklist</h4>
  <ul class="chk">{checks_html}</ul>
  <div class="meta" style="margin-top:10px;font-size:10px;">Hidden when printed.</div>
</aside>
"""


def render_html(snapshot: dict[str, Any], version: int) -> str:
    sections = snapshot["sections"]
    inv = sections["investment"]
    t = inv["totals"]
    team_section = sections["team_and_phases"]
    naming = snapshot.get("naming_convention") or "Statement of Work"

    head = _HTML_HEAD.format(
        title=escape(naming),
        version=version,
        generated_at=escape(snapshot["generated_at"]),
    )

    parts: list[str] = [head]

    # Title block — uses the brief's naming convention
    parts.append(f"""
      <h1>{escape(naming)}</h1>
      <p class="meta">{escape(MR_LEGAL_ENTITY)} &nbsp;·&nbsp; {escape(snapshot["company_name"])} &nbsp;·&nbsp; v{version}</p>
    """)

    # Document Status table (brief Section 2.2) — visible in draft, hidden on print
    ds = snapshot.get("document_status") or {}
    if ds.get("status"):
        parts.append(f"""
          <div class="doc-status-table">
            <div class="row"><div class="lbl">Document Status</div><div><span class="pill draft">{escape(ds.get("status", "Draft"))}</span> &nbsp; <span class="meta">Remove this table before sending to the Company.</span></div></div>
            <div class="row"><div class="lbl">Next steps · Company</div><div>{escape(ds.get("next_steps_client", ""))}</div></div>
            <div class="row"><div class="lbl">Next steps · Massive Rocket</div><div>{escape(ds.get("next_steps_mr", ""))}</div></div>
          </div>
        """)

    # Internal review warning if scope wasn't validated
    if snapshot.get("validation_status_at_generation") != "validated":
        status_text = snapshot.get("validation_status_at_generation", "unknown")
        parts.append(f"""
          <p><span class="pill warn">Internal review</span>
          This SOW was drafted while scope was in <b>{escape(status_text)}</b>.
          Confirm with delivery before sending externally.</p>
        """)

    # Opening Clause
    parts.append("<h2>Opening Clause</h2>")
    parts.append(f"<p>{escape(sections['opening_clause'])}</p>")

    # Timing & Fees
    tf = sections["timing_and_fees"]
    parts.append("<h2>Timing &amp; Fees</h2>")
    parts.append("<table>")
    parts.append(f"<tr><th style='width:35%'>Currency</th><td>{escape(tf.get('currency', ''))}</td></tr>")
    parts.append(f"<tr><th>Commencement date</th><td>{escape(tf.get('start_date') or '[TO BE CONFIRMED]')}</td></tr>")
    parts.append(f"<tr><th>Initial duration</th><td>{tf.get('duration_months', 0)} months</td></tr>")
    parts.append("</table>")

    # Executive Summary + Project Timeline
    parts.append("<h2>Executive Summary</h2>")
    parts.append(f"<p>{escape(sections['executive_summary'])}</p>")
    timeline = sections.get("project_timeline") or []
    if timeline:
        parts.append("<h3>Project Timeline</h3>")
        parts.append(_render_table(timeline, [
            ("phase", "Phase"), ("months", "Months"),
            ("duration", "Duration"), ("headline", "Headline outcome"),
        ]))

    # Engagement Overview
    overview = sections["engagement_overview"]
    parts.append("<h2>Engagement Overview</h2>")
    if overview.get("background"):
        parts.append(f"<p>{escape(overview['background'])}</p>")
    overview_rows = []
    if overview.get("industry"): overview_rows.append(("Industry", overview["industry"]))
    if overview.get("region"): overview_rows.append(("Region", overview["region"]))
    if overview.get("annual_revenue"): overview_rows.append(("Annual revenue", overview["annual_revenue"]))
    if overview.get("estimated_employees"):
        overview_rows.append(("Estimated employees", f"{overview['estimated_employees']:,}"))
    if overview_rows:
        parts.append("<table>")
        for label, val in overview_rows:
            parts.append(f"<tr><th style='width:35%'>{escape(label)}</th><td>{escape(str(val))}</td></tr>")
        parts.append("</table>")

    parts.append("<h3>Streams in scope</h3><ul>")
    for s in overview["stream_labels"]:
        parts.append(f"<li><b>{escape(s['label'])}</b> — {escape(s['description'])}</li>")
    parts.append("</ul>")

    # Services In Scope
    parts.append("<h2>Services In Scope</h2>")
    for stream in sections["scope_of_work"]:
        parts.append(f"<h3>{escape(stream['label'])}</h3>")
        if not stream["in_scope"]:
            parts.append("<p class='meta'>No qualified or qualifying criteria captured yet for this stream.</p>")
        else:
            parts.append("<ul>")
            for item in stream["in_scope"]:
                pill = "" if item.get("confirmed") else " <span class='pill qualifying'>qualifying</span>"
                value = f" — {escape(item['value'])}" if item.get("value") else ""
                desc  = (f"<br><span class='meta'>{escape(item.get('description', ''))}</span>"
                         if item.get('description') else "")
                parts.append(f"<li><b>{escape(item['label'])}</b>{value}{pill}{desc}</li>")
            parts.append("</ul>")
        if stream.get("open_questions"):
            parts.append("<p class='meta'>Open questions for the next discovery call:</p><ul>")
            for q in stream["open_questions"]:
                value = f" — {escape(q['value'])}" if q.get("value") else ""
                parts.append(f"<li class='meta'>{escape(q['label'])}{value}</li>")
            parts.append("</ul>")

    # Services Out of Scope
    parts.append("<h2>Services Out of Scope</h2><ul>")
    for o in sections["out_of_scope"]:
        parts.append(f"<li>{escape(o)}</li>")
    parts.append("</ul>")

    # Commercial Summary
    parts.append("<h2>Commercial Summary</h2>")
    parts.append(f"""
      <div class="totals">
        <div class="row"><span>Gross fees</span><span>${t['gross_usd']:,.0f} {inv['currency']}</span></div>
        <div class="row"><span>Discount</span><span>−${t['discount_usd']:,.0f}</span></div>
        <div class="row grand"><span>Total investment (net)</span><span>${t['net_usd']:,.0f} {inv['currency']}</span></div>
        <div class="row meta"><span>Total hours</span><span>{t['hours']:,.0f}</span></div>
      </div>
    """)
    cc = sections["commercial_clauses"]
    parts.append(f"<p>{escape(cc['blended_rate'])}</p>")
    parts.append(f"<p>{escape(cc['contingency'])}</p>")
    parts.append(f"<p>{escape(cc['consumption_80pct'])}</p>")
    parts.append("<h3>Monthly schedule</h3>")
    parts.append("<table><thead><tr><th>Month</th><th>Phase</th><th>Gross</th><th>Discount</th><th>Net</th></tr></thead><tbody>")
    for m in inv["monthly"]:
        parts.append(
            f"<tr><td>M{m['month']}</td><td>{escape(m['phase'])}</td>"
            f"<td>${m['gross_usd']:,.0f}</td>"
            f"<td>${m['discount_usd']:,.0f}</td>"
            f"<td>${m['net_usd']:,.0f}</td></tr>"
        )
    parts.append("</tbody></table>")

    # Project Management
    parts.append("<h2>Project Management</h2>")
    parts.append(f"<p>{escape(sections['project_management'])}</p>")

    # Monitoring Progress
    parts.append("<h2>Monitoring Progress</h2>")
    parts.append(f"<p>{escape(sections['monitoring_progress'])}</p>")

    # Company's Participation
    parts.append("<h2>Company's Participation</h2>")
    parts.append(f"<p>{escape(sections['companys_participation'])}</p>")

    # Variations & Change in Scope
    parts.append("<h2>Variations &amp; Change in Scope</h2>")
    parts.append(f"<p>{escape(sections['variations'])}</p>")

    # Changes of Date
    parts.append("<h2>Changes of Date</h2>")
    parts.append(f"<p>{escape(sections['changes_of_date'])}</p>")

    # General Notes & Assumptions
    parts.append("<h2>General Notes &amp; Assumptions</h2><ul>")
    for a in sections["assumptions"]:
        parts.append(f"<li>{escape(a)}</li>")
    parts.append("</ul>")

    # Signatures (brief: Thierry Sequeira as MR Director)
    sig = snapshot.get("signatory_mr") or {}
    parts.append(f"""
      <h2>Signatures</h2>
      <p>Executed on behalf of the parties below.</p>
      <div class="signatures">
        <div class="sigblock">
          <div>For {escape(sig.get('entity', MR_LEGAL_ENTITY))}</div>
          <div class="meta">{escape(sig.get('name', MR_SIGNATORY))} · {escape(sig.get('role', MR_SIGNATORY_ROLE))} · Date</div>
        </div>
        <div class="sigblock">
          <div>For {escape(snapshot["company_name"])}</div>
          <div class="meta">Name · Title · Date</div>
        </div>
      </div>
    """)

    # Annex 1 — Change Order template
    annex = sections.get("annex_1_change_order") or {}
    if annex:
        parts.append(f"<h2>{escape(annex.get('title', 'Annex 1 — Change Order Template'))}</h2>")
        parts.append(f"<p>{escape(annex.get('intro', ''))}</p>")
        parts.append("<table>")
        for label, hint in annex.get("fields", []):
            parts.append(f"<tr><th style='width:30%'>{escape(label)}</th><td class='meta'>{escape(hint)}</td></tr>")
        parts.append("</table>")

    # Roadmap (optional)
    roadmap_block = sections.get("roadmap")
    if roadmap_block and roadmap_block.get("milestones"):
        parts.append('<div class="non-binding-banner">The following appendices are NON-BINDING. They support delivery + Company understanding but do not override the SOW body above. If there is any inconsistency, the SOW body wins.</div>')
        parts.append("<h2>Appendix · Roadmap</h2>")
        rm = roadmap_block
        date_line = ""
        if rm.get("start_date"):
            date_line += f"Start: {escape(rm['start_date'])} · "
        if rm.get("end_date"):
            date_line += f"End: {escape(rm['end_date'])} · "
        date_line += f"{rm.get('months', 12)} months"
        parts.append(f"<p class='meta'>{date_line}</p>")
        parts.append("<table><thead><tr><th>Phase</th><th>Workstream</th><th>Milestone</th><th>Start (M)</th><th>Duration</th></tr></thead><tbody>")
        for m in rm.get("milestones", []):
            parts.append(
                f"<tr><td>{escape(m.get('phase', ''))}</td>"
                f"<td>{escape(m.get('workstream', ''))}</td>"
                f"<td><strong>{escape(m.get('title', ''))}</strong>"
                + (f"<br><span class='meta'>{escape(m.get('description', ''))}</span>" if m.get('description') else '')
                + f"</td>"
                f"<td>M{(m.get('month_offset', 0) or 0) + 1}</td>"
                f"<td>{m.get('duration_months', 1)} mo</td></tr>"
            )
        parts.append("</tbody></table>")

    # Beyond Year 1 (optional appendix)
    if roadmap_block and roadmap_block.get("extended_engagement"):
        parts.append("<h2>Appendix · Beyond Year 1 — Future Engagement</h2>")
        parts.append("<p>This engagement is the starting point. Over an extended "
                     "relationship, Massive Rocket would also support:</p>")
        by_year: dict[int, list[dict]] = {}
        for item in roadmap_block["extended_engagement"]:
            by_year.setdefault(int(item.get("year", 2)), []).append(item)
        for year in sorted(by_year.keys()):
            parts.append(f"<h3>Year {year}</h3><ul>")
            for item in by_year[year]:
                price = item.get("estimated_price_usd") or 0
                hours = item.get("estimated_hours") or 0
                price_str = ""
                if price or hours:
                    bits = []
                    if hours: bits.append(f"~{int(hours):,}h")
                    if price: bits.append(f"~${int(price):,}")
                    price_str = f" <span class='meta'>({' · '.join(bits)})</span>"
                parts.append(
                    f"<li><strong>{escape(item.get('title', ''))}</strong>{price_str}"
                    + (f"<br><span class='meta'>{escape(item.get('description', ''))}</span>" if item.get('description') else '')
                    + "</li>"
                )
            parts.append("</ul>")

    # Team appendix (non-binding) — moved here per brief
    parts.append("<h2>Appendix · Team &amp; Phases</h2>")
    pm = team_section["phase_months"]
    parts.append(
        f"<p class='meta'>The engagement runs across "
        f"{pm.get('Understand', 0)} Understand months, "
        f"{pm.get('Execute', 0)} Execute months, and "
        f"{pm.get('Accelerate', 0)} Accelerate months, with total effort of "
        f"{team_section['hours_total']:,.0f} hours. "
        f"Per the brief, this Team appendix specifies ROLES, not named "
        f"individuals — names are confirmed at staffing finalisation, "
        f"post-signature.</p>"
    )
    parts.append("<table><thead><tr><th>Role</th><th>Understand FTE</th><th>Execute FTE</th><th>Accelerate FTE</th></tr></thead><tbody>")
    for role, by_phase in team_section["team_fte"].items():
        parts.append(
            f"<tr><td>{escape(role)}</td>"
            f"<td>{by_phase.get('Understand', 0):.2f}</td>"
            f"<td>{by_phase.get('Execute', 0):.2f}</td>"
            f"<td>{by_phase.get('Accelerate', 0):.2f}</td></tr>"
        )
    parts.append("</tbody></table>")

    # Footer + side panel close
    parts.append(_HTML_FOOT.format(sidepanel=_render_side_panel(snapshot)))
    return "".join(parts)
