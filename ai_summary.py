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
                "note": (c.get("note") or (c.get("extracted") or {}).get("synthesised_note") or "")[:1200],
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


# ---------------------------------------------------------------------------
# Lead-level synthesis — rolls call history + scope + MEDDPICC into a single
# scannable summary for the top of the drawer
# ---------------------------------------------------------------------------

_LEAD_SUMMARY_SYSTEM_PROMPT = """You synthesise everything Massive Rocket
knows about a sales lead into a tight summary the AE can scan in 15
seconds. You receive: company info, the ICP score + status, the current
project streams, MEDDPICC entries collected so far, any project scope
notes, the full call/note history (synthesised + raw), the contact
list, and optionally a `group` block with parent/sibling brand context
(e.g. KFC's payload includes Yum! Brands as the parent plus Pizza Hut,
Taco Bell, Habit Burger as sibling brands with their statuses).

Return ONE JSON object, no preamble, no markdown fences:

{
  "state_of_play": "<2-3 sentence summary of where the deal sits right now>",
  "key_facts": [
    "<bullet 1 — what we know with confidence>",
    "<bullet 2>",
    "<bullet 3-5>"
  ],
  "open_questions": [
    "<bullet 1 — what we still need to learn>",
    "<bullet 2>",
    "<bullet 3-4>"
  ],
  "next_action": "<one sentence: the AE's next concrete move>",
  "risks": [
    "<concrete risk worth flagging, or omit the array entirely if none>"
  ]
}

Rules:
- 2–3 sentences for state_of_play. No fluff. Lead with the most important
  thing.
- 3–5 key_facts. Ground every bullet in the data — no fabrication.
- 3–4 open_questions — what specifically the AE should ask on the next
  call.
- next_action must be concrete and doable this week.
- Plain English. No em-dashes. No marketing tone.
- If the data is thin (e.g. only one note), say so honestly in
  state_of_play.

GROUP CONTEXT (when present):
- If `group.role == "child"`: the parent + sibling brands describe a
  family this lead belongs to (e.g. KFC inside Yum! Brands alongside
  Pizza Hut / Taco Bell / Habit Burger). Weave portfolio reality into
  the summary where it matters: surface sibling wins as reference
  points ("Pizza Hut is closed-won on a similar CDP build — use as
  proof"), call out central-buying risk if the parent looks like the
  real economic buyer, flag sibling status patterns ("3 of 4 Yum
  brands are mid-discovery — momentum") in key_facts. Do NOT pad
  open_questions with sibling info — keep questions specific to THIS
  lead.
- If `group.role == "parent"`: this lead is a holding/portfolio
  account. State of play should describe portfolio-wide momentum
  ("Yum portfolio: 2 of 4 brands in active discovery, 1 closed-won,
  1 dormant"). next_action is typically a portfolio-level move
  (executive briefing, MSA renewal, cross-brand reference call).
"""


def synthesise_lead(payload: dict) -> dict | None:
    """Aggregate everything known about a lead into a scannable summary.

    Returns the structured dict from the schema above, or None if AI
    is unconfigured / fails.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from anthropic import Anthropic
    except ImportError:
        return None

    try:
        client = Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=_DEFAULT_MODEL, max_tokens=1500,
            system=_LEAD_SUMMARY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(payload, default=str)}],
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
        log.warning("Lead synthesis failed: %s", e)
        return None
    # Normalise
    return {
        "state_of_play": str(data.get("state_of_play") or "").strip(),
        "key_facts": [str(b).strip() for b in (data.get("key_facts") or []) if str(b).strip()][:6],
        "open_questions": [str(b).strip() for b in (data.get("open_questions") or []) if str(b).strip()][:6],
        "next_action": str(data.get("next_action") or "").strip(),
        "risks": [str(b).strip() for b in (data.get("risks") or []) if str(b).strip()][:5],
    }


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
            {"note": (c.get("note") or (c.get("extracted") or {}).get("synthesised_note") or "")[:1000]}
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
    # v0.10.0j: 9th criterion. Budget Confirmed feeds the BANT-S Budget tile.
    "budget_confirmed",
]
_HEALTH_VALUES = {"red", "amber", "green"}

_EXTRACT_SYSTEM_PROMPT = """You read raw sales call notes or transcripts and
extract structured qualification data for an internal CRM agency (Massive
Rocket). You return ONE JSON object only, no preamble, no markdown fences.

Schema:
{
  "meddpicc": {
    "metrics":           {"value": "<short phrase or null>", "health": "<red|amber|green or null>"},
    "economic_buyer":    {"value": "<name + title, or null>", "health": "<red|amber|green or null>"},
    "decision_criteria": {"value": "<comma-separated criteria, or null>", "health": "<red|amber|green or null>"},
    "decision_process":  {"value": "<short summary, or null>", "health": "<red|amber|green or null>"},
    "paper_process":     {"value": "<procurement/legal notes, or null>", "health": "<red|amber|green or null>"},
    "identify_pain":     {"value": "<core pain, or null>", "health": "<red|amber|green or null>"},
    "champion":          {"value": "<name + title, or null>", "health": "<red|amber|green or null>"},
    "competition":       {"value": "<vendors mentioned, or null>", "health": "<red|amber|green or null>"},
    "budget_confirmed":  {"value": "<budget signal: amount, range, sign-off, or null>", "health": "<red|amber|green or null>"}
  },
  "project_scope": "<one short paragraph summarising what MR would deliver, or null>",
  "scope_criteria": {
    "crm_strategy": {"engagement_length": "<months, or null>", "lifecycle_maturity": "<1-5, or null>", "stakeholder_count": "<count, or null>", "roadmap_horizon": "<months, or null>"},
    "crm_build": {"migrating_campaigns": "<count, or null>", "new_campaigns": "<count, or null>", "templates_count": "<count, or null>", "html_templates_count": "<count, or null>", "channels": "<comma-separated, or null>", "execute_for_them": "<yes|no|null>", "crm_stakeholder": "<name + title, or null>", "economic_buyer": "<name + title, or null>"},
    "crm_execute": {"monthly_campaign_volume": "<count/month, or null>", "channels_executed": "<comma-separated, or null>"},
    "data_work": {"sources_to_connect": "<count, or null>", "cdp_target": "<vendor or null>", "warehouse_target": "<vendor or null>"},
    "engineering": {"integrations_count": "<count, or null>", "apis_to_build": "<count, or null>", "sdk_platform": "<Braze|Iterable|mParticle|Segment|Firebase|... or null>", "sdk_websites_count": "<count, or null>", "sdk_ios_apps_count": "<count, or null>", "sdk_android_apps_count": "<count, or null>", "sdk_hybrid_apps_count": "<count, or null>", "sdk_complexity": "<1-5, or null>"}
  },
  "contacts_mentioned": [
    {"name": "<full name as spoken>", "title": "<title if mentioned, else null>", "email": "<if mentioned, else null>", "role": "<prospect-side | mr-side | partner-side | unknown>"}
  ],
  "synthesised_note": "<a structured call summary in the MR Call Note format — see below>"
}

CONTACTS_MENTIONED rubric:
- Only include named people. Skip generic references ("the marketing
  team", "their VP", "someone in IT").
- Capture every person mentioned — attendees, people referenced ("Sara
  in legal still needs to review"), CC'd people, anyone identified by
  name.
- `role`:
  - "prospect-side" — people who work at the prospect/customer org
  - "mr-side" — people who work at Massive Rocket
  - "partner-side" — people at a technology partner (Braze, Snowflake,
    Hightouch, mParticle, etc.)
  - "unknown" — can't determine from context
- Don't fabricate emails or titles. If only the name was said, leave
  title and email as null.
- Return an empty array (not null) when no named people are mentioned.

SCOPE_CRITERIA rubric:
- Only fill values that are EXPLICITLY supported by the notes. Numbers and counts
  should appear verbatim ("30 campaigns to migrate" → migrating_campaigns: "30").
- Omit project_types where the notes don't mention anything matching that stream
  (e.g. don't return a "crm_execute" block if the call is about Engineering).
- For sdk_platform, use the vendor name as it appears (Braze, Iterable, mParticle,
  etc.). For channels / channels_executed, comma-separate (e.g. "email, push, sms").
- Counts can be strings ("30") — the platform parses them back.
- Set field to null (not omitted) when the topic was discussed but no concrete
  number was given, to signal "discussed but unknown". Omit the WHOLE project_type
  block when nothing relevant was discussed at all.

HEALTH rubric (use sparingly — only set when the notes give you a real signal):
- green = the criterion is clearly satisfied (e.g. CFO confirmed as buyer + budget approved)
- amber = the criterion is partially known but soft (e.g. VP champion identified but no exec
  sponsor; pain mentioned but not quantified)
- red = the criterion is actively concerning (e.g. no clear buyer despite 3 calls; competitor
  already evaluated and ahead; no budget allocated this fiscal year)
- null/omit = no signal in the notes — don't guess
Do NOT set health on every field by default. Only set it when the prospect said something
that genuinely supports the colour.

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
            # Bumped from 900 → 1800 in v0.9.4 after a long transcript truncated
            # mid-JSON-string and the parser failed. Long synthesised notes +
            # 8 MEDDPICC fields + project scope can easily exceed 900 tokens.
            max_tokens=1800,
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
        health = entry.get("health")
        # Only include a row when there's a usable signal — either value or health.
        if (value and value != "null") or (health in _HEALTH_VALUES):
            out: dict[str, Any] = {}
            if value and value != "null":
                out["value"] = str(value).strip()
            if health in _HEALTH_VALUES:
                out["health"] = health
            meddpicc_out[k] = out
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

    # v0.10.0x: scope_criteria — per-project-type field values extracted
    # from the notes. Filtered to non-null strings only; consumer merges
    # into project_store. Keys we don't know are ignored.
    scope_criteria_out: dict[str, dict[str, str]] = {}
    raw_sc = data.get("scope_criteria") or {}
    if isinstance(raw_sc, dict):
        for pt, fields in raw_sc.items():
            if not isinstance(fields, dict):
                continue
            cleaned: dict[str, str] = {}
            for k, v in fields.items():
                if v is None:
                    continue
                s = str(v).strip()
                if not s or s.lower() == "null":
                    continue
                cleaned[str(k)] = s
            if cleaned:
                scope_criteria_out[str(pt)] = cleaned

    # v1.0.0f (Tier 3c): named people mentioned in the notes.
    # Filtered for plausible names only — at minimum a name string,
    # and `role` falls back to "unknown".
    contacts_mentioned_out: list[dict[str, Any]] = []
    _valid_roles = {"prospect-side", "mr-side", "partner-side", "unknown"}
    for entry in data.get("contacts_mentioned") or []:
        if not isinstance(entry, dict):
            continue
        name = (entry.get("name") or "").strip()
        if not name or name.lower() == "null":
            continue
        title = entry.get("title")
        if title and str(title).lower() != "null":
            title = str(title).strip() or None
        else:
            title = None
        email = entry.get("email")
        if email and str(email).lower() != "null":
            email = str(email).strip() or None
        else:
            email = None
        role = str(entry.get("role") or "unknown").strip().lower()
        if role not in _valid_roles:
            role = "unknown"
        contacts_mentioned_out.append({
            "name": name, "title": title, "email": email, "role": role,
        })

    return {
        "meddpicc": meddpicc_out,
        "project_scope": project_scope,
        "synthesised_note": synthesised_note,
        "scope_criteria": scope_criteria_out or None,
        "contacts_mentioned": contacts_mentioned_out,
    }


# v1.0.0m: partner-contact-side synthesis. Mirrors `synthesise_lead`
# but for individual partner contacts (e.g. Marina at Braze). The
# schema is different — partner-contact conversations are about who
# THEY are working with (their accounts), what's changed, what their
# territory looks like, what blocks them, what they see opening up.

_PARTNER_CONTACT_CONVO_SYSTEM_PROMPT = """You synthesise the conversation
history Massive Rocket has had with a specific PARTNER contact (e.g. a
Braze AE, a Hightouch sales manager — not a prospect, not a customer).

You receive: the contact's name + title + territory + region + country,
the partner they work at (Braze / Hightouch / etc.), and the full
chronological note history. The MOST RECENT note is flagged so you can
weight it.

Return ONE JSON object, no preamble, no markdown fences:

{
  "summary": "<2-3 sentence summary of the MOST RECENT conversation —
              what was discussed, the headline takeaway>",
  "accounts_discussed": [
    "<account name + 1-line context — accounts THEY mentioned in the
      most recent conversation (their customers / prospects, not MR's)>"
  ],
  "updates_on_prior_accounts": [
    "<account from a PRIOR conversation + what's changed since
      (new info, status shift, deal moved, etc.). Empty array if there
      are no prior accounts to update on.>"
  ],
  "territory_info": [
    "<bullet about their patch — geography they cover, the segment
      they own (Strategic Ent / Enterprise / Scale), what their book
      looks like, who their managers are, recent re-orgs that affect
      them>"
  ],
  "challenges": [
    "<a specific friction THEY surfaced — internal process, tooling,
      missing exec sponsorship, ramp pressure, anything blocking them>"
  ],
  "opportunities": [
    "<an opening THEY see — for their patch, for the MR partnership,
      for a co-sell, for an account MR could be a wedge for>"
  ],
  "additional_info": "<anything else worth recording that doesn't fit
                      the buckets above — personal context, comp
                      structure, manager preferences, sibling teams.
                      Empty string if nothing.>"
}

Rules:
- Ground every bullet in the notes. Do NOT fabricate.
- Plain English. No em-dashes. No marketing tone.
- Lead with what the contact ACTUALLY said. Avoid generic
  partner-success cliches.
- If the data is thin (only one note), `updates_on_prior_accounts`
  should be an empty array and `summary` should acknowledge the
  thinness honestly.
- Keep each array to at most 6 bullets — concision over completeness.
- The audience is the partnerships AE (Ben) glancing at the contact
  card before their next call. Optimise for "what do I need to
  remember before I speak to this person again."
"""


def synthesise_partner_contact_conversation(payload: dict) -> dict | None:
    """Run Claude across a partner contact's note history + return the
    structured 7-field summary. Returns None if AI is unconfigured or
    the call fails (best-effort — never raises).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from anthropic import Anthropic
    except ImportError:
        return None

    try:
        client = Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=_DEFAULT_MODEL, max_tokens=1500,
            system=_PARTNER_CONTACT_CONVO_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(payload, default=str)}],
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
        log.warning("Partner-contact conversation synthesis failed: %s", e)
        return None

    def _str_list(key: str, cap: int = 6) -> list[str]:
        out: list[str] = []
        for b in (data.get(key) or []):
            # Drop genuine None entries — str(None) would produce the
            # literal string "None" which would leak into the UI.
            if b is None:
                continue
            s = str(b).strip()
            if s:
                out.append(s)
        return out[:cap]

    return {
        "summary":                    str(data.get("summary") or "").strip(),
        "accounts_discussed":         _str_list("accounts_discussed"),
        "updates_on_prior_accounts":  _str_list("updates_on_prior_accounts"),
        "territory_info":             _str_list("territory_info"),
        "challenges":                 _str_list("challenges"),
        "opportunities":              _str_list("opportunities"),
        "additional_info":            str(data.get("additional_info") or "").strip(),
    }
