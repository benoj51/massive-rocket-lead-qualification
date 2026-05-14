"""
Notion sync for the Lead Qualification Tracker.

Talks to the Notion REST API directly (not via notion-client) so we get
first-class support for the 2025-09+ data-source-aware endpoints.

Public surface:
    NotionSync(data_source_id=..., api_key=...)
        .upsert(payload)         -- create or update a tracker page from the qualify() payload
        .list_pipeline(limit=50) -- read the DB for the Pipeline view in the UI
        .resolve_database_id()   -- fetch the parent DB id for a given data source

The payload shape consumed by upsert() is exactly what qualify_service.qualify()
returns.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import requests

NOTION_API = "https://api.notion.com/v1"
DEFAULT_VERSION = "2025-09-03"
DEFAULT_TIMEOUT = 30


class NotionSyncError(RuntimeError):
    """Wraps any non-2xx response from Notion with the upstream body."""


# --- Field mapping helpers -------------------------------------------------

_STATUS_MAP = {
    "qualify_in": "Qualified",
    "borderline": "Researching",
    "qualify_out": "Disqualified",
}

_OPPORTUNITY_MAP = {
    "retention": "Retention",
    "retention_light": "Retention Light",
    "migration": "Migration",
    "augmentation": "Augmentation",
    "greenfield": "Greenfield",
    "unknown": "Unknown",
}

_STACK_CONFIDENCE_MAP = {
    "confirmed": "Confirmed",
    "inferred": "Inferred",
    "speculated": "Speculated",
    "unknown": "Unknown",
}


def _rich_text(content: str, *, limit: int = 1900) -> list[dict]:
    """Notion rich_text values are capped at 2000 chars per block. Truncate cleanly."""
    if not content:
        return []
    return [{"type": "text", "text": {"content": str(content)[:limit]}}]


def _title(content: str) -> list[dict]:
    return [{"type": "text", "text": {"content": str(content or "")[:200]}}]


def _select(value: str | None) -> dict | None:
    if not value:
        return None
    return {"select": {"name": value}}


def _verticals_for_notion(vertical_label: str) -> str:
    """Coerce scorer's vertical label into a known Notion select option."""
    if not vertical_label:
        return "Other"
    s = vertical_label.lower()
    if "qsr" in s or "quick service" in s or "fast food" in s:
        return "QSR"
    if "roadside" in s or "fuel" in s or "petrol" in s or "gas station" in s:
        return "Roadside Convenience"
    if "delivery" in s:
        return "Delivery"
    if "convenience" in s or "c-store" in s:
        return "C-store"
    if "retail" in s or "ecommerce" in s or "e-commerce" in s:
        return "Retail"
    if "travel" in s or "hospitality" in s or "hotel" in s or "airline" in s:
        return "Travel"
    if "fintech" in s or "financial" in s or "bank" in s:
        return "Fintech"
    if "telecom" in s:
        return "Telecom"
    if "media" in s or "entertainment" in s or "gaming" in s:
        return "Media"
    if "health" in s or "pharma" in s:
        return "Healthcare"
    if "saas" in s or "software" in s:
        return "SaaS"
    return "Other"


def _payload_to_properties(payload: dict) -> dict[str, Any]:
    """Translate the qualify() payload into Notion property values."""
    company = payload.get("company") or {}
    score = payload.get("score") or {}
    discovered = payload.get("discovered") or {}
    opp = payload.get("opportunity") or {}
    meddicc = payload.get("meddicc") or {}

    status_key = score.get("status") or "borderline"
    opp_key = opp.get("type") or score.get("opportunity_type") or "unknown"
    stack_confidence_key = (discovered.get("stack_confidence") or "confirmed").lower()

    revenue_display = discovered.get("revenue") or ""
    if isinstance(revenue_display, (int, float)):
        revenue_display = f"${revenue_display:,.0f}"

    employees_display = discovered.get("employees")
    employees_display = "" if employees_display is None else f"{employees_display:,}"

    deal_size_label = discovered.get("deal_size_label") or ""

    props: dict[str, Any] = {
        "Company": {"title": _title(company.get("name") or "Unknown")},
        "URL": {"url": company.get("url") or None},
        "ICP Score": {"number": float(score.get("total_weighted") or 0)},
        "ICP Normalised": {"number": float(score.get("normalized_score") or 0)},
        "Status": _select(_STATUS_MAP.get(status_key, "Researching")),
        "Vertical": _select(_verticals_for_notion(score.get("breakdown", {}).get("vertical", {}).get("value", ""))),
        "Opportunity Type": _select(_OPPORTUNITY_MAP.get(opp_key, "Unknown")),
        "Stack Confidence": _select(_STACK_CONFIDENCE_MAP.get(stack_confidence_key, "Confirmed")),
        "Revenue": {"rich_text": _rich_text(revenue_display)},
        "Employees": {"rich_text": _rich_text(employees_display)},
        "Tech Stack": {"rich_text": _rich_text(discovered.get("tech_stack", ""))},
        "Region": {"rich_text": _rich_text(discovered.get("region", ""))},
        "Deal Size": {"rich_text": _rich_text(deal_size_label)},
        "Complexity": {"rich_text": _rich_text(discovered.get("complexity", ""))},
        "Fit Summary": {"rich_text": _rich_text(payload.get("fit_summary", ""))},
        "Next Steps": {"rich_text": _rich_text("\n".join(f"• {s}" for s in (payload.get("next_steps") or [])))},
        "Positive Signals": {"rich_text": _rich_text(", ".join(payload.get("signals") or []))},
        "Disqualifiers": {"rich_text": _rich_text(", ".join(payload.get("disqualifiers") or []))},
        "Qualified Date": {"date": {"start": datetime.now(timezone.utc).date().isoformat()}},
        "Owner": _select(payload.get("owner") or "Ben Ojuolape"),
    }

    # Sales Stage — optional; only set when the AE has picked one.
    sales_stage = payload.get("sales_stage")
    if sales_stage:
        props["Sales Stage"] = {"select": {"name": sales_stage}}

    # MEDDICC — only set if the AE filled it in.
    meddicc_score = 0
    meddicc_score_map = {"not_started": 0, "in_progress": 1, "confirmed": 3}
    for prop_name, key in (
        ("Metrics", "metrics"),
        ("Economic Buyer", "economic_buyer"),
        ("Decision Criteria", "decision_criteria"),
        ("Decision Process", "decision_process"),
        ("Identify Pain", "identify_pain"),
        ("Champion", "champion"),
    ):
        entry = meddicc.get(key) or {}
        n = meddicc_score_map.get((entry.get("status") or "not_started"), 0)
        meddicc_score += n
        props[prop_name] = {"number": n}
    props["MEDDICC Score"] = {"number": meddicc_score}

    # Drop None-valued select properties — Notion 400s on them.
    return {k: v for k, v in props.items() if v is not None}


# --- Page content blocks ---------------------------------------------------

_MEDDICC_FIELDS = (
    ("metrics",           "Metrics"),
    ("economic_buyer",    "Economic Buyer"),
    ("decision_criteria", "Decision Criteria"),
    ("decision_process",  "Decision Process"),
    ("identify_pain",     "Identify Pain"),
    ("champion",          "Champion"),
)
_STATUS_ICON = {"not_started": "○", "in_progress": "◐", "confirmed": "●"}


def _meddicc_blocks(payload: dict) -> list[dict]:
    """Render the AE's MEDDICC notes + statuses as page-body blocks.

    Called on both create (inline in `_page_blocks`) and update (appended via
    /blocks/{id}/children, so each push leaves an audit-trail entry).
    """
    meddicc = payload.get("meddicc") or {}
    if not any((meddicc.get(k) or {}).get("value") or (meddicc.get(k) or {}).get("status") not in (None, "not_started")
               for k, _ in _MEDDICC_FIELDS):
        return []
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    blocks: list[dict] = [
        {"object": "block", "type": "heading_3",
         "heading_3": {"rich_text": _rich_text(f"MEDDICC Notes — {stamp}")}},
    ]
    for key, label in _MEDDICC_FIELDS:
        entry = meddicc.get(key) or {}
        status = entry.get("status") or "not_started"
        note = (entry.get("value") or "").strip()
        line = f"{_STATUS_ICON[status]} {label} ({status.replace('_',' ')}): {note or '—'}"
        blocks.append({
            "object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": _rich_text(line)},
        })
    return blocks


def _page_blocks(payload: dict) -> list[dict]:
    score = payload.get("score") or {}
    breakdown = score.get("breakdown") or {}
    stakeholders = payload.get("stakeholders") or []

    blocks: list[dict] = [
        {
            "object": "block", "type": "heading_2",
            "heading_2": {"rich_text": _rich_text("Qualification Summary")},
        },
        {
            "object": "block", "type": "callout",
            "callout": {
                "rich_text": _rich_text(
                    f"ICP {score.get('normalized_score', 0)}/10 — "
                    f"{score.get('status_display', 'Unknown')} — "
                    f"{score.get('opportunity_label', '')}"
                ),
                "icon": {"emoji": "📊"},
            },
        },
        {
            "object": "block", "type": "heading_3",
            "heading_3": {"rich_text": _rich_text("Score Breakdown")},
        },
    ]
    for criterion, data in breakdown.items():
        name = criterion.replace("_", " ").title()
        blocks.append({
            "object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": _rich_text(
                    f"{name}: {data.get('value', 'N/A')} — {data.get('weighted', 0)}/{data.get('max_weighted', 0)} pts"
                )
            },
        })

    if payload.get("fit_summary"):
        blocks.extend([
            {"object": "block", "type": "heading_3",
             "heading_3": {"rich_text": _rich_text("Fit Analysis")}},
            {"object": "block", "type": "paragraph",
             "paragraph": {"rich_text": _rich_text(payload["fit_summary"])}},
        ])

    if payload.get("next_steps"):
        blocks.append({"object": "block", "type": "heading_3",
                       "heading_3": {"rich_text": _rich_text("Next Steps")}})
        for step in payload["next_steps"]:
            blocks.append({
                "object": "block", "type": "to_do",
                "to_do": {"rich_text": _rich_text(step), "checked": False},
            })

    if stakeholders:
        blocks.append({"object": "block", "type": "heading_3",
                       "heading_3": {"rich_text": _rich_text("Stakeholder Targets")}})
        for s in stakeholders[:10]:
            line = f"{s.get('name')} — {s.get('title')} [{s.get('priority')}] — {s.get('why')}"
            blocks.append({
                "object": "block", "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": _rich_text(line)},
            })

    # MEDDICC notes (only if the AE filled anything in).
    blocks.extend(_meddicc_blocks(payload))

    return blocks


# --- Pipeline view helper --------------------------------------------------

def _extract_text(prop: dict | None) -> str:
    if not prop:
        return ""
    if prop.get("type") == "title":
        return "".join(t.get("plain_text", "") for t in prop.get("title", []))
    if prop.get("type") == "rich_text":
        return "".join(t.get("plain_text", "") for t in prop.get("rich_text", []))
    if prop.get("type") == "url":
        return prop.get("url") or ""
    if prop.get("type") == "select":
        return (prop.get("select") or {}).get("name", "") or ""
    if prop.get("type") == "number":
        n = prop.get("number")
        return "" if n is None else str(n)
    if prop.get("type") == "date":
        d = prop.get("date") or {}
        return d.get("start") or ""
    return ""


def _row_from_page(page: dict) -> dict:
    props = page.get("properties") or {}
    return {
        "id": page.get("id"),
        "url": page.get("url"),
        "company": _extract_text(props.get("Company")),
        "company_url": _extract_text(props.get("URL")),
        "icp_normalised": props.get("ICP Normalised", {}).get("number"),
        "icp_score": props.get("ICP Score", {}).get("number"),
        "status": _extract_text(props.get("Status")),
        "sales_stage": _extract_text(props.get("Sales Stage")),
        "vertical": _extract_text(props.get("Vertical")),
        "opportunity_type": _extract_text(props.get("Opportunity Type")),
        "owner": _extract_text(props.get("Owner")),
        "next_steps": _extract_text(props.get("Next Steps")),
        "last_edited": page.get("last_edited_time"),
    }


# --- The sync class --------------------------------------------------------

class NotionSync:
    """REST client targeting the new data-source-aware Notion API."""

    def __init__(
        self,
        api_key: str | None = None,
        data_source_id: str | None = None,
        database_id: str | None = None,
        api_version: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("NOTION_API_KEY", "")
        self.data_source_id = data_source_id or os.environ.get("NOTION_DATA_SOURCE_ID", "")
        self.database_id = database_id or os.environ.get("NOTION_DATABASE_ID", "")
        self.api_version = api_version or os.environ.get("NOTION_API_VERSION", DEFAULT_VERSION)
        if not self.api_key:
            raise ValueError("NOTION_API_KEY is required.")
        if not (self.data_source_id or self.database_id):
            raise ValueError("Either NOTION_DATA_SOURCE_ID or NOTION_DATABASE_ID is required.")

    # ---- HTTP plumbing ----
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Notion-Version": self.api_version,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, *, json_body: dict | None = None) -> dict:
        url = f"{NOTION_API}{path}"
        resp = requests.request(method, url, headers=self._headers(), json=json_body, timeout=DEFAULT_TIMEOUT)
        if not resp.ok:
            raise NotionSyncError(f"Notion {method} {path} {resp.status_code}: {resp.text[:400]}")
        return resp.json()

    # ---- Public ----
    def resolve_database_id(self) -> str:
        """Look up the parent DB id for our data source, cache on self."""
        if self.database_id:
            return self.database_id
        ds = self._request("GET", f"/data_sources/{self.data_source_id}")
        parent = ds.get("parent") or {}
        db_id = parent.get("database_id")
        if not db_id:
            raise NotionSyncError("Data source has no parent database_id; check the data source ID is correct.")
        self.database_id = db_id
        return db_id

    def _parent(self) -> dict:
        if self.data_source_id:
            return {"type": "data_source_id", "data_source_id": self.data_source_id}
        return {"database_id": self.database_id}

    def _find_existing(self, company_name: str, company_url: str) -> dict | None:
        if not (company_name or company_url):
            return None
        filters: list[dict] = []
        if company_name:
            filters.append({"property": "Company", "title": {"equals": company_name}})
        if company_url:
            filters.append({"property": "URL", "url": {"equals": company_url}})
        body = {"filter": {"or": filters}, "page_size": 1} if len(filters) > 1 else {"filter": filters[0], "page_size": 1}

        if self.data_source_id:
            data = self._request("POST", f"/data_sources/{self.data_source_id}/query", json_body=body)
        else:
            data = self._request("POST", f"/databases/{self.database_id}/query", json_body=body)
        results = data.get("results") or []
        return results[0] if results else None

    def upsert(self, payload: dict) -> dict:
        """Create or update a tracker page. Returns {action, page_id, url}."""
        company = payload.get("company") or {}
        name = company.get("name", "")
        url = company.get("url", "")
        existing = self._find_existing(name, url)
        properties = _payload_to_properties(payload)
        if existing:
            page = self._request(
                "PATCH",
                f"/pages/{existing['id']}",
                json_body={"properties": properties},
            )
            # Append a fresh MEDDICC notes section on update so the AE's
            # latest captures aren't lost (we can't replace children in place).
            meddicc_extra = _meddicc_blocks(payload)
            if meddicc_extra:
                try:
                    self._request(
                        "PATCH",
                        f"/blocks/{existing['id']}/children",
                        json_body={"children": meddicc_extra},
                    )
                except NotionSyncError:
                    # Don't block the upsert on a block-append failure.
                    pass
            return {"action": "updated", "page_id": page.get("id"), "url": page.get("url")}
        page = self._request(
            "POST",
            "/pages",
            json_body={
                "parent": self._parent(),
                "properties": properties,
                "children": _page_blocks(payload),
            },
        )
        return {"action": "created", "page_id": page.get("id"), "url": page.get("url")}

    def list_pipeline(self, *, limit: int = 50) -> list[dict]:
        """Return pipeline rows for the UI's Pipeline view."""
        body = {"page_size": min(limit, 100), "sorts": [{"property": "ICP Normalised", "direction": "descending"}]}
        if self.data_source_id:
            data = self._request("POST", f"/data_sources/{self.data_source_id}/query", json_body=body)
        else:
            data = self._request("POST", f"/databases/{self.database_id}/query", json_body=body)
        return [_row_from_page(p) for p in (data.get("results") or [])]


def sync_to_notion(payload: dict) -> dict:
    """Module-level convenience for one-shot calls."""
    return NotionSync().upsert(payload)
