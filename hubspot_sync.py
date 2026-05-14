"""HubSpot write-back module — scaffolding for v0.3.

**Status: feature-flagged OFF by default.** Per the original product brief,
HubSpot integration ships only after CEO approval. This module is wired in
end-to-end so that flipping a single env var activates it.

Activation requirements (all three):
    1. HUBSPOT_API_KEY                     — Private app token
    2. HUBSPOT_SYNC_ENABLED=1              — Explicit opt-in
    3. (recommended) Custom company props in HubSpot:
       - mr_icp_score (number, 0-10)
       - mr_icp_status (single-line text)
       - mr_opportunity_type (single-line text)
       - mr_fit_summary (multi-line text)
       - mr_last_qualified (date)

If custom properties are absent, the sync degrades to writing only standard
HubSpot company properties (name, domain, industry, lifecyclestage).

Public surface mirrors notion_sync.NotionSync:
    HubSpotSync().upsert(payload)  -> {action, company_id, url}
    HubSpotSync.is_enabled()       -> bool
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

log = logging.getLogger("mr.hubspot")
HUBSPOT_BASE = "https://api.hubapi.com"
DEFAULT_TIMEOUT = 15


class HubSpotSyncError(RuntimeError):
    """Raised when HubSpot returns a non-2xx response we can't recover from."""


class HubSpotSyncDisabled(RuntimeError):
    """Raised when HubSpot sync is requested but disabled via env config."""


def is_enabled() -> bool:
    """Both flags required. Defensive AND."""
    return bool(os.environ.get("HUBSPOT_API_KEY", "").strip()) and \
           os.environ.get("HUBSPOT_SYNC_ENABLED", "").strip() == "1"


def status() -> dict:
    """Surface in /api/health so the team can confirm activation state."""
    return {
        "enabled": is_enabled(),
        "api_key_present": bool(os.environ.get("HUBSPOT_API_KEY", "").strip()),
        "sync_flag": os.environ.get("HUBSPOT_SYNC_ENABLED", "") == "1",
    }


# ---- Payload mapping -----------------------------------------------------

def _clean_domain(url: str) -> str:
    s = (url or "").strip().lower()
    for prefix in ("https://", "http://"):
        if s.startswith(prefix):
            s = s[len(prefix):]
    if s.startswith("www."):
        s = s[4:]
    return s.split("/")[0].split("?")[0]


def _status_to_lifecycle(qual_status: str) -> str:
    return {
        "qualify_in": "marketingqualifiedlead",
        "borderline": "lead",
        "qualify_out": "other",
    }.get(qual_status, "lead")


def _qualify_payload_to_props(payload: dict) -> dict[str, Any]:
    """Build HubSpot company properties from our qualify() payload."""
    company = payload.get("company") or {}
    score = payload.get("score") or {}
    opp = payload.get("opportunity") or {}
    discovered = payload.get("discovered") or {}

    props: dict[str, Any] = {
        "name": company.get("name") or "",
        "domain": _clean_domain(company.get("url") or ""),
        "industry": discovered.get("vertical") or "",
        "lifecyclestage": _status_to_lifecycle(score.get("status") or ""),
        # Numeric employees + revenue (HubSpot accepts numeric strings).
        "numberofemployees": str(discovered.get("employees") or "") or "",
        "annualrevenue": str(discovered.get("revenue_numeric") or "") or "",
        # Custom MR properties — these are skipped if HubSpot rejects them.
        "mr_icp_score": str(score.get("normalized_score") or "") or "",
        "mr_icp_status": score.get("status_display") or "",
        "mr_opportunity_type": opp.get("label") or "",
        "mr_fit_summary": (payload.get("fit_summary") or "")[:1800],
    }
    # Drop empties so we don't overwrite existing HubSpot fields with "".
    return {k: v for k, v in props.items() if v not in ("", None)}


# ---- The sync class -------------------------------------------------------

class HubSpotSync:
    """Minimal v3-API wrapper. Disabled by default; activate via env flags."""

    def __init__(self, api_key: str | None = None, *, enforce_enabled: bool = True):
        self.api_key = (api_key or os.environ.get("HUBSPOT_API_KEY") or "").strip()
        if enforce_enabled and not is_enabled():
            raise HubSpotSyncDisabled(
                "HubSpot sync is disabled. Set HUBSPOT_SYNC_ENABLED=1 and HUBSPOT_API_KEY to activate."
            )
        if not self.api_key:
            raise HubSpotSyncDisabled("HUBSPOT_API_KEY is required to construct HubSpotSync.")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "accept": "application/json",
        }

    def _request(self, method: str, path: str, *, json_body: dict | None = None) -> dict:
        url = f"{HUBSPOT_BASE}{path}"
        resp = requests.request(method, url, headers=self._headers(), json=json_body, timeout=DEFAULT_TIMEOUT)
        if not resp.ok:
            raise HubSpotSyncError(f"HubSpot {method} {path} {resp.status_code}: {resp.text[:400]}")
        return resp.json() if resp.content else {}

    def find_company_by_domain(self, domain: str) -> dict | None:
        if not domain:
            return None
        body = {
            "filterGroups": [{
                "filters": [{"propertyName": "domain", "operator": "EQ", "value": domain}]
            }],
            "properties": ["name", "domain", "industry", "lifecyclestage",
                           "mr_icp_score", "mr_icp_status"],
            "limit": 1,
        }
        data = self._request("POST", "/crm/v3/objects/companies/search", json_body=body)
        results = data.get("results") or []
        return results[0] if results else None

    def upsert(self, payload: dict) -> dict:
        """Create or update a company. Returns {action, company_id, url}."""
        props = _qualify_payload_to_props(payload)
        domain = props.get("domain")
        existing = self.find_company_by_domain(domain) if domain else None

        # Try once with custom MR properties; if HubSpot 400s for an unknown
        # property, retry with the custom set stripped so we still write the
        # standard fields.
        attempts = [props, {k: v for k, v in props.items() if not k.startswith("mr_")}]
        last_err: HubSpotSyncError | None = None
        for attempt_props in attempts:
            try:
                if existing:
                    resp = self._request(
                        "PATCH",
                        f"/crm/v3/objects/companies/{existing['id']}",
                        json_body={"properties": attempt_props},
                    )
                    return {
                        "action": "updated",
                        "company_id": resp.get("id") or existing.get("id"),
                        "url": f"https://app.hubspot.com/contacts/_/company/{resp.get('id') or existing.get('id')}",
                        "props_written": sorted(attempt_props.keys()),
                    }
                resp = self._request(
                    "POST",
                    "/crm/v3/objects/companies",
                    json_body={"properties": attempt_props},
                )
                return {
                    "action": "created",
                    "company_id": resp.get("id"),
                    "url": f"https://app.hubspot.com/contacts/_/company/{resp.get('id')}",
                    "props_written": sorted(attempt_props.keys()),
                }
            except HubSpotSyncError as e:
                last_err = e
                msg = str(e)
                # Only retry on schema mismatches.
                if "property" not in msg.lower() and "mr_" not in msg.lower():
                    raise
                log.warning("HubSpot rejected custom MR properties; retrying with standard set only.")
                continue
        # Should be unreachable.
        raise last_err or HubSpotSyncError("HubSpot upsert failed for unknown reason.")
