"""Optional AI-assisted fit summary using the Anthropic API.

Returns a 2-3 sentence summary when ANTHROPIC_API_KEY is set; otherwise
returns None and the caller falls back to the heuristic generator in
qualify_service.

Model: claude-haiku-4-5 (fast + cheap; this task is 2-3 sentences).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

log = logging.getLogger("mr.ai_summary")

_DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

SYSTEM_PROMPT = """You are a senior sales rep at Massive Rocket, a services
agency that delivers Braze and Hightouch implementations. You write blunt,
useful fit summaries for an internal Notion tracker — read by AEs and the
Head of Partnerships.

Rules:
- 2 to 3 sentences. No preamble, no "in summary".
- Plain English. No marketing jargon. No em-dashes.
- Lead with what makes them fit (or not).
- Name specific tech when known (Braze, Snowflake, Hightouch, Segment).
- Don't restate the numeric score or the status label — the UI already shows them.
- If hard disqualifiers are present, name them.
- If signals are present, weave them in.
"""


def _format_context(payload: dict) -> str:
    """Compact JSON-ish brief for the model. Keeps tokens down."""
    org = (payload.get("company") or {}).get("apollo") or {}
    score = payload.get("score") or {}
    discovered = payload.get("discovered") or {}
    opp = payload.get("opportunity") or {}

    brief: dict[str, Any] = {
        "company": (payload.get("company") or {}).get("name"),
        "industry_keywords": " ".join(
            [str(org.get("industry") or ""), *(org.get("keywords") or [])]
        )[:240],
        "revenue": discovered.get("revenue"),
        "employees": discovered.get("employees"),
        "region": discovered.get("region"),
        "tech_stack": discovered.get("tech_stack"),
        "complexity": discovered.get("complexity"),
        "opportunity_type": opp.get("label"),
        "opportunity_play": opp.get("play"),
        "score_breakdown": {
            k: f"{v.get('value')} ({v.get('weighted')}/{v.get('max_weighted')})"
            for k, v in (score.get("breakdown") or {}).items()
        },
        "positive_signals": payload.get("signals") or [],
        "hard_disqualifiers": payload.get("disqualifiers") or [],
    }
    return json.dumps(brief, ensure_ascii=False, default=str)


def generate_fit_summary(payload: dict) -> str | None:
    """Return a fresh AI summary, or None if AI is unconfigured or failed."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from anthropic import Anthropic
    except ImportError:
        log.warning("anthropic SDK not installed; falling back to heuristic.")
        return None
    try:
        client = Anthropic(api_key=api_key)
        ctx = _format_context(payload)
        msg = client.messages.create(
            model=_DEFAULT_MODEL,
            max_tokens=220,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": ctx}],
        )
        # SDK returns content as a list of content blocks; first is text for this call.
        for block in msg.content:
            text = getattr(block, "text", None)
            if text:
                return text.strip()
        return None
    except Exception as e:
        log.warning("AI summary call failed; falling back to heuristic. %s", e)
        return None


def is_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


# ---------------------------------------------------------------------------
# Roadmap suggestion + Extended Engagement suggestion
# ---------------------------------------------------------------------------

_ROADMAP_SYSTEM_PROMPT = """You take Massive Rocket's qualification data
(MEDDPICC, scope, call notes) and existing roadmap milestones and produce
a *refined* set of milestones — adjusting, adding, or removing — to reflect
what we now know about the prospect.

Return ONE JSON object only. No preamble. No markdown fences.

Schema:
{
  "milestones": [
    {
      "workstream":      "<one of: CRM Strategy, CRM Build, CRM Execute, Data, Engineering, Cross-cutting>",
      "title":           "<short milestone label, max ~50 chars>",
      "month_offset":    <integer; 0 = project start>,
      "duration_months": <integer >= 1>,
      "phase":           "<one of: Understand, Execute, Accelerate>",
      "description":     "<one short sentence, optional>"
    },
    ...
  ],
  "rationale": "<one short paragraph: how the notes/MEDDPICC moved the plan>"
}

Rules:
- Output 4–10 milestones total. More than 10 = too granular for a roadmap.
- Use the project's total months as the constraint: month_offset + duration_months <= total_months.
- If the call notes surface a specific pain or timeline, reflect it
  (e.g. "Q2 renewal" → migration must finish by month 5).
- Keep workstreams distinct. Don't put strategy work under CRM Build.
- No marketing tone. No em-dashes. Plain English.
"""


_EXTENDED_SYSTEM_PROMPT = """You propose 3 to 5 follow-on engagements for
a Massive Rocket client beyond their initial scope. You see the current
scope, the package catalogue, and what we've learned from calls. You're
helping the AE pitch what year 2 / year 3 with MR looks like.

Return ONE JSON object. No preamble. No markdown fences.

Schema:
{
  "items": [
    {
      "year":             <integer >= 2>,
      "title":            "<short label>",
      "description":      "<one to two sentences on why this fits>",
      "package_key":      "<exact key from the package catalogue, or null>",
      "estimated_hours":  <integer or 0 if unknown>,
      "estimated_price_usd": <number or 0 if unknown>
    },
    ...
  ]
}

Rules:
- Year 2 first, then year 3, then beyond. Don't dump everything into year 2.
- Pick from the package catalogue where there's a sensible match. Use the
  exact `key`. Fall back to a custom title only when no package fits.
- Estimate prices conservatively. Use $200/h * hours when unsure.
- Don't propose work the client just paid for in year 1.
- Plain English. No buzzwords. No em-dashes.
"""


def suggest_roadmap(*, total_months: int, current_milestones: list[dict],
                    scope: dict | None, calls: list[dict] | None,
                    project_streams: list[str] | None = None) -> dict | None:
    """Run Claude over the qual context and propose a refined milestone list."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from anthropic import Anthropic
    except ImportError:
        return None

    context = {
        "total_months": int(total_months or 12),
        "project_streams": project_streams or [],
        "current_milestones": current_milestones or [],
        "scope_summary": (scope or {}).get("summary"),
        "scope_streams": [s.get("project_type") for s in (scope or {}).get("streams", [])],
        "recent_call_notes": [
            {
                "type": c.get("type"),
                "title": c.get("title") or "",
                "note": (c.get("note") or c.get("extracted", {}).get("synthesised_note") or "")[:1200],
            }
            for c in (calls or [])[:5]
        ],
    }
    try:
        client = Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=_DEFAULT_MODEL, max_tokens=1500,
            system=_ROADMAP_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(context, default=str)}],
        )
        text = ""
        for block in msg.content:
            text = (getattr(block, "text", None) or "")
            if text:
                break
        text = text.strip().strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
        data = json.loads(text)
    except Exception as e:
        log.warning("Roadmap suggestion failed: %s", e)
        return None
    return data


def suggest_extended_engagement(*, current_scope_streams: list[str],
                                 current_package_keys: list[str] | None,
                                 package_catalogue: list[dict],
                                 calls: list[dict] | None) -> dict | None:
    """Propose what year 2 / year 3 / beyond with MR could look like."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from anthropic import Anthropic
    except ImportError:
        return None
    context = {
        "current_scope_streams": current_scope_streams or [],
        "current_package_keys": current_package_keys or [],
        "package_catalogue": [
            {"key": p.get("key"), "name": p.get("name"),
             "hours": p.get("total_hours"), "duration_months": p.get("duration_months"),
             "notes": p.get("notes") or ""}
            for p in (package_catalogue or [])
        ],
        "recent_call_notes": [
            {"note": (c.get("note") or c.get("extracted", {}).get("synthesised_note") or "")[:1000]}
            for c in (calls or [])[:5]
        ],
    }
    try:
        client = Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=_DEFAULT_MODEL, max_tokens=1500,
            system=_EXTENDED_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(context, default=str)}],
        )
        text = ""
        for block in msg.content:
            text = (getattr(block, "text", None) or "")
            if text:
                break
        text = text.strip().strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
        data = json.loads(text)
    except Exception as e:
        log.warning("Extended engagement suggestion failed: %s", e)
        return None
    return data


# ---------------------------------------------------------------------------
# Note extraction: turn raw call notes / transcripts into structured fills
# ---------------------------------------------------------------------------

_MEDDPICC_KEYS = [
    "metrics", "economic_buyer", "decision_criteria", "decision_process",
    "paper_process", "identify_pain", "champion", "competition",
]

_EXTRACT_SYSTEM_PROMPT = """You read raw sales call notes or transcripts and
extract structured qualification data for an internal CRM agency (Massive
Rocket). You return ONE JSON object only, no preamble, no markdown fences.

Schema:
{
  "meddpicc": {
    "metrics":           {"value": "<short phrase or null>"},
    "economic_buyer":    {"value": "<name + title, or null>"},
    "decision_criteria": {"value": "<comma-separated criteria, or null>"},
    "decision_process":  {"value": "<short summary, or null>"},
    "paper_process":     {"value": "<procurement/legal notes, or null>"},
    "identify_pain":     {"value": "<core pain, or null>"},
    "champion":          {"value": "<name + title, or null>"},
    "competition":       {"value": "<vendors mentioned, or null>"}
  },
  "project_scope": "<one short paragraph summarising what MR would deliver, or null>",
  "synthesised_note": "<a structured call summary in the MR Call Note format — see below>"
}

The synthesised_note uses this exact markdown structure (omit any section
where you have nothing real to say — never write 'TBD' or 'N/A'):

## Headline
<one sentence: what mattered most in this call>

## Attendees
- <name, title (company)> — one per line; MR side and prospect side mixed

## What we heard
- <2 to 4 bullets summarising the conversation in plain English>

## Discovery
- **Metrics:** <only if mentioned>
- **Economic Buyer:** <only if identified>
- **Decision Criteria:** <only if mentioned>
- **Decision Process:** <only if discussed>
- **Paper Process:** <only if discussed>
- **Pain:** <only if surfaced>
- **Champion:** <only if identified>
- **Competition:** <only if mentioned>

## Project shaping
<1 to 2 sentences on what MR's engagement might look like — only if
the call gave you enough to say something concrete>

## Action items
**MR:**
- <action>
**Prospect:**
- <action>

## Risks
- <only if concrete risks were raised in the call>

Rules:
- Only fill values you can ground in the text. Use null for everything else.
- Keep values brief — phrases, not paragraphs.
- No marketing tone. No em-dashes. Plain English.
- If a section has nothing to say, omit the section entirely.
- The synthesised_note IS the AE-facing artefact. Make it scannable.
"""


def extract_from_notes(notes: str, *, company_name: str | None = None,
                       current_meddpicc: dict | None = None) -> dict | None:
    """Return {meddpicc: {...}, project_scope: str} extracted from the notes.

    Returns None if Anthropic isn't configured or the call fails.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from anthropic import Anthropic
    except ImportError:
        log.warning("anthropic SDK not installed; extraction unavailable.")
        return None

    notes = (notes or "").strip()
    if not notes:
        return None
    if len(notes) > 60_000:
        notes = notes[:60_000]

    context_prefix = ""
    if company_name:
        context_prefix += f"Company: {company_name}\n"
    if current_meddpicc:
        # Show the AE's existing entries so the model doesn't overwrite confirmed ones.
        confirmed = {k: v for k, v in current_meddpicc.items()
                     if isinstance(v, dict) and v.get("status") == "confirmed" and v.get("value")}
        if confirmed:
            context_prefix += "Already confirmed (do not overwrite):\n"
            for k, v in confirmed.items():
                context_prefix += f"  {k}: {v.get('value')}\n"

    user_msg = f"{context_prefix}\nNotes:\n{notes}"

    try:
        client = Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=_DEFAULT_MODEL,
            max_tokens=900,
            system=_EXTRACT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = ""
        for block in msg.content:
            text = (getattr(block, "text", None) or "")
            if text:
                break
        text = text.strip()
        if text.startswith("```"):
            # Strip a stray code fence if the model added one
            text = text.strip("`").strip()
            if text.lower().startswith("json"):
                text = text[4:].lstrip()
        data = json.loads(text)
    except Exception as e:
        log.warning("Note extraction call failed: %s", e)
        return None

    # Normalise + filter to known keys only.
    meddpicc_out: dict[str, dict[str, Any]] = {}
    for k in _MEDDPICC_KEYS:
        entry = (data.get("meddpicc") or {}).get(k) or {}
        value = entry.get("value")
        if value and value != "null":
            meddpicc_out[k] = {"value": str(value).strip()}
    project_scope = data.get("project_scope")
    if project_scope and str(project_scope).lower() != "null":
        project_scope = str(project_scope).strip()
    else:
        project_scope = None
    synthesised_note = data.get("synthesised_note")
    if synthesised_note and str(synthesised_note).lower() != "null":
        synthesised_note = str(synthesised_note).strip()
    else:
        synthesised_note = None

    return {
        "meddpicc": meddpicc_out,
        "project_scope": project_scope,
        "synthesised_note": synthesised_note,
    }
