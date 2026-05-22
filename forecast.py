"""
Pipeline forecast (v1.0.0n).

Pure-logic module — no Flask, no Notion. Takes a list of lead dicts +
the forecast config and returns a quarterly bookings forecast sliced
every way the UI needs (by quarter / owner / partner-source / vertical /
region).

Definitions:
- Deal value: monthly GBP. Resolution order:
    1. explicit `deal_value_monthly_gbp` field
    2. parsed from `deal_size` free-text ("£40k/month" → 40000)
    3. pricing_store.total_monthly if the per-lead pricing config exists
    4. None → lead lands in `missing_value` bucket so AE can fix it
- Expected close quarter: parsed from `expected_close_date`. If missing,
  the lead is bucketed into the CURRENT quarter with `close_date_inferred`
  set, so it's visible (and fixable) rather than silently dropped.
- Commit / Best / Pipeline groupings: standard SaaS interpretation,
  see forecast_config_store.COMMIT_STAGES / BEST_CASE_STAGES / PIPELINE_STAGES.

Disqualified, On Hold, and "New" (un-stageable) leads are excluded.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Iterable

import forecast_config_store as _config


# ---------------------------------------------------------------------------
# Deal value resolution
# ---------------------------------------------------------------------------

# "£40k/month" → 40000
# "£55,000/mo" → 55000
# "$60k MRR" → 60000  (we treat $ as GBP-equivalent here; MR's market is global
#                       and the user has said monthly GBP is the unit of record;
#                       fix-the-currency-conversion is out of scope for v1.0.0n)
# "£500k ARR" → 41667 (annual → divide by 12)
# "40k/month" → 40000 (no currency symbol fine — assume GBP)
_VALUE_PATTERN = re.compile(
    r"""
    [£\$€]?\s*                # optional currency
    (?P<num>\d[\d,]*\.?\d*)    # the number
    \s*
    (?P<unit>k|m|K|M)?         # k=thousand, m=million
    """,
    re.VERBOSE,
)


def _looks_annual(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in ("/year", "/yr", "annual", "tcv", "arr", "p.a.", " pa "))


def _looks_monthly(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in ("/month", "/mo", "monthly", "mrr", "p.m.", " pm "))


# v1.0.0s: parser-hardening constants.
# Words that signal the AE doesn't actually know the number yet.
# Anything containing one of these → return None rather than extract.
_DOUBT_MARKERS = (
    "no idea", "not sure", "maybe", "perhaps", "guess",
    "tbh", "could be", "no clue", "wild guess",
)
# Upper sanity cap on monthly value. Anything above this is almost
# certainly a typo (£40B/month?) and would skew the forecast badly.
# MR's largest realistic deal is ~£200k/month; £10M is generous headroom.
_MAX_MONTHLY_GBP = 10_000_000


def parse_deal_value_from_text(text: str | None) -> int | None:
    """Best-effort numeric extraction from a free-text deal_size field.
    Returns monthly GBP. Returns None when:
      - text is empty / a known placeholder ("TBD", "tbc", "n/a", "-")
      - text contains explicit doubt markers ("no idea", "maybe", ...)
      - the matched number is preceded by a negative sign
      - the resulting value would exceed _MAX_MONTHLY_GBP
    """
    if not text:
        return None
    s = str(text).strip()
    if not s or s.lower() in {"tbd", "tbc", "n/a", "—", "-", "unknown"}:
        return None
    # v1.0.0s: bail out when the AE wrote a number but flagged uncertainty
    # alongside it ("no idea, maybe £10k"). Better to surface in the
    # missing-value bucket than silently land a fake commit.
    s_lower = s.lower()
    if any(marker in s_lower for marker in _DOUBT_MARKERS):
        return None
    m = _VALUE_PATTERN.search(s)
    if not m:
        return None
    # Reject negatives. The regex doesn't consume "-" so "−40k" → 40000
    # without this guard; we check the char immediately before the match.
    if m.start() > 0 and s[m.start() - 1] in ("-", "−"):
        return None
    try:
        num = float(m.group("num").replace(",", ""))
    except ValueError:
        return None
    unit = (m.group("unit") or "").lower()
    if unit == "k":
        num *= 1_000
    elif unit == "m":
        num *= 1_000_000
    if num <= 0:
        return None
    # Annual → monthly conversion. If text doesn't say monthly OR annual
    # explicitly, assume monthly (matches MR's `deal_size_label` convention).
    if _looks_annual(s) and not _looks_monthly(s):
        num = num / 12
    if num > _MAX_MONTHLY_GBP:
        return None
    return int(round(num))


def resolve_deal_value(lead: dict[str, Any]) -> tuple[int | None, str]:
    """Return (monthly_gbp, source) where source is one of:
        'explicit'  — the new structured field was set
        'parsed'    — extracted from deal_size text
        'pricing'   — from pricing_store
        'unknown'   — none of the above; lead needs deal value entered
    """
    # 1) Explicit numeric field
    explicit = lead.get("deal_value_monthly_gbp")
    if explicit not in (None, "", 0, "0"):
        try:
            val = int(round(float(explicit)))
            if val > 0:
                return val, "explicit"
        except (TypeError, ValueError):
            pass
    # 2) Parse the free-text deal_size
    parsed = parse_deal_value_from_text(lead.get("deal_size")
                                          or lead.get("deal_size_label"))
    if parsed:
        return parsed, "parsed"
    # 3) pricing_store fallback (best-effort; the store is optional)
    lead_id = lead.get("id") or lead.get("page_id")
    if lead_id:
        try:
            import pricing_store
            cfg = pricing_store.load(lead_id)
            if cfg:
                # pricing_store config shape: {total_monthly: int, ...}.
                # Different versions stored it under different keys —
                # tolerate both `total_monthly` and `monthly_total`.
                val = cfg.get("total_monthly") or cfg.get("monthly_total") \
                      or cfg.get("monthly_gbp")
                if val:
                    return int(round(float(val))), "pricing"
        except Exception:
            pass
    return None, "unknown"


# ---------------------------------------------------------------------------
# Quarter bucketing
# ---------------------------------------------------------------------------

def _today() -> date:
    return datetime.now(timezone.utc).date()


def _quarter_of(d: date) -> str:
    """date → 'YYYY-Qn' (Q1 = Jan-Mar)."""
    q = (d.month - 1) // 3 + 1
    return f"{d.year}-Q{q}"


def current_quarter() -> str:
    return _quarter_of(_today())


def next_n_quarters(n: int = 4) -> list[str]:
    """Return ['this Q', '+1', '+2', ...] up to n entries. Used to seed
    the forecast view so empty quarters still render."""
    today = _today()
    out = []
    y, q = today.year, (today.month - 1) // 3 + 1
    for _ in range(n):
        out.append(f"{y}-Q{q}")
        q += 1
        if q > 4:
            q = 1
            y += 1
    return out


def parse_close_date(value: Any) -> date | None:
    """Tolerate ISO dates ('2026-09-30'), ISO datetimes ('2026-09-30T...'),
    and bare 'YYYY-MM' (we treat as end-of-month)."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    # Strip time component
    s_date = s.split("T")[0]
    # YYYY-MM-DD
    try:
        return date.fromisoformat(s_date)
    except ValueError:
        pass
    # YYYY-MM → end-of-quarter-month as a sensible default
    m = re.match(r"^(\d{4})-(\d{1,2})$", s_date)
    if m:
        try:
            y, mo = int(m.group(1)), int(m.group(2))
            # Use the 28th to avoid month-length edge cases
            return date(y, mo, 28)
        except ValueError:
            return None
    return None


def resolve_close_quarter(lead: dict[str, Any]) -> tuple[str, bool]:
    """Return (quarter_str, was_inferred). If lead has no close date, we
    bucket into the current quarter with was_inferred=True so the AE
    can see it needs filling in."""
    d = parse_close_date(lead.get("expected_close_date"))
    if d:
        return _quarter_of(d), False
    return current_quarter(), True


# ---------------------------------------------------------------------------
# Forecast builder
# ---------------------------------------------------------------------------

# Statuses + stages that disqualify a lead from the forecast.
_EXCLUDE_STATUSES = {"Disqualified", "On Hold", "Closed Lost"}


def _stage_probability(stage: str | None, probs: dict[str, float]) -> float:
    if not stage:
        return 0.0
    return probs.get(stage, 0.0)


def _empty_bucket() -> dict[str, Any]:
    return {
        "commit_gbp":      0,    # weighted, monthly
        "best_case_gbp":   0,    # weighted, monthly
        "pipeline_gbp":    0,    # weighted, monthly
        "raw_pipeline_gbp": 0,   # unweighted sum of in-stage deals
        "deal_count":      0,
        "deal_ids":        [],
    }


def _annualise(monthly_gbp: int) -> int:
    return monthly_gbp * 12


def _add_lead_to_bucket(bucket: dict[str, Any], lead: dict[str, Any],
                         value: int, prob: float) -> None:
    stage = lead.get("sales_stage") or ""
    weighted = int(round(value * prob))
    bucket["pipeline_gbp"] += weighted
    bucket["raw_pipeline_gbp"] += value
    if stage in _config.BEST_CASE_STAGES:
        bucket["best_case_gbp"] += weighted
    if stage in _config.COMMIT_STAGES:
        bucket["commit_gbp"] += weighted
    bucket["deal_count"] += 1
    bucket["deal_ids"].append(lead.get("id") or lead.get("page_id"))


def _eligible(lead: dict[str, Any]) -> bool:
    """A lead is in the forecast iff:
    - status is not Disqualified / On Hold / Closed Lost
    - sales_stage is a known pipeline stage (Discovery+)
    """
    if (lead.get("status") or "") in _EXCLUDE_STATUSES:
        return False
    stage = lead.get("sales_stage") or ""
    return stage in _config.PIPELINE_STAGES


def build_forecast(leads: Iterable[dict[str, Any]], *,
                    config: dict[str, Any] | None = None,
                    horizon_quarters: int = 4) -> dict[str, Any]:
    """Main entry point. Returns the full forecast payload:

    {
      "generated_at": iso,
      "horizon": ["2026-Q3", "2026-Q4", ...],
      "totals": { commit_gbp, best_case_gbp, pipeline_gbp, deal_count, ... },
      "by_quarter": { "2026-Q3": {bucket}, ... },
      "by_owner":    { "Ben Ojuolape": {bucket}, ... },
      "by_partner":  { "Braze": {bucket}, "Hightouch": {bucket}, "Direct": {bucket} },
      "by_vertical": { ... },
      "by_region":   { ... },
      "missing_value": [{lead_id, name}, ...],
      "config_used": { stage_probabilities, quarterly_target_gbp, ... },
      "coverage_ratio_this_quarter": float,
    }
    """
    cfg = config or _config.load()
    probs = cfg["stage_probabilities"]
    target = cfg.get("quarterly_target_gbp") or _config.DEFAULT_QUARTERLY_TARGET_GBP

    horizon = next_n_quarters(horizon_quarters)
    horizon_set = set(horizon)

    by_quarter:  dict[str, dict[str, Any]] = {q: _empty_bucket() for q in horizon}
    by_owner:    dict[str, dict[str, Any]] = {}
    by_partner:  dict[str, dict[str, Any]] = {}
    by_vertical: dict[str, dict[str, Any]] = {}
    by_region:   dict[str, dict[str, Any]] = {}
    missing_value: list[dict[str, Any]] = []

    totals = _empty_bucket()

    for lead in leads:
        if not _eligible(lead):
            continue
        value, source = resolve_deal_value(lead)
        if value is None:
            missing_value.append({
                "id":           lead.get("id") or lead.get("page_id"),
                "company":      lead.get("company"),
                "sales_stage":  lead.get("sales_stage"),
                "deal_size":    lead.get("deal_size"),
            })
            continue
        prob = _stage_probability(lead.get("sales_stage"), probs)
        if prob <= 0:
            continue
        quarter, inferred = resolve_close_quarter(lead)
        # If the close date falls OUTSIDE our horizon, lump into the
        # last horizon bucket (so distant Q+5 deals still surface;
        # the UI can decide whether to render them).
        bucket_q = quarter if quarter in horizon_set else horizon[-1]
        _add_lead_to_bucket(by_quarter[bucket_q], lead, value, prob)
        _add_lead_to_bucket(totals, lead, value, prob)
        # By owner
        owner = (lead.get("owner") or "Unassigned").strip() or "Unassigned"
        _add_lead_to_bucket(by_owner.setdefault(owner, _empty_bucket()),
                            lead, value, prob)
        # By partner source — leverage sourced_for_partners (the AE-set
        # multi-tag list). A lead can be sourced for multiple partners
        # (Braze + Hightouch co-sell), so we count it under each. The
        # "Direct" bucket catches leads with no sourced_for entries.
        sourced_for = lead.get("sourced_for_partners") or []
        if sourced_for:
            for p in sourced_for:
                _add_lead_to_bucket(by_partner.setdefault(p, _empty_bucket()),
                                    lead, value, prob)
        else:
            _add_lead_to_bucket(by_partner.setdefault("Direct", _empty_bucket()),
                                lead, value, prob)
        # By vertical
        vertical = (lead.get("vertical") or "Unknown").strip() or "Unknown"
        _add_lead_to_bucket(by_vertical.setdefault(vertical, _empty_bucket()),
                            lead, value, prob)
        # By region
        region = (lead.get("region") or "Unknown").strip() or "Unknown"
        _add_lead_to_bucket(by_region.setdefault(region, _empty_bucket()),
                            lead, value, prob)

    # Coverage ratio for THIS quarter: total pipeline (unweighted, in-stage
    # deals) vs the target. 3x is the SaaS rule-of-thumb for healthy
    # coverage. Annualised because the target is annual-ish? Actually MR's
    # target field is per quarter, so we compare monthly × 3 vs target.
    this_q = horizon[0]
    this_q_monthly_pipeline = by_quarter[this_q]["raw_pipeline_gbp"]
    # Target is quarterly bookings (so we compare to 3 months of monthly
    # deal value). Coverage = (3 months × monthly_pipeline) / quarterly_target.
    coverage = 0.0
    if target > 0:
        coverage = round((this_q_monthly_pipeline * 3) / target, 2)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "horizon": horizon,
        "totals":      totals,
        "by_quarter":  by_quarter,
        "by_owner":    by_owner,
        "by_partner":  by_partner,
        "by_vertical": by_vertical,
        "by_region":   by_region,
        "missing_value": missing_value,
        "config_used": cfg,
        "coverage_ratio_this_quarter": coverage,
        # Annualised totals are useful for executive summary cards.
        "totals_annualised": {
            "commit_gbp":     _annualise(totals["commit_gbp"]),
            "best_case_gbp":  _annualise(totals["best_case_gbp"]),
            "pipeline_gbp":   _annualise(totals["pipeline_gbp"]),
        },
    }
