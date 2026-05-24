"""v1.0.0bs — Jeff's knowledge base.

Jeff is the in-app AI assistant. He answers AE questions about how to
fill out Project Build correctly, how MR's pricing works, and what
best practice looks like when scoping a deal.

This module is the single place that builds Jeff's system prompt.
Two sources, by design:

1. **Code** — pricing.py role catalogue + team templates + rate cards.
   These are the FACTUAL ground truth. Drifting from them would
   immediately make Jeff wrong; reading them at runtime keeps him
   honest as the rate card changes.

2. **Markdown doc** — `knowledge/pricing_best_practices.md`. The soft
   guidance: when to push back on a client's pricing demand, how to
   talk about contingency, common AE mistakes. Editable in Settings
   so the team can update Jeff's advice without a code deploy.

Skill level adjusts framing only — Jeff's facts don't change, but
his verbosity + jargon does:
- beginner    → explains terms, walks through step by step
- intermediate → assumes basics, focuses on tradeoffs
- expert      → terse, technical, surfaces edge cases

The current view + lead context (if any) become a small "user is
currently looking at X" block so Jeff can give targeted advice
rather than generic answers.

Public API:
    build_system_prompt(*, skill="intermediate", context=None) -> str
    load_best_practices() -> str        # raw doc body
    save_best_practices(body) -> None   # admin write-back
    is_configured() -> bool             # ANTHROPIC_API_KEY present?
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Knowledge doc location — packaged with the app, persists to the
# Railway volume so admin edits survive deploys.
_DEFAULT_KB_PATH = Path(__file__).parent / "knowledge" / "pricing_best_practices.md"


SKILL_LEVELS = ("beginner", "intermediate", "expert")


def is_configured() -> bool:
    """Jeff needs Claude to actually answer. If the key is missing,
    the endpoint returns a friendly "Jeff is offline" instead of
    burning a request."""
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def _kb_path() -> Path:
    override = os.environ.get("JEFF_KB_PATH")
    return Path(override) if override else _DEFAULT_KB_PATH


def load_best_practices() -> str:
    """Read the markdown knowledge doc. Returns empty string if the
    file is missing — Jeff still works off the code-derived facts."""
    p = _kb_path()
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, FileNotFoundError):
        return ""


def save_best_practices(body: str) -> None:
    """Write the markdown knowledge doc. Used by the Settings UI when
    an admin tweaks Jeff's guidance."""
    p = _kb_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body or "", encoding="utf-8")


# -----------------------------------------------------------------
# System prompt builder
# -----------------------------------------------------------------

def _pricing_facts_block() -> str:
    """Render the live pricing data as a compact reference block.
    Reads pricing.py + rate_cards.py at call time so Jeff always
    cites the current rate card."""
    try:
        import pricing
        import rate_cards
    except ImportError:
        return ""

    lines: list[str] = []
    lines.append("## MR pricing — current values")
    lines.append("")
    lines.append(f"- Blended client rate: ${pricing.CLIENT_BLENDED_RATE_USD_PER_HOUR}/hour USD")
    lines.append(f"- Working assumption: {pricing.HOURS_PER_FTE_MONTH} hours per FTE-month")
    lines.append(f"- Default phase split (12-month deal): "
                  f"{pricing.DEFAULT_PHASE_MONTHS['Understand']}/"
                  f"{pricing.DEFAULT_PHASE_MONTHS['Execute']}/"
                  f"{pricing.DEFAULT_PHASE_MONTHS['Accelerate']} "
                  f"(Understand / Execute / Accelerate)")
    lines.append(f"- Default discount: 15% off the Understand phase + "
                  f"first half of Execute")
    lines.append("")
    lines.append("### Rate cards available")
    try:
        for card in rate_cards.all_cards():
            lines.append(f"- {card}")
    except Exception:
        pass
    lines.append("")
    lines.append("### Project-type team templates")
    try:
        templates = pricing.list_team_templates()
        for ptype, roles in templates.items():
            lines.append(f"- **{ptype}**: {', '.join(roles)}")
    except Exception:
        pass
    lines.append("")
    return "\n".join(lines)


def _skill_block(skill: str) -> str:
    """Translate the skill level into a clear instruction about
    verbosity + jargon level. Single source of truth so the three
    levels render consistently across surfaces."""
    skill = (skill or "intermediate").lower()
    if skill not in SKILL_LEVELS:
        skill = "intermediate"
    if skill == "beginner":
        return (
            "The user describes themselves as a BEGINNER. Explain CRM "
            "/ Braze / loyalty / pricing terminology when you use it. "
            "Walk through your reasoning step by step. Prefer concrete "
            "examples over abstractions. If they ask a one-line question, "
            "answer in 3-5 sentences with a worked example.")
    if skill == "expert":
        return (
            "The user describes themselves as an EXPERT. Be terse. "
            "Assume MR vocabulary (FTE, blended rate, phase, project "
            "ops, contingency, opportunity type). Surface edge cases + "
            "tradeoffs without restating fundamentals. If they ask a "
            "one-line question, answer in 1-2 sentences unless detail "
            "is genuinely needed.")
    return (
        "The user describes themselves as INTERMEDIATE. Assume they "
        "know the basics; focus on tradeoffs, best practice, and the "
        "'why' behind recommendations. Don't re-teach FTE or phase "
        "concepts unless asked. Aim for ~3-sentence answers; expand "
        "when the question warrants it.")


def _context_block(context: dict[str, Any] | None) -> str:
    """Render the user's current screen + open lead as a tiny
    awareness block. Lets Jeff give targeted answers ("for THIS deal,
    you should...") rather than generic ones."""
    if not context:
        return ""
    parts: list[str] = ["## User context"]
    view = (context.get("view") or "").strip()
    if view:
        parts.append(f"- Current view: **{view}**")
    lead = context.get("lead") or {}
    if lead:
        bits = []
        for key, label in (("company", "Company"), ("vertical", "Vertical"),
                            ("status", "Status"), ("opportunity_type", "Opportunity"),
                            ("region", "Region"),
                            ("deal_size", "Deal size estimate")):
            v = lead.get(key)
            if v:
                bits.append(f"{label}: {v}")
        if bits:
            parts.append("- Open lead: " + " · ".join(bits))
    pricing_cfg = context.get("pricing") or {}
    if pricing_cfg:
        bits = []
        for key, label in (("rate_card", "Rate card"),
                            ("currency", "Currency"),
                            ("months", "Duration (months)"),
                            ("project_ops_pct", "Project ops %"),
                            ("contingency_pct", "Contingency %")):
            v = pricing_cfg.get(key)
            if v is not None and v != "":
                bits.append(f"{label}: {v}")
        if bits:
            parts.append("- Pricing config in progress: " + " · ".join(bits))
    if len(parts) == 1:
        return ""  # No context worth surfacing.
    parts.append("")
    return "\n".join(parts)


def build_system_prompt(*, skill: str = "intermediate",
                          context: dict[str, Any] | None = None) -> str:
    """Build the full system prompt Jeff uses for every chat turn.

    Sections (in order):
      1. Identity + tone
      2. Skill-adjusted framing
      3. Current user context (view + open lead + pricing in progress)
      4. Code-derived pricing facts (live from pricing.py + rate_cards)
      5. Admin-editable best-practice guidance (markdown doc)

    Order matters: identity first establishes who Jeff is; facts before
    best practices so opinions are grounded in the rate card.
    """
    identity = (
        "You are **Jeff** — Massive Rocket's in-app assistant for the "
        "Lead Qualification + Project Build + Pricing app. You help AEs "
        "and growth managers scope deals correctly, pick the right "
        "pricing posture, and respond to client pushback on price.\n\n"
        "Speak in MR's voice: direct, no fluff, no hedging adjectives. "
        "When a recommendation has a tradeoff, name it. When MR's data "
        "isn't sufficient to answer, say so plainly. You can use "
        "markdown (lists, bold, headings) but skip emoji unless the "
        "user asks.\n\n"
        "Your scope: pricing, scoping, project types, rate cards, SOW "
        "structure, common client objections, MR delivery best "
        "practices. Not in scope: writing the actual SOW content, "
        "running pricing calculations (the app does that), or making "
        "client commitments. Redirect those gently.")

    skill_line = _skill_block(skill)
    ctx = _context_block(context)
    facts = _pricing_facts_block()
    kb = load_best_practices()
    kb_block = ""
    if kb.strip():
        kb_block = "## Best-practice guidance (from admin-edited doc)\n\n" + kb.strip()

    sections = [identity, "", skill_line]
    if ctx:
        sections.extend(["", ctx])
    if facts:
        sections.extend(["", facts])
    if kb_block:
        sections.extend(["", kb_block])
    return "\n".join(sections)
