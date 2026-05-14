"""Weekly Slack digest of the qualification platform.

Generates a Slack Block Kit message from the current pipeline + the last
N audit events. Posting is gated by SLACK_WEBHOOK_URL — when unset,
`send_digest` returns {sent: False, reason: ...} without making a network
call.

The digest is designed to land in #partnerships once a week (Monday 09:00
London). Schedule it via Railway Cron, an external scheduler, or a
manual trigger to /api/slack/digest.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

log = logging.getLogger("mr.slack_digest")

DEFAULT_TIMEOUT = 10


def is_configured() -> bool:
    return bool(os.environ.get("SLACK_WEBHOOK_URL", "").strip())


def _top_pipeline_lines(rows: list[dict], n: int = 5) -> list[str]:
    """Top N rows by ICP, formatted as one-liners."""
    sorted_rows = sorted(rows, key=lambda r: r.get("icp_normalised") or 0, reverse=True)
    out: list[str] = []
    for r in sorted_rows[:n]:
        score = r.get("icp_normalised")
        score_str = f"{score:.1f}" if isinstance(score, (int, float)) else "—"
        status = r.get("status") or "—"
        company = r.get("company") or "?"
        stage = r.get("sales_stage") or "—"
        out.append(f"• *{company}* — {score_str}/10 — {status} — _{stage}_")
    return out


def _recent_qualifications(events: list[dict], n: int = 5) -> list[str]:
    """Most recent `qualified` events as one-liners."""
    qualified = [e for e in events if e.get("type") == "qualified"]
    out: list[str] = []
    for e in qualified[:n]:
        company = e.get("company") or "?"
        score = e.get("score")
        score_str = f"{score:.1f}" if isinstance(score, (int, float)) else "—"
        status = e.get("status") or "—"
        out.append(f"• *{company}* — {score_str}/10 — {status}")
    return out


def build_digest(*, pipeline_rows: list[dict], audit_events: list[dict],
                 title: str = "Lead Qualification — Weekly Digest") -> dict:
    """Build the Slack Block Kit payload. Pure function, no network."""
    audit_events = audit_events or []
    pipeline_rows = pipeline_rows or []

    qualified_in = sum(1 for e in audit_events if e.get("type") == "qualified" and e.get("status") == "qualify_in")
    borderline = sum(1 for e in audit_events if e.get("type") == "qualified" and e.get("status") == "borderline")
    qualified_out = sum(1 for e in audit_events if e.get("type") == "qualified" and e.get("status") == "qualify_out")
    notion_syncs = sum(1 for e in audit_events if e.get("type") == "notion_sync")

    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": title}},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Pipeline size:* {len(pipeline_rows)}"},
                {"type": "mrkdwn", "text": f"*Notion syncs:* {notion_syncs}"},
                {"type": "mrkdwn", "text": f"*Qualified In:* {qualified_in}"},
                {"type": "mrkdwn", "text": f"*Borderline:* {borderline}"},
                {"type": "mrkdwn", "text": f"*Qualified Out:* {qualified_out}"},
            ],
        },
    ]

    top = _top_pipeline_lines(pipeline_rows, n=5)
    if top:
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
                       "text": "*Top 5 by ICP*\n" + "\n".join(top)}})

    recent = _recent_qualifications(audit_events, n=5)
    if recent:
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
                       "text": "*Recent qualifications*\n" + "\n".join(recent)}})

    return {"blocks": blocks}


def send_digest(payload: dict) -> dict:
    """Post a Block Kit payload to Slack. Returns {sent, reason}."""
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook:
        return {"sent": False, "reason": "SLACK_WEBHOOK_URL not configured"}
    try:
        resp = requests.post(webhook, json=payload, timeout=DEFAULT_TIMEOUT)
        if resp.status_code >= 400:
            log.warning("Slack webhook %s: %s", resp.status_code, resp.text[:200])
            return {"sent": False, "reason": f"Slack {resp.status_code}: {resp.text[:200]}"}
        return {"sent": True, "reason": "ok"}
    except requests.RequestException as e:
        log.warning("Slack webhook error: %s", e)
        return {"sent": False, "reason": str(e)}
