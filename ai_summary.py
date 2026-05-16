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
  "project_scope": "<one short paragraph summarising what MR would deliver, or null>"
}

Rules:
- Only fill values you can ground in the text. Use null for everything else.
- Keep values brief — phrases, not paragraphs.
- No marketing tone. No em-dashes. Plain English.
- If the text doesn't mention something, return null. Don't guess.
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

    return {"meddpicc": meddpicc_out, "project_scope": project_scope}
