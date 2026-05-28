"""Tool-using agent + persona library (v1.0.0dk).

The gap analysis against Agentforce / Breeze / Clay landed on two
missing pieces beyond the tool registry (mr_tools):

  1. An agent that can actually CALL those tools in a loop — read the
     pipeline, look up coverage, match proof points — and reason over
     the results, rather than a one-shot chat that only knows what's in
     its prompt.
  2. A small library of PERSONAS so the same engine can act as an
     Account Researcher, a Partner Relationship Coach, a Briefing
     Writer, a Pipeline Analyst, or Jeff (pricing) — each scoped to the
     right tools and given the right voice.

This module is that engine. It runs the Anthropic tool-use loop against
the mr_tools registry and returns the final answer PLUS an audit trace
of every tool that fired (name, input, ok/error) so the UI can render
"here's what I did" cards and the audit log can record agent actions.

Public API
----------
is_configured() -> bool
list_personas() -> list[dict]              # {key, label, description, ...}
get_persona(key) -> Persona | None
run_agent(persona_key, messages, *, context=None, allow_writes=False,
          max_steps=6, model=None) -> dict
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import mr_tools

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Shared style guidance baked into every persona's system prompt.
# Mirrors Ben's writing-style memory: plain English, no em-dashes, no
# AI cadence, never invent facts.
# ---------------------------------------------------------------------

_BASE_RULES = """\
You are part of Massive Rocket's internal sales + partnerships platform.
Massive Rocket is a Braze + Hightouch + Snowflake consultancy (CRM, data
and engineering for B2C brands: QSR, retail, financial services).

GROUND RULES (all personas)
- Use the tools to ground every claim in real MR data. Do not guess at
  numbers, names or dates you could look up. If a tool returns no data,
  say "I don't have data on that" rather than inventing it.
- Plain English. No marketing tone, no "I hope this finds you well",
  no AI cliches. Never use em-dashes or en-dashes; use a comma, a
  period or a regular hyphen.
- Be concise. Lead with the answer, then the supporting detail.
- You draft and analyse; you never send messages or make external
  commitments. Outreach you produce is a draft for a human to review.
- When you call a tool, briefly tell the user what you found before
  moving on, so they can follow your reasoning."""


@dataclass(frozen=True)
class Persona:
    key: str
    label: str
    description: str
    # System prompt fragment appended after the base rules.
    system: str
    # Tool tags this persona is scoped to (None => all read tools).
    tool_tags: tuple[str, ...] | None = None
    # Whether this persona may use write tools at all (still gated by
    # the per-request allow_writes flag).
    can_write: bool = False
    # Suggested opening prompts the UI can show as chips.
    starters: tuple[str, ...] = field(default_factory=tuple)


_PERSONAS: dict[str, Persona] = {}


def _register(p: Persona) -> None:
    _PERSONAS[p.key] = p


_register(Persona(
    key="researcher",
    label="Account Researcher",
    description="Researches an account: pipeline status, engagement, "
                "stakeholders and relevant proof points.",
    system=(
        "ROLE: Account Researcher.\n"
        "Given a company name or lead, build a tight briefing: where it "
        "sits in the pipeline, its engagement score and what's driving "
        "it, who the key contacts are, and which delivered proof points "
        "are most relevant. Resolve a company name to a lead id with "
        "list_leads before calling get_lead. Finish with 2-3 concrete "
        "next actions for the AE."
    ),
    tool_tags=("pipeline", "partners", "research", "proof", "analysis"),
    starters=(
        "Research <company> for me",
        "Which proof points fit a QSR lead on Braze?",
        "What's the engagement picture on my pipeline?",
    ),
))

_register(Persona(
    key="partner_coach",
    label="Partner Relationship Coach",
    description="Surfaces stale / overdue partner stakeholders and "
                "drafts re-engagement outreach.",
    system=(
        "ROLE: Partner Relationship Coach.\n"
        "Help the partnership team keep Braze / Hightouch / Snowflake "
        "relationships warm. Use get_stakeholder_coverage and "
        "get_overdue_contacts to find who's slipping, then prioritise by "
        "tier and how long it's been. When asked, draft outreach with "
        "draft_outreach (default tone re_engagement for stale contacts). "
        "Always present drafts for the human to review and send."
    ),
    tool_tags=("partners", "outreach", "analysis"),
    can_write=False,
    starters=(
        "Who on the partner side is overdue for a touch?",
        "Show me stakeholder coverage and the biggest gaps",
        "Draft a re-engagement note to a stale Braze contact",
    ),
))

_register(Persona(
    key="briefing",
    label="Briefing Writer",
    description="Writes internal project briefs grounded in delivered "
                "proof points and account context.",
    system=(
        "ROLE: Briefing Writer.\n"
        "Produce internal briefs for an account or opportunity: the "
        "situation, why MR is a fit, the most relevant delivered proof "
        "points (use match_proof_points / list_use_cases), and a "
        "suggested approach. NEVER fabricate client metrics — only cite "
        "outcomes that appear in a use-case result; if a proof point has "
        "no metric, describe the work qualitatively. Keep it skimmable: "
        "headings + short bullets."
    ),
    tool_tags=("proof", "pipeline", "research", "partners"),
    starters=(
        "Write a brief for <company>",
        "Build a proof-point pack for a retail loyalty pitch",
    ),
))

_register(Persona(
    key="pipeline_analyst",
    label="Pipeline Analyst",
    description="Analyses pipeline health and quarterly target "
                "attainment.",
    system=(
        "ROLE: Pipeline Analyst.\n"
        "Answer questions about pipeline health and goal attainment. Use "
        "list_leads for the current pipeline, get_engagement_score for "
        "account health, and get_quarterly_progress for plan-vs-actual. "
        "Quantify: cite counts, percentages and attainment. Flag the 2-3 "
        "things most worth the manager's attention this week."
    ),
    tool_tags=("pipeline", "targets", "analysis"),
    starters=(
        "How are we tracking against Q2 targets?",
        "Which accounts are at risk right now?",
        "Summarise pipeline health for the weekly review",
    ),
))

_register(Persona(
    key="jeff",
    label="Jeff (Pricing)",
    description="MR's pricing + scoping assistant, now able to look up "
                "real pipeline + proof points.",
    system=(
        "ROLE: Jeff, MR's pricing + scoping assistant.\n"
        "Help AEs scope deals, pick a pricing posture and handle price "
        "pushback. You can look up the live pipeline and delivered proof "
        "points to ground your advice. You do NOT run pricing "
        "calculations (the app does that) or write SOW content. Keep "
        "answers direct and name the tradeoffs."
    ),
    tool_tags=("pipeline", "proof", "research"),
    starters=(
        "How should I price a 12-month Braze build?",
        "What proof points back a financial-services pitch?",
    ),
))


def list_personas() -> list[dict[str, Any]]:
    return [
        {
            "key":         p.key,
            "label":       p.label,
            "description": p.description,
            "can_write":   p.can_write,
            "starters":    list(p.starters),
        }
        for p in _PERSONAS.values()
    ]


def get_persona(key: str) -> Persona | None:
    return _PERSONAS.get((key or "").strip().lower())


def is_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


# ---------------------------------------------------------------------
# Context block (reuse Jeff's awareness pattern, lightly)
# ---------------------------------------------------------------------

def _context_block(context: dict[str, Any] | None) -> str:
    if not context or not isinstance(context, dict):
        return ""

    def _clean(v: Any) -> str:
        if v is None:
            return ""
        s = str(v).replace("\r", " ").replace("\n", " ")
        s = s.strip().lstrip("#").lstrip("*").lstrip("-").strip()
        return s[:120]

    parts: list[str] = ["## User context"]
    view = _clean(context.get("view"))
    if view:
        parts.append(f"- Current view: {view}")
    lead = context.get("lead") or {}
    if isinstance(lead, dict) and lead:
        bits = []
        for key, label in (("company", "Company"), ("vertical", "Vertical"),
                            ("status", "Status"),
                            ("opportunity_type", "Opportunity"),
                            ("region", "Region")):
            v = _clean(lead.get(key))
            if v:
                bits.append(f"{label}: {v}")
        lead_id = _clean(lead.get("id"))
        if lead_id:
            bits.append(f"lead_id: {lead_id}")
        if bits:
            parts.append("- Open lead: " + " · ".join(bits))
    if len(parts) == 1:
        return ""
    return "\n".join(parts)


def _build_system(persona: Persona, context: dict[str, Any] | None) -> str:
    sections = [_BASE_RULES, "", persona.system]
    ctx = _context_block(context)
    if ctx:
        sections.extend(["", ctx])
    return "\n".join(sections)


# ---------------------------------------------------------------------
# The agent loop
# ---------------------------------------------------------------------

def _summarise_result(result: Any) -> str:
    """One-line summary of a tool result for the audit trace."""
    if isinstance(result, dict):
        if "error" in result and len(result) <= 3:
            return f"error: {str(result['error'])[:120]}"
        # Count-ish summaries for list-returning tools.
        for k in ("count", "leads", "contacts", "overdue", "matches",
                  "use_cases", "metrics"):
            v = result.get(k)
            if isinstance(v, int):
                return f"{k}={v}"
            if isinstance(v, list):
                return f"{k}: {len(v)} items"
        keys = ", ".join(list(result.keys())[:6])
        return f"keys: {keys}"
    return str(result)[:120]


def run_agent(persona_key: str,
              messages: list[dict[str, Any]],
              *,
              context: dict[str, Any] | None = None,
              allow_writes: bool = False,
              max_steps: int = 6,
              model: str | None = None) -> dict[str, Any]:
    """Run one agent turn with tool use.

    Args
    ----
    persona_key:   which persona to act as (see list_personas()).
    messages:      prior conversation [{role, content}, ...].
    context:       optional {view, lead} awareness block.
    allow_writes:  if False, write tools are removed from the toolset
                   entirely (the agent literally cannot call them).
    max_steps:     max model<->tool round trips before forcing a stop.

    Returns
    -------
    {
      "message":  <final assistant text>,
      "persona":  <key>,
      "steps":    [ {tool, input, ok, summary}, ... ],  # audit trace
      "stopped":  "end_turn" | "max_steps",
    }
    or {"error": ..., "code": ...} on failure.
    """
    persona = get_persona(persona_key)
    if persona is None:
        return {"error": f"unknown persona: {persona_key}",
                "code": "unknown_persona",
                "available": list(_PERSONAS.keys())}
    if not is_configured():
        return {"error": "Agent is offline — ANTHROPIC_API_KEY isn't set.",
                "code": "agent_disabled"}

    try:
        from anthropic import Anthropic
    except ImportError:
        return {"error": "Anthropic SDK not installed.",
                "code": "agent_disabled"}

    # Scope the toolset: persona tags + per-request write gate.
    writes_ok = bool(allow_writes) and persona.can_write
    tools = mr_tools.anthropic_tools(
        include_writes=writes_ok,
        tags=persona.tool_tags,
    )
    system = _build_system(persona, context)

    # Normalise inbound messages to user/assistant text turns.
    convo: list[dict[str, Any]] = []
    for m in (messages or [])[-20:]:
        if not isinstance(m, dict):
            continue
        role = "assistant" if m.get("role") == "assistant" else "user"
        content = str(m.get("content") or "").strip()
        if not content:
            continue
        convo.append({"role": role, "content": content[:8000]})
    if not convo:
        return {"error": "no usable message content",
                "code": "invalid_request"}

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"].strip())
    model = (model or os.environ.get("AGENT_MODEL")
             or os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-4-5")

    steps: list[dict[str, Any]] = []
    stopped = "end_turn"

    for _ in range(max(1, int(max_steps))):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=1500,
                system=system,
                tools=tools,
                messages=convo,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("agent upstream error: %s", e)
            return {"error": f"Agent couldn't respond: {e}",
                    "code": "upstream_error", "steps": steps}

        # Append the assistant turn verbatim (text + tool_use blocks) so
        # the next request has the full tool-use context.
        convo.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            text = "".join(
                getattr(b, "text", "") or ""
                for b in resp.content
                if getattr(b, "type", None) == "text"
            ).strip()
            return {
                "message": text or "(The agent returned an empty reply.)",
                "persona": persona.key,
                "steps":   steps,
                "stopped": "end_turn",
            }

        # Run every tool_use block and feed results back.
        tool_results: list[dict[str, Any]] = []
        for block in resp.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            name = block.name
            args = block.input or {}
            result = mr_tools.call_tool(name, args)
            ok = not (isinstance(result, dict) and "error" in result
                      and len(result) <= 3)
            steps.append({
                "tool":    name,
                "input":   args,
                "ok":      ok,
                "summary": _summarise_result(result),
                "writes":  bool(getattr(mr_tools.get_tool(name), "writes", False)),
            })
            import json
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, default=str)[:12000],
            })
        convo.append({"role": "user", "content": tool_results})
    else:
        stopped = "max_steps"

    # Hit the step cap — ask for a final synthesis without more tools.
    try:
        final = client.messages.create(
            model=model,
            max_tokens=1200,
            system=system + "\n\nYou have gathered enough. Give your final "
                            "answer now without calling more tools.",
            messages=convo,
        )
        text = "".join(
            getattr(b, "text", "") or ""
            for b in final.content
            if getattr(b, "type", None) == "text"
        ).strip()
    except Exception as e:  # noqa: BLE001
        text = f"(Stopped after {max_steps} tool steps; could not "
        text += f"synthesise: {e})"

    return {
        "message": text or "(The agent ran out of steps.)",
        "persona": persona.key,
        "steps":   steps,
        "stopped": stopped,
    }
