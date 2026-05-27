"""Quarterly targets store (v1.0.0db).

Leadership-visibility numbers - plan vs actual per quarter, for two
default metrics: opportunities (new qualified leads) + re_engagements
(accounts won back from Closed Lost / Nurture via outreach). Both
team-wide totals and per-owner splits are supported.

Storage: one JSON file at cache/quarterly_targets.json. Single file
because the row count is small (~handful of quarters, ~handful of
owners, 2-N metrics) and reads land on the Dashboard which polls
infrequently.

Public API
----------
list_quarters()                     -> list of quarter dicts, newest first
get_quarter(quarter_id)             -> quarter dict | None
upsert_quarter(payload)             -> persisted dict (id assigned if absent)
delete_quarter(quarter_id)          -> bool (False if missing)
set_cell(quarter_id, metric, kind,
         owner, value)              -> persisted dict (single-cell update)
default_metrics()                   -> list of metric dicts the UI seeds with

Quarter id convention: "YYYY-Qn" (e.g. "2026-Q2"). `year` + `quarter`
are also stored for sortability.

Shape of one quarter:
    {
      "id": "2026-Q2",
      "year": 2026, "quarter": 2,
      "metrics": {
        "opportunities": {
          "team":     {"plan": 25, "actual": 18},
          "by_owner": {"Ben Ojuolape": {"plan": 10, "actual": 7}, ...}
        },
        "re_engagements": {
          "team":     {"plan": 5, "actual": 3},
          "by_owner": {...}
        }
      },
      "created_at": "...", "updated_at": "..."
    }
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import json_file_store


_DEFAULT_PATH = Path(__file__).parent / "cache" / "quarterly_targets.json"
_LOCK = threading.Lock()

# v1.0.0dc: full Q2 2026 metric framework, per Ben's leadership doc.
# Grouped logically (Pipeline / Engagement / Content / Vendor / Sequences
# / Expansion). The UI auto-extends with any custom key not in this list
# so admins can still add ad-hoc metrics via the editor.
_DEFAULT_METRICS = [
    # --- Pipeline (per-function: Marketing / Partnerships / BD / AM) ---
    {"key": "qls_prioritised", "label": "QLs from Prioritised Logos",
     "hint":  "Qualified leads inside the ICP / target list."},
    {"key": "qls_non_prioritised", "label": "QLs from Non-Prioritised Logos",
     "hint":  "Qualified leads outside the priority list."},
    {"key": "positive_actions_prioritised",
     "label": "Positive Actions - Prioritised Logos",
     "hint":  "Meaningful engagement signals from priority logos."},
    {"key": "positive_actions_non_prioritised",
     "label": "Positive Actions - Non-Prioritised Logos",
     "hint":  "Meaningful engagement signals from non-priority logos."},
    {"key": "warm_intros_prioritised",
     "label": "Warm Introductions to Prioritised Logos",
     "hint":  "Referral-driven intros to priority accounts."},
    {"key": "warm_intros_non_prioritised",
     "label": "Warm Introductions to Non-Prioritised Logos",
     "hint":  "Referral-driven intros to non-priority accounts."},
    # --- Engagement (Marketing) ---
    {"key": "email_opens", "label": "Email Opens",
     "hint":  "Total opens across nurture + outbound."},
    {"key": "social_engagement", "label": "Social Engagement",
     "hint":  "Likes / comments / reshares across LinkedIn."},
    {"key": "connection_requests_accepted",
     "label": "Connection Requests Accepted"},
    {"key": "content_views", "label": "Content Views",
     "hint":  "Blog + case study + asset page views."},
    # --- Conversations ---
    {"key": "ae_conversations", "label": "AE Conversations"},
    {"key": "csm_conversations", "label": "CSM Conversations"},
    {"key": "outbound_stakeholder_conversations",
     "label": "Outbound Stakeholder Conversations",
     "hint":  "Conversations with target-account stakeholders."},
    {"key": "referral_conversations",
     "label": "Referral / Intro Conversations",
     "hint":  "Via network or existing clients."},
    # --- Content ---
    {"key": "case_studies", "label": "Case Studies / Customer Stories"},
    {"key": "linkedin_posts", "label": "LinkedIn Posts"},
    {"key": "blog_posts", "label": "Blog Posts"},
    {"key": "customer_newsletters", "label": "Customer Newsletters"},
    {"key": "partner_newsletters", "label": "Partner Newsletters"},
    {"key": "webinars", "label": "Webinars"},
    # --- Vendor / partner meetings ---
    {"key": "meetings_braze", "label": "Meetings with Braze"},
    {"key": "meetings_hightouch", "label": "Meetings with Hightouch"},
    {"key": "meetings_snowflake", "label": "Meetings with Snowflake"},
    {"key": "meetings_other_vendors", "label": "Meetings with Other Vendors"},
    # --- Sequences (Account Management) ---
    {"key": "sequences_expand_new",
     "label": "Sequences per Expanded/New Logo"},
    {"key": "sequences_winback",
     "label": "Sequence per Winback / Re-Engagement Logo"},
    {"key": "proactive_engagement_winback",
     "label": "Proactive Engagement per Winback / Re-Engagement Logo"},
    # --- Expansion (AM + Big Bets) ---
    {"key": "city_x_city_conversations",
     "label": "Prospect / Client Conversations at City x City"},
    {"key": "expansion_strategy_sessions",
     "label": "Expansion Strategy Sessions"},
    {"key": "multithreading_meetings",
     "label": "New Stakeholder / Multithreading Meetings"},
    {"key": "expansion_discovery_calls",
     "label": "Expansion Discovery Calls"},
    # v1.0.0dd: key stakeholder coverage rolls up from
    # /api/metrics/stakeholder-coverage. Set the plan here, the
    # actual % displays alongside on the Dashboard.
    {"key": "partner_stakeholder_coverage_pct",
     "label": "Partner Stakeholder Coverage %",
     "hint":  "Share of key partner contacts touched in the last 30 days. "
              "Actual auto-computed by the platform; set the plan here."},
    # --- Legacy v1.0.0db defaults, kept for back-compat ---
    {"key": "opportunities", "label": "Opportunities (legacy)",
     "hint":  "Pre-v1.0.0dc default - kept so older quarters still render."},
    {"key": "re_engagements", "label": "Re-engagements (legacy)",
     "hint":  "Pre-v1.0.0dc default - kept so older quarters still render."},
]


class QuarterlyTargetsStoreError(RuntimeError):
    pass


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _path() -> Path:
    override = os.environ.get("QUARTERLY_TARGETS_STORE_PATH")
    p = Path(override) if override else _DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


_QID_RE = re.compile(r"^(\d{4})-Q([1-4])$")


def _parse_id(qid: str) -> tuple[int, int]:
    """Return (year, quarter) for a quarter id. Raises if malformed."""
    m = _QID_RE.match((qid or "").strip())
    if not m:
        raise QuarterlyTargetsStoreError(
            f"Bad quarter id {qid!r} (expected YYYY-Qn, e.g. 2026-Q2)"
        )
    return int(m.group(1)), int(m.group(2))


def _to_int(value: Any) -> int:
    """Coerce a number-ish value to int >= 0. Empty / invalid -> 0."""
    if value is None or value == "":
        return 0
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return 0
    return max(0, n)


def _normalise_metrics(raw: Any) -> dict[str, dict[str, Any]]:
    """Coerce the metrics block into the canonical shape."""
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, dict):
        return out
    for metric_key, m in raw.items():
        if not metric_key:
            continue
        m = m if isinstance(m, dict) else {}
        team = m.get("team") if isinstance(m.get("team"), dict) else {}
        by_owner = m.get("by_owner") if isinstance(m.get("by_owner"), dict) else {}
        cleaned_by_owner: dict[str, dict[str, int]] = {}
        for owner, vals in by_owner.items():
            if not owner:
                continue
            v = vals if isinstance(vals, dict) else {}
            cleaned_by_owner[str(owner)] = {
                "plan":   _to_int(v.get("plan")),
                "actual": _to_int(v.get("actual")),
            }
        out[str(metric_key)] = {
            "team": {
                "plan":   _to_int(team.get("plan")),
                "actual": _to_int(team.get("actual")),
            },
            "by_owner": cleaned_by_owner,
        }
    return out


def _normalise(payload: dict[str, Any]) -> dict[str, Any]:
    qid = (payload.get("id") or "").strip()
    if not qid:
        year = payload.get("year")
        quarter = payload.get("quarter")
        if not (year and quarter):
            raise QuarterlyTargetsStoreError("id or (year + quarter) required")
        qid = f"{int(year)}-Q{int(quarter)}"
    year, quarter = _parse_id(qid)
    return {
        "id":         qid,
        "year":       year,
        "quarter":    quarter,
        "metrics":    _normalise_metrics(payload.get("metrics")),
        "created_at": payload.get("created_at") or _now(),
        "updated_at": _now(),
    }


def _load_raw() -> list[dict[str, Any]]:
    p = _path()
    if not p.exists():
        return []
    try:
        with _LOCK:
            data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict) and isinstance(data.get("quarters"), list):
        return [r for r in data["quarters"] if isinstance(r, dict)]
    return []


def _write_raw(rows: list[dict[str, Any]]) -> None:
    json_file_store.write_json(_path(), {"quarters": rows})


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------

def default_metrics() -> list[dict[str, str]]:
    """Return the canonical default-metric specs. Stable order."""
    return [dict(m) for m in _DEFAULT_METRICS]


def list_quarters() -> list[dict[str, Any]]:
    """All quarters, newest first (by year then quarter desc)."""
    rows = _load_raw()
    rows.sort(key=lambda r: (-int(r.get("year", 0)), -int(r.get("quarter", 0))))
    return rows


def get_quarter(quarter_id: str) -> dict[str, Any] | None:
    qid = (quarter_id or "").strip()
    if not qid:
        return None
    for r in _load_raw():
        if r.get("id") == qid:
            return r
    return None


def upsert_quarter(payload: dict[str, Any]) -> dict[str, Any]:
    clean = _normalise(payload)
    rows = _load_raw()
    for i, r in enumerate(rows):
        if r.get("id") == clean["id"]:
            clean["created_at"] = r.get("created_at") or clean["created_at"]
            rows[i] = clean
            _write_raw(rows)
            return clean
    rows.append(clean)
    _write_raw(rows)
    return clean


def delete_quarter(quarter_id: str) -> bool:
    qid = (quarter_id or "").strip()
    rows = _load_raw()
    new_rows = [r for r in rows if r.get("id") != qid]
    if len(new_rows) == len(rows):
        return False
    _write_raw(new_rows)
    return True


def set_cell(quarter_id: str, metric_key: str, kind: str,
             owner: str | None, value: Any) -> dict[str, Any]:
    """Update a single cell.

    kind = "plan" | "actual"
    owner = None -> team total, else per-owner cell

    Creates the quarter / metric / owner entry if it doesn't exist.
    Returns the updated quarter dict.
    """
    qid = (quarter_id or "").strip()
    if not qid:
        raise QuarterlyTargetsStoreError("quarter_id required")
    metric_key = (metric_key or "").strip()
    if not metric_key:
        raise QuarterlyTargetsStoreError("metric_key required")
    if kind not in ("plan", "actual"):
        raise QuarterlyTargetsStoreError(
            f"kind must be 'plan' or 'actual', got {kind!r}")

    value_int = _to_int(value)
    year, quarter = _parse_id(qid)

    rows = _load_raw()
    target = None
    for r in rows:
        if r.get("id") == qid:
            target = r
            break
    if target is None:
        target = {
            "id": qid, "year": year, "quarter": quarter,
            "metrics": {},
            "created_at": _now(),
        }
        rows.append(target)

    metrics = target.setdefault("metrics", {})
    metric = metrics.setdefault(metric_key, {
        "team": {"plan": 0, "actual": 0}, "by_owner": {},
    })
    if owner:
        bucket = metric.setdefault("by_owner", {})
        cell = bucket.setdefault(owner, {"plan": 0, "actual": 0})
        cell[kind] = value_int
    else:
        team = metric.setdefault("team", {"plan": 0, "actual": 0})
        team[kind] = value_int
    target["updated_at"] = _now()
    _write_raw(rows)
    return target
