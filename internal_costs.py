"""
Internal cost rates per role (× region × seniority for Staff Aug).

**STATUS: PLACEHOLDER until Finance shares the live `[Database] Rate Card -
Internal` tab.** Cost values here are an industry-standard agency stub —
45% of the sales rate per role/region/currency. Real numbers will replace
this once the internal rate card lands. The shape of this module is
designed to drop the real data in with a one-shot copy.

Public surface:
    internal_cost_lookup(role, currency, *, region=None, seniority=None)
        -> dict {"hourly": float, "daily": float} | None

    is_placeholder_data() -> bool
        Returns True until the real internal rate card is wired in.
        The UI surfaces a banner while this is True.

    margin_thresholds() -> dict
        Green / yellow / red boundaries for the UI indicator.
"""
from __future__ import annotations

import rate_cards

# Industry standard agency cost-to-price ratio. Real number comes from
# Finance's Internal Rate Card tab when shared.
PLACEHOLDER_COST_RATIO = 0.45

# Gross margin thresholds (decimal). Adjust once Finance confirms targets.
MARGIN_TARGETS = {
    "green": 0.40,   # ≥ 40% → healthy
    "yellow": 0.30,  # 30–40% → marginal
    "red": 0.00,     # < 30% → below target
}

# Set to True once real internal rates have been imported.
# Currently False because every value is derived from the placeholder ratio.
_REAL_DATA_LOADED = False


def is_placeholder_data() -> bool:
    """Until Finance shares the real Internal Rate Card, this stays True."""
    return not _REAL_DATA_LOADED


def margin_thresholds() -> dict[str, float]:
    return dict(MARGIN_TARGETS)


def margin_band(margin_pct: float) -> str:
    """Return 'green' | 'yellow' | 'red' for a given gross margin."""
    if margin_pct >= MARGIN_TARGETS["green"]:
        return "green"
    if margin_pct >= MARGIN_TARGETS["yellow"]:
        return "yellow"
    return "red"


def internal_cost_lookup(
    role: str,
    currency: str = "USD",
    *,
    region: str | None = None,
    seniority: str | None = None,
) -> dict[str, float] | None:
    """Return internal cost {hourly, daily} for the given role + dimensions.

    Currently derived from the sales rate via PLACEHOLDER_COST_RATIO.
    When the real Internal Rate Card is added, swap this body for a
    direct table lookup; the signature stays the same so callers don't
    change.
    """
    # First try Staff Aug rate (uses region + seniority).
    if region and seniority:
        sales = rate_cards.rate_lookup(
            "Staff Augmentation", role, currency,
            region=region, seniority=seniority,
        )
        if sales:
            return _scale(sales, PLACEHOLDER_COST_RATIO)
    # Otherwise use MR Default blended rate.
    sales = rate_cards.rate_lookup("MR Default", role, currency)
    if sales:
        return _scale(sales, PLACEHOLDER_COST_RATIO)
    return None


def _scale(sales: dict[str, float], ratio: float) -> dict[str, float]:
    return {
        "hourly": round(sales["hourly"] * ratio, 2),
        "daily": round(sales["daily"] * ratio, 2),
    }
