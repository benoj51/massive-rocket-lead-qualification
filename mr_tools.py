"""Unified agentic tool registry (v1.0.0dj).

Single source of truth for the tools the agentic layer can call. Each
tool is a plain Python function + a JSON schema describing its inputs.
The same registry is exposed two ways:

  - Anthropic tool-use (the in-app agent)  -> anthropic_tools()
  - Model Context Protocol (Claude Desktop, etc.) via mr_mcp_server.py

Why a registry rather than ad-hoc per-surface wiring: the gap analysis
against Salesforce Agentforce / HubSpot Breeze / Clay landed on the
same conclusion the MCP ecosystem did. Define the tools once, in code,
close to the data; let every agent surface (in-app, desktop, scheduled)
share them. No duplicated schemas, no drift.

Design rules
------------
- Handlers call the existing stores / modules IN-PROCESS. No HTTP hop
  back into Flask, so this works from the MCP stdio server too.
- Read tools are side-effect-free. Write tools set ``writes=True`` so
  the caller can gate them behind approval / audit (the in-app agent
  surfaces an audit card; the MCP server can be run read-only).
- Every handler is defensive: it returns a dict with an ``error`` key
  rather than raising, so one mis-call never crashes the agent loop.
- Handlers take a single ``args`` dict (the tool input) and read keys
  off it. Extra keys are ignored. Missing keys fall back to defaults.

Public API
----------
all_tools()                 -> list[Tool]
get_tool(name)              -> Tool | None
anthropic_tools(...)        -> list[dict]   # {name, description, input_schema}
call_tool(name, args)       -> dict         # dispatch + run a handler
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Tool model + registry
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]
    # writes=True => this tool mutates MR data. The in-app agent shows
    # an audit card and (optionally) requires approval; the MCP server
    # can be launched with MR_MCP_READONLY=1 to hide these entirely.
    writes: bool = False
    # Coarse grouping for persona scoping (see agent.py).
    tags: tuple[str, ...] = field(default_factory=tuple)


_REGISTRY: dict[str, Tool] = {}


def _register(tool: Tool) -> Tool:
    if tool.name in _REGISTRY:
        raise ValueError(f"duplicate tool name: {tool.name}")
    _REGISTRY[tool.name] = tool
    return tool


def tool(name: str, description: str, input_schema: dict[str, Any], *,
         writes: bool = False, tags: tuple[str, ...] = ()):
    """Decorator: register a function as an MR tool."""
    def deco(fn: Callable[[dict[str, Any]], Any]) -> Callable:
        _register(Tool(name=name, description=description,
                       input_schema=input_schema, handler=fn,
                       writes=writes, tags=tags))
        return fn
    return deco


def all_tools(*, include_writes: bool = True,
              tags: tuple[str, ...] | None = None) -> list[Tool]:
    out = list(_REGISTRY.values())
    if not include_writes:
        out = [t for t in out if not t.writes]
    if tags:
        want = set(tags)
        out = [t for t in out if want & set(t.tags)]
    return out


def get_tool(name: str) -> Tool | None:
    return _REGISTRY.get(name)


def anthropic_tools(*, include_writes: bool = True,
                    tags: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """Tool definitions in the Anthropic Messages `tools=` format."""
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        for t in all_tools(include_writes=include_writes, tags=tags)
    ]


def call_tool(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Dispatch a tool call. Always returns a dict (never raises) so the
    agent loop can feed the result straight back to the model.

    On success: the handler's dict (or {"result": <value>} for non-dict
    returns). On failure: {"error": "...", "tool": name}.
    """
    args = args or {}
    t = _REGISTRY.get(name)
    if t is None:
        return {"error": f"unknown tool: {name}",
                "available": sorted(_REGISTRY.keys())}
    try:
        out = t.handler(args)
    except Exception as e:  # noqa: BLE001 — defensive boundary
        log.warning("tool %s failed: %s", name, e)
        return {"error": str(e), "tool": name}
    if isinstance(out, dict):
        return out
    return {"result": out}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------
# Read tools — pipeline / leads
# ---------------------------------------------------------------------

@tool(
    "list_leads",
    "List qualified leads / accounts in the Notion pipeline. Returns "
    "company, owner, stage, status and ICP score per row. Use this to "
    "find accounts before drilling into one with get_lead.",
    {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "minimum": 1, "maximum": 100,
                      "description": "Max rows to return (default 50)."},
        },
    },
    tags=("pipeline", "research"),
)
def _list_leads(args: dict[str, Any]) -> dict[str, Any]:
    import notion_sync
    limit = int(args.get("limit") or 50)
    limit = max(1, min(limit, 100))
    try:
        rows = notion_sync.NotionSync().list_pipeline(limit=limit)
    except (notion_sync.NotionSyncError, ValueError) as e:
        return {"leads": [], "error": f"Notion not configured: {e}"}
    trimmed = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        trimmed.append({
            "id":          r.get("id"),
            "company":     r.get("company"),
            "owner":       r.get("owner"),
            "sales_stage": r.get("sales_stage"),
            "status":      r.get("status"),
            "icp":         r.get("icp_normalised"),
            "region":      r.get("region"),
            "vertical":    r.get("vertical"),
            "opportunity_type": r.get("opportunity_type"),
        })
    return {"leads": trimmed, "count": len(trimmed)}


@tool(
    "get_lead",
    "Fetch the full detail for one lead / account by its Notion page id, "
    "including company, owner, stage, BANT / MEDDPICC fields, tech stack "
    "and summary. Pair with list_leads to resolve a company name to an id.",
    {
        "type": "object",
        "properties": {
            "lead_id": {"type": "string",
                        "description": "Notion page id of the lead."},
        },
        "required": ["lead_id"],
    },
    tags=("pipeline", "research"),
)
def _get_lead(args: dict[str, Any]) -> dict[str, Any]:
    import notion_sync
    lead_id = (args.get("lead_id") or "").strip()
    if not lead_id:
        return {"error": "lead_id required"}
    try:
        page = notion_sync.NotionSync().get_page(lead_id)
    except (notion_sync.NotionSyncError, ValueError) as e:
        return {"error": f"Notion not configured: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"lookup failed: {e}"}
    if not page:
        return {"error": "lead not found", "lead_id": lead_id}
    return {"lead": page}


@tool(
    "get_engagement_score",
    "Compute the engagement score (0-100) for one account: how well its "
    "contact roster is covered and how recent the activity is. Returns "
    "score, band (strong/warm/weak/cold) and the signal breakdown. "
    "Read-only — does not record a snapshot or fire notifications.",
    {
        "type": "object",
        "properties": {
            "lead_id": {"type": "string",
                        "description": "Notion page id of the lead."},
        },
        "required": ["lead_id"],
    },
    tags=("pipeline", "analysis"),
)
def _get_engagement_score(args: dict[str, Any]) -> dict[str, Any]:
    import contacts_store
    import calls_store
    import lead_contact_notes_store
    import engagement
    lead_id = (args.get("lead_id") or "").strip()
    if not lead_id:
        return {"error": "lead_id required"}
    contacts = [contacts_store.annotate_touch_state(dict(c))
                for c in contacts_store.list_contacts(lead_id)]
    event_isos: list[str] = []
    for c in contacts:
        try:
            for n in lead_contact_notes_store.list_notes(lead_id, c["id"]):
                if n.get("created_at"):
                    event_isos.append(n["created_at"])
        except Exception:  # noqa: BLE001
            continue
    try:
        for k in calls_store.list_calls(lead_id):
            if k.get("created_at"):
                event_isos.append(k["created_at"])
    except Exception:  # noqa: BLE001
        pass
    result = engagement.compute_engagement_score(
        contacts=contacts, recent_event_isos=event_isos)
    result["lead_id"] = lead_id
    return result


# ---------------------------------------------------------------------
# Read tools — partners / stakeholders
# ---------------------------------------------------------------------

@tool(
    "list_partner_contacts",
    "List partner-side contacts (Braze / Hightouch / Snowflake people the "
    "partnership team works with). Pass partner_id to scope to one partner, "
    "or omit it for every partner. Returns name, title, partner, tier, "
    "key-stakeholder flag and last-touched date.",
    {
        "type": "object",
        "properties": {
            "partner_id": {"type": "string",
                           "description": "Partner slug (e.g. 'braze'). "
                                          "Omit for all partners."},
        },
    },
    tags=("partners", "research"),
)
def _list_partner_contacts(args: dict[str, Any]) -> dict[str, Any]:
    import partner_contacts_store
    partner_id = (args.get("partner_id") or "").strip()
    if partner_id:
        contacts = partner_contacts_store.list_contacts(partner_id)
    else:
        contacts = partner_contacts_store.list_all_contacts()
    trimmed = [{
        "id":                 c.get("id"),
        "name":               c.get("name"),
        "title":              c.get("title"),
        "partner_id":         c.get("partner_id"),
        "partner_name":       c.get("partner_name"),
        "email":              c.get("email"),
        "tier":               c.get("tier"),
        "is_key_stakeholder": c.get("is_key_stakeholder"),
        "mr_owner":           c.get("mr_owner"),
        "last_touched_at":    c.get("last_touched_at"),
        "status":             c.get("status"),
    } for c in contacts]
    return {"contacts": trimmed, "count": len(trimmed)}


@tool(
    "get_overdue_contacts",
    "List partner contacts that are past their touch cadence (overdue for "
    "outreach). Pass partner_id to scope to one partner. Use this for the "
    "'who should I reach out to' question.",
    {
        "type": "object",
        "properties": {
            "partner_id": {"type": "string",
                           "description": "Partner slug. Omit for all."},
        },
    },
    tags=("partners", "analysis"),
)
def _get_overdue_contacts(args: dict[str, Any]) -> dict[str, Any]:
    import partner_contacts_store
    partner_id = (args.get("partner_id") or "").strip() or None
    overdue = partner_contacts_store.overdue_contacts(partner_id)
    trimmed = [{
        "id":              c.get("id"),
        "name":            c.get("name"),
        "title":           c.get("title"),
        "partner_id":      c.get("partner_id"),
        "partner_name":    c.get("partner_name"),
        "last_touched_at": c.get("last_touched_at"),
        "mr_owner":        c.get("mr_owner"),
        "tier":            c.get("tier"),
    } for c in overdue]
    return {"overdue": trimmed, "count": len(trimmed)}


@tool(
    "get_stakeholder_coverage",
    "Compute key-stakeholder coverage: of the contacts the partnership "
    "team flagged as key, how many were engaged within the window. Returns "
    "overall totals plus a per-partner breakdown (worst coverage first) and "
    "action lists of stale / never-touched stakeholders.",
    {
        "type": "object",
        "properties": {
            "window_days": {"type": "integer", "minimum": 1, "maximum": 365,
                            "description": "Engagement window in days "
                                           "(default 30)."},
        },
    },
    tags=("partners", "analysis"),
)
def _get_stakeholder_coverage(args: dict[str, Any]) -> dict[str, Any]:
    import stakeholder_coverage
    window = int(args.get("window_days") or 30)
    window = max(1, min(window, 365))
    return stakeholder_coverage.compute(window_days=window)


# ---------------------------------------------------------------------
# Read tools — targets
# ---------------------------------------------------------------------

@tool(
    "get_quarterly_progress",
    "Read quarterly targets (plan vs actual) for a quarter. Pass quarter_id "
    "like '2026-Q2'; omit it for the latest quarter on file. Returns each "
    "metric's team plan, actual and attainment %.",
    {
        "type": "object",
        "properties": {
            "quarter_id": {"type": "string",
                           "description": "Quarter id, e.g. '2026-Q2'. "
                                          "Omit for the latest."},
        },
    },
    tags=("targets", "analysis"),
)
def _get_quarterly_progress(args: dict[str, Any]) -> dict[str, Any]:
    import quarterly_targets_store as qt
    qid = (args.get("quarter_id") or "").strip()
    quarter = None
    if qid:
        quarter = qt.get_quarter(qid)
        if quarter is None:
            return {"error": f"quarter not found: {qid}",
                    "available": [q.get("id") for q in qt.list_quarters()]}
    else:
        quarters = qt.list_quarters()
        if not quarters:
            return {"error": "no quarters configured"}
        # list_quarters is sorted; take the most recent by id.
        quarter = sorted(quarters, key=lambda q: q.get("id") or "")[-1]

    metrics_out = []
    for key, cell in (quarter.get("metrics") or {}).items():
        team = (cell or {}).get("team") or {}
        plan = team.get("plan") or 0
        actual = team.get("actual") or 0
        pct = int(round(actual / plan * 100)) if plan else None
        metrics_out.append({
            "metric":     key,
            "plan":       plan,
            "actual":     actual,
            "attainment_pct": pct,
        })
    return {
        "quarter_id": quarter.get("id"),
        "label":      quarter.get("label"),
        "metrics":    metrics_out,
    }


# ---------------------------------------------------------------------
# Read tools — use cases / proof points
# ---------------------------------------------------------------------

@tool(
    "list_use_cases",
    "List proof-point use cases from the Massive Rocket use-case catalog "
    "(real delivered client work). Filter by industry_slug or "
    "platform_slug. Returns title, client, problem/solution/outcome and "
    "metrics. Empty if the catalog DB isn't configured on this server.",
    {
        "type": "object",
        "properties": {
            "industry_slug": {"type": "string"},
            "platform_slug": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
    },
    tags=("proof", "research"),
)
def _list_use_cases(args: dict[str, Any]) -> dict[str, Any]:
    import usecases_db
    if not usecases_db.is_configured():
        return {"use_cases": [], "error": "use-case catalog DB not configured"}
    rows = usecases_db.list_use_cases(
        industry_slug=(args.get("industry_slug") or None),
        platform_slug=(args.get("platform_slug") or None),
        limit=int(args.get("limit") or 25),
    )
    return {"use_cases": rows, "count": len(rows)}


@tool(
    "match_proof_points",
    "Find the most relevant proof-point use cases for a lead, scored by "
    "industry match (+3) and platform / tech-stack overlap (+2 each). Use "
    "this when drafting outreach, briefs or pitches so claims are grounded "
    "in real delivered work. Never invent metrics not present in a result.",
    {
        "type": "object",
        "properties": {
            "industry":   {"type": "string",
                           "description": "Lead's industry (name or slug)."},
            "tech_stack": {"type": "array", "items": {"type": "string"},
                           "description": "Platforms the lead uses."},
            "limit":      {"type": "integer", "minimum": 1, "maximum": 20},
        },
    },
    tags=("proof", "research"),
)
def _match_proof_points(args: dict[str, Any]) -> dict[str, Any]:
    import usecases_db
    if not usecases_db.is_configured():
        return {"matches": [], "error": "use-case catalog DB not configured"}
    stack = args.get("tech_stack") or []
    if isinstance(stack, str):
        stack = [s.strip() for s in stack.split(",") if s.strip()]
    rows = usecases_db.match_for_lead(
        industry=(args.get("industry") or None),
        tech_stack=list(stack),
        limit=int(args.get("limit") or 6),
    )
    return {"matches": rows, "count": len(rows)}


# ---------------------------------------------------------------------
# Read tools — drafting
# ---------------------------------------------------------------------

@tool(
    "draft_outreach",
    "Draft a single outreach message (email / linkedin / slack) for a "
    "contact. Returns subject (email only), body and a ready-to-open "
    "mailto link. Drafts ONLY — never sends. Em-dashes are stripped "
    "automatically. Provide the contact as an object with at least a name.",
    {
        "type": "object",
        "properties": {
            "contact": {
                "type": "object",
                "description": "Contact details: name (required), title, "
                               "partner_name/account_name, email, "
                               "linkedin_url.",
                "properties": {
                    "name":         {"type": "string"},
                    "title":        {"type": "string"},
                    "partner_name": {"type": "string"},
                    "account_name": {"type": "string"},
                    "email":        {"type": "string"},
                    "linkedin_url": {"type": "string"},
                },
                "required": ["name"],
            },
            "channel": {"type": "string",
                        "enum": ["email", "linkedin", "slack"]},
            "tone": {"type": "string",
                     "enum": ["friendly", "re_engagement", "intro", "update"]},
            "context_hint": {"type": "string",
                             "description": "What the sender wants to convey."},
            "sender_name": {"type": "string",
                            "description": "Who the message is signed from."},
        },
        "required": ["contact", "channel"],
    },
    tags=("outreach",),
)
def _draft_outreach(args: dict[str, Any]) -> dict[str, Any]:
    import outreach
    contact = args.get("contact")
    if not isinstance(contact, dict) or not (contact.get("name") or "").strip():
        return {"error": "contact object with a name is required"}
    channel = (args.get("channel") or "").strip().lower()
    try:
        return outreach.draft(
            contact, channel,
            tone=(args.get("tone") or "friendly"),
            context_hint=(args.get("context_hint") or None),
            sender_name=(args.get("sender_name") or None),
        )
    except ValueError as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------
# Write tools
# ---------------------------------------------------------------------

@tool(
    "log_call",
    "Log a call / meeting / note against a lead. WRITE action — persists "
    "to the activity store. Provide lead_id and content; optionally type "
    "(call/meeting/note/email), title and attendees. Returns the saved "
    "record.",
    {
        "type": "object",
        "properties": {
            "lead_id": {"type": "string"},
            "content": {"type": "string",
                        "description": "The note / call summary text."},
            "type": {"type": "string",
                     "enum": ["call", "meeting", "note", "email"]},
            "title": {"type": "string"},
            "attendees": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["lead_id", "content"],
    },
    writes=True,
    tags=("pipeline",),
)
def _log_call(args: dict[str, Any]) -> dict[str, Any]:
    import calls_store
    lead_id = (args.get("lead_id") or "").strip()
    if not lead_id:
        return {"error": "lead_id required"}
    if not (args.get("content") or "").strip():
        return {"error": "content required"}
    try:
        record = calls_store.add_call(lead_id, {
            "content":   args.get("content"),
            "type":      args.get("type") or "note",
            "title":     args.get("title") or "",
            "attendees": args.get("attendees") or [],
        })
    except calls_store.CallsStoreError as e:
        return {"error": str(e)}
    return {"logged": True, "record": record}
