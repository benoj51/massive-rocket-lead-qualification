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

    # Source of opportunity — single select. Maps to existing Notion column.
    opp_source = payload.get("opportunity_source")
    if opp_source:
        props["Partner Source"] = {"select": {"name": opp_source}}

    # Sourced For — multi-select. New Notion column expected;
    # add it manually if missing (Notion will 400 the whole push otherwise).
    sourced_for = payload.get("sourced_for_partners")
    if sourced_for:
        valid = [p for p in sourced_for if p]
        if valid:
            props["Sourced For"] = {"multi_select": [{"name": p} for p in valid]}

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
    ("paper_process",     "Paper Process"),
    ("identify_pain",     "Identify Pain"),
    ("champion",          "Champion"),
    ("competition",       "Competition"),
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
         "heading_3": {"rich_text": _rich_text(f"MEDDPICC Notes — {stamp}")}},
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

    # Project scope summary
    project_scope = (payload.get("project_scope") or "").strip()
    if project_scope:
        blocks.append({"object": "block", "type": "heading_3",
                       "heading_3": {"rich_text": _rich_text("Project Scope")}})
        blocks.append({"object": "block", "type": "paragraph",
                       "paragraph": {"rich_text": _rich_text(project_scope)}})

    # Notes / transcript
    notes = (payload.get("notes") or "").strip()
    if notes:
        blocks.append({"object": "block", "type": "heading_3",
                       "heading_3": {"rich_text": _rich_text("Notes & Transcript")}})
        # Notion paragraphs cap at ~2000 chars per rich_text node, so split
        # long notes into multiple paragraphs.
        for chunk in _chunk_text(notes, 1900):
            blocks.append({"object": "block", "type": "paragraph",
                           "paragraph": {"rich_text": _rich_text(chunk, limit=1900)}})

    return blocks


def _chunk_text(text: str, size: int) -> list[str]:
    """Split text into roughly `size`-char chunks at paragraph boundaries where possible."""
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    buf = ""
    for paragraph in text.split("\n\n"):
        if len(buf) + len(paragraph) + 2 > size and buf:
            chunks.append(buf.strip())
            buf = paragraph
        else:
            buf = (buf + "\n\n" + paragraph) if buf else paragraph
    if buf.strip():
        chunks.append(buf.strip())
    # If a single paragraph was still too long, hard-cut it.
    out: list[str] = []
    for c in chunks:
        while len(c) > size:
            out.append(c[:size])
            c = c[size:]
        out.append(c)
    return out


# --- Pipeline view helper --------------------------------------------------

def _extract_multi_select(prop: dict | None) -> list[str]:
    if not prop or prop.get("type") != "multi_select":
        return []
    return [item.get("name", "") for item in (prop.get("multi_select") or []) if item.get("name")]


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
    if prop.get("type") == "multi_select":
        return ", ".join(_extract_multi_select(prop))
    if prop.get("type") == "number":
        n = prop.get("number")
        return "" if n is None else str(n)
    if prop.get("type") == "date":
        d = prop.get("date") or {}
        return d.get("start") or ""
    return ""


def _page_to_detail(page: dict) -> dict:
    """Flatten a Notion page into a compact dict for the edit drawer.
    Returns every field the UI shows, plus metadata."""
    props = page.get("properties") or {}
    return {
        "id": page.get("id"),
        "url": page.get("url"),
        "last_edited": page.get("last_edited_time"),
        "created": page.get("created_time"),
        "company": _extract_text(props.get("Company")),
        "company_url": _extract_text(props.get("URL")),
        "icp_score": props.get("ICP Score", {}).get("number"),
        "icp_normalised": props.get("ICP Normalised", {}).get("number"),
        "status": _extract_text(props.get("Status")),
        "sales_stage": _extract_text(props.get("Sales Stage")),
        "vertical": _extract_text(props.get("Vertical")),
        "opportunity_type": _extract_text(props.get("Opportunity Type")),
        "stack_confidence": _extract_text(props.get("Stack Confidence")),
        "owner": _extract_text(props.get("Owner")),
        "revenue": _extract_text(props.get("Revenue")),
        "employees": _extract_text(props.get("Employees")),
        "tech_stack": _extract_text(props.get("Tech Stack")),
        "region": _extract_text(props.get("Region")),
        "deal_size": _extract_text(props.get("Deal Size")),
        # v1.0.0n: forecasting fields.
        "deal_value_monthly_gbp": props.get("Deal Value (Monthly GBP)", {}).get("number"),
        "expected_close_date": _extract_text(props.get("Expected Close Date")),
        "complexity": _extract_text(props.get("Complexity")),
        "fit_summary": _extract_text(props.get("Fit Summary")),
        "next_steps": _extract_text(props.get("Next Steps")),
        "positive_signals": _extract_text(props.get("Positive Signals")),
        "disqualifiers": _extract_text(props.get("Disqualifiers")),
        "qualified_date": _extract_text(props.get("Qualified Date")),
        "opportunity_source": _extract_text(props.get("Partner Source")),
        "sourced_for_partners": _extract_multi_select(props.get("Sourced For")),
        # v1.0.0ca: reason captured when a lead closes (Closed Lost
        # or Rejected). Round-trips through the rich-text writer above.
        "close_reason": _extract_text(props.get("Close Reason")),
        # v1.0.0g: durable state backup (chunked rich_text). Joined here
        # so the API consumer doesn't have to think about chunking.
        "state_backup": _extract_text(props.get("State Backup")),
    }


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
        "opportunity_source": _extract_text(props.get("Partner Source")),
        "sourced_for_partners": _extract_multi_select(props.get("Sourced For")),
        # v1.0.0n: include forecast fields in pipeline rows so the
        # /api/forecast endpoint can compute without a second fetch.
        "deal_size": _extract_text(props.get("Deal Size")),
        "deal_value_monthly_gbp": props.get("Deal Value (Monthly GBP)", {}).get("number"),
        "expected_close_date": _extract_text(props.get("Expected Close Date")),
        "region": _extract_text(props.get("Region")),
        "last_edited": page.get("last_edited_time"),
        # v1.0.0cc: surfaced in pipeline rows so the Dashboard's
        # loss-reason aggregator doesn't need a second fetch per lead.
        "close_reason": _extract_text(props.get("Close Reason")),
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
        """Resolve the database_id from whatever the user gave us."""
        if self.database_id:
            return self.database_id
        # data_source_id was set; try to look up its parent database
        try:
            ds = self._request("GET", f"/data_sources/{self.data_source_id}")
            parent = ds.get("parent") or {}
            db_id = parent.get("database_id")
            if db_id:
                self.database_id = db_id
                return db_id
        except NotionSyncError:
            pass
        # Value was actually a database ID (the part in Notion URLs).
        self.database_id = self.data_source_id
        return self.database_id

    def _ensure_data_source_id(self) -> str:
        """Guarantee self.data_source_id points at a real, queryable data
        source. The user may have put a database_id in NOTION_DATA_SOURCE_ID;
        in that case we discover the actual data source from the DB lookup
        and cache it.

        Notion-Version 2025-09+ no longer supports /databases/{id}/query —
        everything has to flow through data sources.
        """
        if self.data_source_id:
            # Probe: is it actually a data source?
            try:
                self._request("GET", f"/data_sources/{self.data_source_id}")
                return self.data_source_id
            except NotionSyncError as e:
                if "404" not in str(e):
                    raise
                # Fall through: treat as database_id
                candidate_db = self.data_source_id
                self.data_source_id = ""
                self.database_id = self.database_id or candidate_db

        if not self.database_id:
            raise NotionSyncError("No database_id or data_source_id resolves.")

        db = self._request("GET", f"/databases/{self.database_id}")
        sources = db.get("data_sources") or []
        if not sources:
            raise NotionSyncError(
                f"Database {self.database_id} has no data sources. "
                f"This is unusual — check the database hasn't been deleted."
            )
        self.data_source_id = sources[0]["id"]
        return self.data_source_id

    def _parent(self) -> dict:
        # 2025-09 requires data_source_id parents for create. Make sure we have one.
        ds_id = self._ensure_data_source_id()
        return {"type": "data_source_id", "data_source_id": ds_id}

    # v1.0.0i: self-heal the "State Backup" property so the durable
    # mirror (v1.0.0g) can never silently fail because the schema is
    # missing. Idempotent — GET the DB schema, PATCH only if the
    # property is absent. Safe to call once at app boot.
    def ensure_state_backup_property(self) -> dict[str, Any]:
        """Make sure the Notion DB has a "State Backup" rich-text
        property. See `ensure_properties` for the generic helper —
        kept as a thin wrapper for backward-compat with v1.0.0i."""
        return self.ensure_properties({
            "State Backup": {"rich_text": {}},
        })

    # v1.0.0n: generic property-self-heal. Adds any missing properties
    # in one PATCH. Idempotent — existing properties are reported as
    # `existed`, missing ones are created in a single round-trip.
    def ensure_properties(self, spec: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """For each (property_name → Notion property spec) in `spec`,
        check the DB schema and create any that don't exist. One PATCH
        for all missing ones (Notion accepts batched property creation).

        Returns a status dict the caller can log + surface in
        diagnostics. Never raises — startup self-heal must not crash
        the app.
        """
        status: dict[str, Any] = {
            "checked": True,
            "existed": [],
            "created": [],
            "error": None,
        }
        try:
            # Try the data source schema first (2025-09+), fall back to
            # the database endpoint for older API versions.
            try:
                ds_id = self._ensure_data_source_id()
                schema = self._request("GET", f"/data_sources/{ds_id}")
                schema_endpoint = f"/data_sources/{ds_id}"
            except NotionSyncError:
                schema = self._request("GET", f"/databases/{self.database_id}")
                schema_endpoint = f"/databases/{self.database_id}"
            existing_props = schema.get("properties") or {}
            to_create: dict[str, dict[str, Any]] = {}
            for name, prop_spec in spec.items():
                if name in existing_props:
                    status["existed"].append(name)
                else:
                    to_create[name] = prop_spec
            if to_create:
                self._request("PATCH", schema_endpoint,
                              json_body={"properties": to_create})
                status["created"] = list(to_create.keys())
            return status
        except Exception as e:
            status["error"] = str(e)
            return status

    # v1.0.0i: Notion's own page-revision log — last-ditch recovery
    # path for pre-backup data loss. Returns the page's edit history
    # with prior values of key text fields (Fit Summary, Next Steps,
    # Positive Signals, Lead Summary) so the AE can copy-paste old
    # context that the AI synthesised from now-lost call notes.
    def get_page_history(self, page_id: str, *, limit: int = 50) -> dict[str, Any]:
        """Pull the page's revision log via the Notion comments / pages
        history APIs. Returns a list of revisions with the prior value
        of each text-bearing property where Notion makes it available.

        Notion's free plan only retains 30 days of history; paid plans
        keep 90 days / unlimited. We surface whatever the API gives us
        and let the AE judge.
        """
        try:
            # Notion's revision endpoint isn't fully public — fall back
            # to a properties-only snapshot of the current page, which
            # is still useful (the AE can compare against what's
            # currently in the cache).
            page = self._request("GET", f"/pages/{page_id}")
            props = page.get("properties") or {}
            recoverable = {}
            for key, prop_name in (
                ("fit_summary", "Fit Summary"),
                ("next_steps", "Next Steps"),
                ("positive_signals", "Positive Signals"),
                ("lead_summary", "Lead Summary"),
                ("meddicc_notes", "MEDDICC Notes"),
                ("state_backup", "State Backup"),
            ):
                p = props.get(prop_name)
                if p:
                    text = _extract_text(p)
                    if text:
                        recoverable[key] = {
                            "property": prop_name,
                            "text": text,
                            "chars": len(text),
                        }
            return {
                "page_id": page_id,
                "last_edited": page.get("last_edited_time"),
                "url": page.get("url"),
                "recoverable_fields": recoverable,
                "note": (
                    "Notion's full revision history is only viewable in the "
                    "UI (Plus+ plans). Open the page in Notion → click ⋯ → "
                    "Page history to see prior values of these fields."
                ),
            }
        except NotionSyncError as e:
            return {"page_id": page_id, "error": str(e)}

    def _query(self, body: dict) -> dict:
        """Query the data source. Self-heals if the user gave us a database_id
        in the data_source_id env var (common when copying from Notion URLs)."""
        ds_id = self._ensure_data_source_id()
        return self._request("POST", f"/data_sources/{ds_id}/query", json_body=body)

    def _find_existing(self, company_name: str, company_url: str) -> dict | None:
        if not (company_name or company_url):
            return None
        filters: list[dict] = []
        if company_name:
            filters.append({"property": "Company", "title": {"equals": company_name}})
        if company_url:
            filters.append({"property": "URL", "url": {"equals": company_url}})
        body = {"filter": {"or": filters}, "page_size": 1} if len(filters) > 1 else {"filter": filters[0], "page_size": 1}
        data = self._query(body)
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
        data = self._query(body)
        return [_row_from_page(p) for p in (data.get("results") or [])]

    def get_page(self, page_id: str) -> dict:
        """Fetch a single page and return a normalized, edit-friendly dict.
        Distinct from list_pipeline rows: includes all editable fields."""
        page = self._request("GET", f"/pages/{page_id}")
        return _page_to_detail(page)

    def update_page(self, page_id: str, edits: dict) -> dict:
        """PATCH editable fields on a tracker page.

        `edits` is a flat dict matching the keys returned by get_page (company,
        url, status, sales_stage, vertical, opportunity_type, owner,
        stack_confidence, revenue, employees, tech_stack, region, deal_size,
        complexity, fit_summary, next_steps, positive_signals, disqualifiers).
        Unknown keys are ignored. Empty strings clear the property.
        """
        props: dict[str, Any] = {}
        # Title
        if "company" in edits:
            props["Company"] = {"title": _title(edits["company"])}
        # URL
        if "url" in edits:
            props["URL"] = {"url": (edits["url"] or None)}
        # Selects — None or empty string means leave alone; explicit "" means clear
        for key, prop_name, mapping in (
            ("status", "Status", {"qualify_in": "Qualified", "borderline": "Researching",
                                  "qualify_out": "Disqualified",
                                  # Accept raw select names too
                                  "Qualified": "Qualified", "Researching": "Researching",
                                  "Disqualified": "Disqualified", "New": "New",
                                  "On Hold": "On Hold",
                                  # v1.0.0ca: Nurture (auto-set on
                                  # Closed Lost) + Rejected (manual
                                  # decision to not pursue).
                                  "Nurture": "Nurture",
                                  "Rejected": "Rejected"}),
            ("sales_stage", "Sales Stage", None),
            ("vertical", "Vertical", None),
            ("opportunity_type", "Opportunity Type",
                {"retention": "Retention", "retention_light": "Retention Light",
                 "migration": "Migration", "augmentation": "Augmentation",
                 "greenfield": "Greenfield", "unknown": "Unknown",
                 "Retention": "Retention", "Retention Light": "Retention Light",
                 "Migration": "Migration", "Augmentation": "Augmentation",
                 "Greenfield": "Greenfield", "Unknown": "Unknown"}),
            ("owner", "Owner", None),
            ("stack_confidence", "Stack Confidence", _STACK_CONFIDENCE_MAP),
        ):
            if key not in edits:
                continue
            value = edits[key]
            if value is None or value == "":
                props[prop_name] = {"select": None}
            else:
                mapped = mapping.get(value, value) if mapping else value
                props[prop_name] = {"select": {"name": mapped}}
        # v1.0.0g: chunked state-backup property — durable lifeline against
        # Railway cache wipes. Accepts a list of pre-chunked rich-text
        # entries (each <2000 chars). Skips silently if not provided.
        if "state_backup_chunks" in edits:
            chunks = edits["state_backup_chunks"] or []
            if chunks:
                props["State Backup"] = {
                    "rich_text": [
                        {"type": "text", "text": {"content": str(c)[:1990]}}
                        for c in chunks
                    ],
                }
            else:
                # Explicit empty list = clear the property
                props["State Backup"] = {"rich_text": []}

        # Rich text fields
        # NB: "Lead Summary" (v0.10.0f) requires the property to exist in
        # the Notion DB. If it doesn't, Notion returns 400; callers should
        # catch and skip rather than fail the upstream operation.
        for key, prop_name in (
            ("revenue", "Revenue"),
            ("employees", "Employees"),
            ("tech_stack", "Tech Stack"),
            ("region", "Region"),
            ("deal_size", "Deal Size"),
            ("complexity", "Complexity"),
            ("fit_summary", "Fit Summary"),
            ("next_steps", "Next Steps"),
            ("positive_signals", "Positive Signals"),
            ("disqualifiers", "Disqualifiers"),
            ("lead_summary", "Lead Summary"),
            # v1.0.0ca: reason captured when sales_stage flips to
            # "Closed Lost" or status flips to "Rejected". Optional for
            # Rejected, prompted-for on Closed Lost. Helps the team
            # build a loss-reason dataset over time.
            ("close_reason", "Close Reason"),
        ):
            if key in edits:
                props[prop_name] = {"rich_text": _rich_text(edits[key] or "")}

        # v1.0.0n: forecasting fields. Numeric deal value + expected
        # close date. Both optional; both auto-created on boot if the
        # Notion DB doesn't have them yet (see ensure_forecast_properties).
        if "deal_value_monthly_gbp" in edits:
            val = edits["deal_value_monthly_gbp"]
            if val is None or val == "":
                props["Deal Value (Monthly GBP)"] = {"number": None}
            else:
                try:
                    props["Deal Value (Monthly GBP)"] = {"number": float(val)}
                except (TypeError, ValueError):
                    pass
        if "expected_close_date" in edits:
            val = edits["expected_close_date"]
            if val is None or val == "":
                props["Expected Close Date"] = {"date": None}
            else:
                # Notion accepts ISO yyyy-mm-dd; strip time component if
                # the UI sent a full datetime.
                date_str = str(val).split("T")[0].strip()
                if date_str:
                    props["Expected Close Date"] = {"date": {"start": date_str}}

        # v0.10.0p: numeric ICP score writes — enables re-scoring on lead
        # update when scoring-relevant fields change.
        if "icp_normalised" in edits:
            val = edits["icp_normalised"]
            if val is None or val == "":
                props["ICP Normalised"] = {"number": None}
            else:
                props["ICP Normalised"] = {"number": float(val)}
        if "icp_total" in edits:
            val = edits["icp_total"]
            if val is None or val == "":
                props["ICP Score"] = {"number": None}
            else:
                props["ICP Score"] = {"number": float(val)}
        # Opportunity Type from re-scoring (uses the same select mapping
        # as the qualify flow).
        if "opportunity_type_key" in edits:
            okey = edits["opportunity_type_key"]
            if okey and okey in _OPPORTUNITY_MAP:
                props["Opportunity Type"] = {"select": {"name": _OPPORTUNITY_MAP[okey]}}

        # Source of opportunity — single select on Notion "Partner Source"
        if "opportunity_source" in edits:
            val = edits["opportunity_source"]
            props["Partner Source"] = ({"select": None} if not val
                                       else {"select": {"name": val}})

        # Sourced For — multi-select. Send empty list to clear.
        if "sourced_for_partners" in edits:
            partners = edits["sourced_for_partners"] or []
            if isinstance(partners, str):
                partners = [p.strip() for p in partners.split(",") if p.strip()]
            props["Sourced For"] = {"multi_select": [{"name": p} for p in partners if p]}

        if not props:
            return {"updated": False, "reason": "no editable fields supplied"}

        # v1.0.0aq: defensive retry when the Notion DB is missing a
        # property we tried to write. Without this, a single missing
        # column (e.g. "Sourced For" on a DB that pre-dates v1.0.0z)
        # 400s the whole save and the user loses every edit in the
        # batch. We parse the error message, strip the offending
        # property, and retry once. If it still fails, surface the
        # error normally so the user sees the real problem.
        #
        # v1.0.0bp: the recovery now also returns the names of any
        # dropped properties so the API + UI can be honest about a
        # partial save instead of returning silent success. This
        # surfaced after a "still can't edit account names" report
        # where the user was hitting Save, seeing a green toast, but
        # the rename never landed because something earlier in the
        # property list had been dropped.
        page, dropped = self._patch_page_with_missing_property_recovery(page_id, props)
        out = {"updated": True, "page_id": page.get("id"), "url": page.get("url"),
                "lead": _page_to_detail(page)}
        if dropped:
            out["dropped_props"] = dropped
        return out

    def _patch_page_with_missing_property_recovery(self, page_id: str,
                                                     props: dict) -> tuple[dict, list[str]]:
        """PATCH a page's properties; if Notion 400s with "X is not a
        property that exists", drop X from the request and retry.
        Logs the dropped property so it's visible in the server log.

        v1.0.0bp: now returns (page, dropped_property_names) so callers
        can surface a partial-save warning instead of pretending the
        full write landed. Loops the recovery — if the second attempt
        also has a missing property, drop it too and retry once more.
        Bounded retries (up to len(props)) so a pathologically broken
        schema can't spin forever.

        Notion's error format is reliable here: the message body
        always starts with the property name, e.g.
            "Sourced For is not a property that exists."
        We parse the first token before " is not a property" and use
        it as the key to drop from `props`.
        """
        import re as _re
        import logging as _logging
        log = _logging.getLogger(__name__)
        dropped: list[str] = []
        current = dict(props)
        # Bound iterations so a totally-broken schema can't infinite-loop.
        for _ in range(len(props) + 1):
            try:
                page = self._request("PATCH", f"/pages/{page_id}",
                                      json_body={"properties": current})
                return page, dropped
            except NotionSyncError as e:
                msg = str(e)
                m = _re.search(
                    r'["\'`]?([A-Za-z][A-Za-z0-9 _]+?)["\'`]?\s+is not a property that exists',
                    msg)
                if not m:
                    raise
                bad = m.group(1).strip()
                if bad not in current:
                    # Parser caught something we didn't send — bail out
                    # rather than silently dropping unrelated state.
                    raise
                log.warning(
                    "Notion DB missing property %r — dropping from PATCH "
                    "and retrying. Add the column manually or wait for the "
                    "next boot self-heal to create it.", bad)
                dropped.append(bad)
                current = {k: v for k, v in current.items() if k != bad}
                if not current:
                    # Nothing left to write — return a no-op response
                    # shape the caller can handle, plus the drop trail.
                    return {"id": page_id, "url": None}, dropped
        # Defensive — should never reach here given the loop bound.
        raise NotionSyncError(
            f"PATCH /pages/{page_id} kept failing with missing-property "
            f"errors after dropping {dropped!r}")


def sync_to_notion(payload: dict) -> dict:
    """Module-level convenience for one-shot calls."""
    return NotionSync().upsert(payload)
