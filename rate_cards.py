"""
Rate cards — source of truth for what MR charges.

Data extracted from the v2.0 Pricing Calculator
(Google Sheet: 1ghZrB-U7GoJ6IGR9K9yj3ptUbwM7IU4J_hRpFJ-00K4,
tab `[Database] Rate Card - Sales`, fetched 2026-05-16).

Three rate card types:
  - "MR Default"           — single blended rate, all roles, region-agnostic
  - "Staff Augmentation"   — per (role, seniority, region), with rates in
                             each currency
  - Client-specific        — bespoke rates negotiated for a specific client
                             (Yum! Small Markets, Yum Thailand etc.)

The lookup contract:
    rate_lookup(rate_card, role, currency, *, region=None, seniority=None)
        -> dict {"hourly": float, "daily": float} | None

If the lookup misses (role not found on the chosen card), the caller can
fall back to MR Default or raise — `compute_quote` falls back so the AE
isn't blocked when a niche role isn't on a client's card.
"""
from __future__ import annotations

from typing import Any

CURRENCIES = ("USD", "GBP", "EUR")

# Working assumptions used to convert between days, hours, and FTE.
HOURS_PER_DAY = 8
WORKING_DAYS_PER_MONTH = 20  # ~ 4 weeks × 5
HOURS_PER_FTE_MONTH = HOURS_PER_DAY * WORKING_DAYS_PER_MONTH  # 160
UTILIZATION = 0.85

# Exchange rates — used only when a rate card has values in one currency
# and the AE picks another. The default cards already carry all 3 currencies,
# so this is rarely hit.
FX = {
    ("GBP", "USD"): 1.33,
    ("USD", "GBP"): 1 / 1.33,
    ("EUR", "GBP"): 1 / 1.17,
    ("GBP", "EUR"): 1.17,
    ("USD", "EUR"): (1 / 1.33) * 1.17,
    ("EUR", "USD"): (1 / 1.17) * 1.33,
}


def _trio(gbp_h: float, gbp_d: float, usd_h: float, usd_d: float,
          eur_h: float, eur_d: float) -> dict[str, dict[str, float]]:
    """Helper to build the three-currency block."""
    return {
        "GBP": {"hourly": gbp_h, "daily": gbp_d},
        "USD": {"hourly": usd_h, "daily": usd_d},
        "EUR": {"hourly": eur_h, "daily": eur_d},
    }


# ---------------------------------------------------------------------------
# Rate cards
# ---------------------------------------------------------------------------

# MR Default — region-agnostic blended rate, applies to all roles.
RATE_CARD_MR_DEFAULT: dict[str, Any] = {
    "name": "MR Default",
    "type": "blended",
    "rates": _trio(150, 1200, 200, 1600, 175, 1400),
}

# Client-specific rate cards.
CLIENT_RATE_CARDS: dict[str, dict[str, Any]] = {
    "Yum! Small Markets": {
        "name": "Yum! Small Markets",
        "type": "client_partial",
        "applicable_roles": ["Onboarding Consultant"],
        "rates": _trio(32, 253, 42, 337, 37, 295),
    },
    "Yum Thailand!": {
        "name": "Yum Thailand!",
        "type": "client_blended",
        "applicable_roles": "all",
        "rates": _trio(79, 632, 105, 843, 92, 737),
    },
}

# Staff Augmentation — per (role, seniority, region).
# Stored as a list of records for grep-ability + iteration.
# Each record: role, seniority, region, GBP_h, GBP_d, USD_h, USD_d, EUR_h, EUR_d
STAFF_AUG_RATES: list[dict[str, Any]] = [
    {"role": "Braze Technical Architect", "seniority": "Senior", "region": "UK",
     **_trio(119, 950, 162, 1295, 138, 1100)},
    {"role": "Business Analyst", "seniority": "Senior", "region": "EU",
     **_trio(100, 800, 116, 925, 137, 1095)},
    {"role": "Business Analyst", "seniority": "Senior", "region": "LATAM",
     **_trio(89, 715, 104, 830, 122, 975)},
    # CRM Consultant
    {"role": "CRM Consultant", "seniority": "Lead", "region": "EU",
     **_trio(117, 935, 135, 1080, 159, 1275)},
    {"role": "CRM Consultant", "seniority": "Practitioner", "region": "EU",
     **_trio(92, 735, 106, 850, 126, 1005)},
    {"role": "CRM Consultant", "seniority": "Senior", "region": "EU",
     **_trio(109, 870, 126, 1005, 149, 1190)},
    {"role": "CRM Consultant", "seniority": "Practitioner", "region": "India",
     **_trio(55, 440, 64, 510, 75, 600)},
    {"role": "CRM Consultant", "seniority": "Senior", "region": "India",
     **_trio(70, 560, 81, 650, 96, 765)},
    {"role": "CRM Consultant", "seniority": "Lead", "region": "LATAM",
     **_trio(107, 855, 124, 990, 146, 1170)},
    {"role": "CRM Consultant", "seniority": "Senior", "region": "LATAM",
     **_trio(89, 715, 104, 830, 122, 975)},
    {"role": "CRM Consultant", "seniority": "Lead", "region": "UK",
     **_trio(119, 950, 138, 1100, 162, 1295)},
    {"role": "CRM Consultant", "seniority": "Senior", "region": "UK",
     **_trio(113, 900, 130, 1040, 154, 1230)},
    # CRM Consultant (AI)
    {"role": "CRM Consultant (AI)", "seniority": "Senior", "region": "EU",
     **_trio(125, 1000, 144, 1155, 171, 1365)},
    {"role": "CRM Consultant (AI)", "seniority": "Senior", "region": "India",
     **_trio(70, 560, 81, 650, 96, 765)},
    {"role": "CRM Consultant (AI)", "seniority": "Senior", "region": "LATAM",
     **_trio(98, 785, 114, 910, 134, 1070)},
    {"role": "CRM Consultant (AI)", "seniority": "Senior", "region": "UK",
     **_trio(133, 1060, 153, 1225, 181, 1445)},
    # Developers
    {"role": "CRM Developer (Braze)", "seniority": "Senior", "region": "EU",
     **_trio(100, 800, 116, 925, 137, 1095)},
    {"role": "CRM Developer (Braze)", "seniority": "Senior", "region": "UK",
     **_trio(117, 935, 135, 1080, 159, 1275)},
    {"role": "CRM Developer (SFMC)", "seniority": "Senior", "region": "EU",
     **_trio(100, 800, 116, 925, 137, 1095)},
    {"role": "CRM Operations Manager", "seniority": "Senior", "region": "UK",
     **_trio(133, 1060, 153, 1225, 181, 1445)},
    # CRM Strategist
    {"role": "CRM Strategist", "seniority": "Practitioner", "region": "EU",
     **_trio(117, 935, 135, 1080, 159, 1275)},
    {"role": "CRM Strategist", "seniority": "Practitioner", "region": "India",
     **_trio(70, 560, 81, 650, 96, 765)},
    {"role": "CRM Strategist", "seniority": "Practitioner", "region": "LATAM",
     **_trio(107, 855, 124, 990, 146, 1170)},
    {"role": "CRM Strategist", "seniority": "Practitioner", "region": "UK",
     **_trio(119, 950, 138, 1100, 162, 1295)},
    # CRM leadership
    {"role": "CRM Team Lead", "seniority": "Practitioner", "region": "EU",
     **_trio(150, 1200, 174, 1390, 205, 1640)},
    {"role": "CRM Team Lead", "seniority": "Practitioner", "region": "UK",
     **_trio(171, 1370, 198, 1585, 234, 1870)},
    {"role": "CRM Director", "seniority": "Senior", "region": "UK",
     **_trio(234, 1870, 270, 2160, 319, 2550)},
    # Data
    {"role": "Data Analyst", "seniority": "Senior", "region": "EU",
     **_trio(109, 870, 126, 1005, 149, 1190)},
    {"role": "Data Analyst", "seniority": "Senior", "region": "India",
     **_trio(63, 500, 73, 580, 86, 685)},
    {"role": "Data Engineer (CDP)", "seniority": "Senior", "region": "EU",
     **_trio(142, 1135, 164, 1315, 194, 1550)},
    {"role": "Data Engineer (CDP)", "seniority": "Senior", "region": "India",
     **_trio(78, 625, 91, 725, 107, 855)},
    {"role": "Data Engineer (CDP)", "seniority": "Senior", "region": "LATAM",
     **_trio(107, 855, 124, 990, 146, 1170)},
    {"role": "Data Engineer (CDP)", "seniority": "Senior", "region": "UK",
     **_trio(148, 1185, 171, 1370, 202, 1615)},
    {"role": "Data Engineer (Kafka)", "seniority": "Senior", "region": "EU",
     **_trio(142, 1135, 164, 1315, 194, 1550)},
    {"role": "Data Engineer (Snowflake)", "seniority": "Senior", "region": "EU",
     **_trio(142, 1135, 164, 1315, 194, 1550)},
    {"role": "Data Engineer (Snowflake)", "seniority": "Senior", "region": "India",
     **_trio(78, 625, 91, 725, 107, 855)},
    {"role": "Data Engineer (Snowflake)", "seniority": "Senior", "region": "LATAM",
     **_trio(107, 855, 124, 990, 146, 1170)},
    {"role": "Data Engineer (Snowflake)", "seniority": "Senior", "region": "UK",
     **_trio(148, 1185, 171, 1370, 202, 1615)},
    # QA + Platform + PM + Eng
    {"role": "Manual QA Engineer", "seniority": "Senior", "region": "EU",
     **_trio(92, 735, 106, 850, 126, 1005)},
    {"role": "Platform Engineer", "seniority": "Senior", "region": "EU",
     **_trio(134, 1070, 155, 1240, 183, 1460)},
    {"role": "Project Manager", "seniority": "Senior", "region": "EU",
     **_trio(109, 870, 126, 1005, 149, 1190)},
    {"role": "Project Manager", "seniority": "Senior", "region": "India",
     **_trio(55, 440, 64, 510, 75, 600)},
    {"role": "Project Manager", "seniority": "Senior", "region": "LATAM",
     **_trio(98, 785, 114, 910, 134, 1070)},
    {"role": "Scrum Master", "seniority": "Senior", "region": "EU",
     **_trio(109, 870, 126, 1005, 149, 1190)},
    {"role": "Software Engineer", "seniority": "Lead", "region": "EU",
     **_trio(142, 1135, 164, 1315, 194, 1550)},
    {"role": "Software Engineer", "seniority": "Senior", "region": "EU",
     **_trio(125, 1000, 144, 1155, 171, 1365)},
    {"role": "Technical Architect", "seniority": "Senior", "region": "EU",
     **_trio(150, 1200, 174, 1390, 205, 1640)},
    {"role": "Technical Product Owner", "seniority": "Senior", "region": "EU",
     **_trio(142, 1135, 164, 1315, 194, 1550)},
]


def all_cards() -> list[str]:
    """Names of every rate card available for selection in the UI."""
    return ["MR Default", "Staff Augmentation"] + list(CLIENT_RATE_CARDS.keys())


def list_regions() -> list[str]:
    return sorted({r["region"] for r in STAFF_AUG_RATES})


def list_seniorities() -> list[str]:
    return sorted({r["seniority"] for r in STAFF_AUG_RATES})


def list_roles_for_card(rate_card: str) -> list[str]:
    if rate_card == "Staff Augmentation":
        return sorted({r["role"] for r in STAFF_AUG_RATES})
    if rate_card in CLIENT_RATE_CARDS:
        ar = CLIENT_RATE_CARDS[rate_card].get("applicable_roles", "all")
        if isinstance(ar, list):
            return list(ar)
    # MR Default + "all" client cards: any role string is valid; return
    # the union of Staff Aug roles as a sensible suggestion list.
    return sorted({r["role"] for r in STAFF_AUG_RATES})


def rate_lookup(
    rate_card: str,
    role: str,
    currency: str = "USD",
    *,
    region: str | None = None,
    seniority: str | None = None,
) -> dict[str, float] | None:
    """Resolve {hourly, daily} for the given inputs, or None if unknown.

    Falls through to MR Default if a client-specific card doesn't list the
    role — keeps quotes flowing when a niche role pops up on a custom card.
    """
    currency = currency.upper()
    if currency not in CURRENCIES:
        return None

    # Blended MR Default
    if rate_card == "MR Default":
        return dict(RATE_CARD_MR_DEFAULT["rates"][currency])

    # Client-specific cards
    if rate_card in CLIENT_RATE_CARDS:
        card = CLIENT_RATE_CARDS[rate_card]
        applicable = card.get("applicable_roles", "all")
        # If role is on this client card or card is fully blended, use it.
        if applicable == "all" or (isinstance(applicable, list) and role in applicable):
            return dict(card["rates"][currency])
        # Otherwise fall through to MR Default for this role.
        return dict(RATE_CARD_MR_DEFAULT["rates"][currency])

    # Staff Augmentation — needs role + seniority + region
    if rate_card == "Staff Augmentation":
        if not (region and seniority):
            return None
        for r in STAFF_AUG_RATES:
            if r["role"] == role and r["region"] == region and r["seniority"] == seniority:
                return {"hourly": r[currency]["hourly"], "daily": r[currency]["daily"]}
        return None

    return None


def blended_rate(rate_card: str, currency: str = "USD") -> float | None:
    """Headline hourly rate for the rate card (for UI display)."""
    if rate_card == "MR Default":
        return RATE_CARD_MR_DEFAULT["rates"][currency]["hourly"]
    if rate_card in CLIENT_RATE_CARDS:
        return CLIENT_RATE_CARDS[rate_card]["rates"][currency]["hourly"]
    return None
