"""Outreach drafting (v1.0.0df).

Given a contact + channel + tone + optional context, produces a
draft message the AE can copy / paste / send. Drafts only - never
auto-sends. Caller is responsible for actually delivering.

Channels
--------
- email     -> subject + body, body 2-3 short paragraphs, signed
- linkedin  -> single message <300 chars, no subject, no signature
- slack     -> single message <200 chars, casual

The drafts follow Ben's writing-style memory: no em-dashes, no AI
cadence, plain English. Channel-specific length caps stop the model
running long.

Public API
----------
draft(contact: dict, channel: str, *, tone: str = "friendly",
      context_hint: str | None = None, recent_notes: list = None,
      sender_name: str | None = None) -> dict
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

log = logging.getLogger(__name__)

VALID_CHANNELS = {"email", "linkedin", "slack"}
VALID_TONES = {
    "friendly":      "Warm + direct. You're catching up or making a small ask.",
    "re_engagement": "Acknowledge time has passed. Brief, no apology, "
                     "offer one concrete reason to reconnect.",
    "intro":         "First touch. Reference what you know about them + the "
                     "partner relationship; keep it short.",
    "update":        "Share a concrete update (deal, account, project) and "
                     "ask one short question.",
}


# ---------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------

def _channel_rules(channel: str) -> str:
    """Per-channel constraints baked into the system prompt so the
    model never writes a 5-paragraph LinkedIn DM."""
    if channel == "email":
        return (
            "FORMAT: An email with a 'Subject:' line then a blank line then "
            "the body. Subject < 60 characters. Body 2-3 short paragraphs, "
            "max 120 words total. Sign off with the sender's first name only. "
            "No greeting beyond a simple 'Hi <FirstName>,'."
        )
    if channel == "linkedin":
        return (
            "FORMAT: A single LinkedIn DM. Under 280 characters total "
            "(LinkedIn limit is 300 - leave headroom). Plain text. "
            "No subject. No signature. One concrete ask."
        )
    if channel == "slack":
        return (
            "FORMAT: A single Slack DM. Under 200 characters. Casual but "
            "professional. No greeting fluff ('Hope you're well'). "
            "One concrete ask."
        )
    raise ValueError(f"Unknown channel: {channel}")


def _build_system_prompt(channel: str, tone_key: str) -> str:
    tone_desc = VALID_TONES.get(tone_key, VALID_TONES["friendly"])
    return f"""You draft outreach messages for Massive Rocket account
executives. Massive Rocket is a Braze + Hightouch + Snowflake
consultancy specialising in CRM, data, and engineering for B2C
brands (QSR, retail, financial services, etc).

You receive a contact's details (name, title, partner / account,
recent notes if any) and a channel + tone. Produce a draft the AE
will review before sending.

WRITING STYLE
- Plain English. No marketing tone. No em-dashes. No "I hope this
  finds you well" or other AI cliches.
- Specific over generic: reference the partner / account / role
  rather than abstract language.
- One concrete ask per message. No multi-question paragraphs.
- Never invent facts. If you don't have detail to ground a claim,
  leave it out.

TONE
{tone_desc}

{_channel_rules(channel)}

OUTPUT
Return ONLY the message. No surrounding commentary, no JSON, no
backticks. For email, the FIRST line MUST be "Subject: <line>"
then a blank line then the body."""


def _build_user_msg(contact: dict, sender_name: str | None,
                     context_hint: str | None,
                     recent_notes: list[dict] | None) -> str:
    name = contact.get("name") or "this contact"
    first = (name.split()[0] if name else "there")
    title = contact.get("title")
    partner = contact.get("partner_name") or contact.get("account_name") or ""
    email = contact.get("email")
    linkedin = contact.get("linkedin_url")
    last_touched = contact.get("last_touched_at")

    lines = [f"Contact: {name}"]
    if title:    lines.append(f"Title: {title}")
    if partner:  lines.append(f"At: {partner}")
    if email:    lines.append(f"Email: {email}")
    if linkedin: lines.append(f"LinkedIn: {linkedin}")
    if last_touched:
        lines.append(f"Last touched: {last_touched}")
    if sender_name:
        lines.append(f"Sender (you'll sign as their first name): {sender_name}")
    lines.append(f"Use the first name when addressing them: {first}")

    if context_hint:
        lines.append("")
        lines.append(f"What the sender wants to convey: {context_hint.strip()}")

    if recent_notes:
        lines.append("")
        lines.append("Recent notes on this contact (most recent first):")
        for n in recent_notes[:5]:
            content = (n.get("content") or "").strip()
            if not content:
                continue
            # Trim verbose notes; the model needs gist not transcript
            snippet = content if len(content) <= 280 else content[:280] + "..."
            ts = (n.get("created_at") or "")[:10]
            lines.append(f"- ({ts}) {snippet}")

    return "\n".join(lines)


# ---------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------

_SUBJECT_RE = re.compile(r"^Subject:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)


def _parse_email(raw: str) -> tuple[str | None, str]:
    """Pull 'Subject: ...' out, return (subject, body)."""
    m = _SUBJECT_RE.search(raw)
    if not m:
        return None, raw.strip()
    subject = m.group(1).strip()
    # Body is everything after the subject line, stripped of leading
    # blank lines.
    body = raw[m.end():].lstrip("\n").rstrip()
    return subject, body


# ---------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------

def is_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def draft(contact: dict[str, Any], channel: str, *,
           tone: str = "friendly",
           context_hint: str | None = None,
           recent_notes: list[dict] | None = None,
           sender_name: str | None = None,
           model: str | None = None) -> dict[str, Any]:
    """Draft a single-channel outreach message. Returns:

      {
        "channel":  "email" | "linkedin" | "slack",
        "tone":     <tone key>,
        "subject":  <str | None>,     # email only
        "body":     <str>,
        "mailto":   <str | None>,     # email only, ready-to-open url
        "char_count": <int>,
      }

    Raises ValueError on bad channel / tone. Returns body=""
    when Anthropic isn't configured (caller surfaces a clearer
    "AI not configured" message).
    """
    channel = (channel or "").strip().lower()
    if channel not in VALID_CHANNELS:
        raise ValueError(f"channel must be one of {sorted(VALID_CHANNELS)}")
    tone = (tone or "friendly").strip().lower()
    if tone not in VALID_TONES:
        tone = "friendly"

    if not is_configured():
        return {
            "channel": channel, "tone": tone,
            "subject": None, "body": "",
            "mailto": None, "char_count": 0,
            "error": "Anthropic API key not set on the server",
        }

    try:
        from anthropic import Anthropic
    except ImportError:
        log.warning("anthropic SDK not installed; draft unavailable")
        return {
            "channel": channel, "tone": tone,
            "subject": None, "body": "",
            "mailto": None, "char_count": 0,
            "error": "anthropic SDK not installed",
        }

    system = _build_system_prompt(channel, tone)
    user = _build_user_msg(contact, sender_name, context_hint, recent_notes)
    # Channel max tokens. Email needs ~500, LinkedIn/Slack much less.
    max_tokens = 700 if channel == "email" else 250

    try:
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"].strip())
        msg = client.messages.create(
            model=(model or os.environ.get("ANTHROPIC_MODEL")
                    or "claude-sonnet-4-5"),
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        raw = ""
        for block in msg.content:
            text = getattr(block, "text", None) or ""
            if text:
                raw = text
                break
        raw = raw.strip()
    except Exception as e:
        log.warning("Outreach draft failed: %s", e)
        return {
            "channel": channel, "tone": tone,
            "subject": None, "body": "",
            "mailto": None, "char_count": 0,
            "error": str(e),
        }

    subject = None
    body = raw
    if channel == "email":
        subject, body = _parse_email(raw)

    mailto = None
    if channel == "email" and contact.get("email"):
        # Quote the body and subject for mailto:; encodeURIComponent
        # equivalent for python-side.
        from urllib.parse import quote
        params = []
        if subject:
            params.append(f"subject={quote(subject)}")
        if body:
            params.append(f"body={quote(body)}")
        qs = "&".join(params)
        mailto = f"mailto:{contact['email']}" + (f"?{qs}" if qs else "")

    return {
        "channel": channel,
        "tone": tone,
        "subject": subject,
        "body": body,
        "mailto": mailto,
        "char_count": len(body or ""),
    }
