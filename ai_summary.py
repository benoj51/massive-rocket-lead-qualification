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
