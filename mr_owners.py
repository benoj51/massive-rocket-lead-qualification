"""
Massive Rocket owners (v1.0.0o).

Single source of truth for the people at MR who can be assigned as
the `owner` field on a lead or `mr_owner` on a partner contact.
Every UI surface that needs the list of MR people (lead drawer, qualify
form, partner contact form, pipeline filter) reads from here via
`GET /api/owners`, so adding/removing a name is a one-place change.

Adding a person: append a dict to `OWNERS` below. Removing: delete or
mark `active: False` (preferred — keeps historical lead.owner values
resolvable if you want to surface "ex-MR" tags later).

Roles + regions are surfaced in the UI dropdowns (e.g. "Daniel Ergueta
— Account Manager · AMER") so Ben can pick the right person without
remembering the org chart.
"""
from __future__ import annotations

from typing import Any


# Ordered for the dropdown. Senior leadership + Growth lead first, then
# AMs, then AEs-in-transition, then marketing + partner managers.
# Sort UI applies alpha-by-name as a secondary, but the AE picks from
# the order presented here.
OWNERS: list[dict[str, Any]] = [
    {
        "name":   "Thierry Sequeira",
        "role":   "CEO UK",
        "region": "Global",
        "email":  "thierry@massiverocket.com",
        "active": True,
    },
    {
        "name":   "Daniel Craig",
        "role":   "Director of Growth",
        "region": "Global",
        "email":  "daniel.craig@massiverocket.com",
        "active": True,
    },
    {
        "name":   "Ben Ojuolape",
        "role":   "Growth Lead (Partnerships + GTM)",
        "region": "UK → US",
        "email":  "ben@massiverocket.com",
        "active": True,
    },
    {
        "name":   "Daniel Ergueta",
        "role":   "Account Manager",
        "region": "AMER",
        "email":  "daniel.ergueta@massiverocket.com",
        "active": True,
    },
    {
        "name":   "Tsveti Grncarova",
        "role":   "Account Manager",
        "region": "EMEA",
        "email":  "tsvetelina.rancheva@massiverocket.com",
        "active": True,
    },
    {
        "name":   "Jorge Arrechea",
        "role":   "AMER AM, transitioning to AE",
        "region": "AMER",
        "email":  "jorge.arrechea@massiverocket.com",
        "active": True,
    },
    {
        "name":   "Marija Veljanova",
        "role":   "AMER AM, transitioning to AE",
        "region": "EMEA",
        "email":  "marija.veljanova@massiverocket.com",
        "active": True,
    },
    {
        "name":   "Darren Addy",
        "role":   "EMEA AM, transitioning to AE",
        "region": "EMEA",
        "email":  "darren.addy@massiverocket.com",
        "active": True,
    },
    {
        "name":   "Claudia Lima",
        "role":   "Partner Manager, AMER",
        "region": "AMER",
        "email":  "claudia.lima@massiverocket.com",
        "active": True,
    },
    {
        "name":   "Sonal Dalia",
        "role":   "Partner Manager",
        "region": "EMEA",
        # Email not provided in the roster — left blank intentionally.
        # Update here when confirmed.
        "email":  "",
        "active": True,
    },
    {
        "name":   "Jamie MacDow",
        "role":   "Marketing — co-owns New Accounts OKR",
        "region": "Global",
        "email":  "jamie.macdow@massiverocket.com",
        "active": True,
    },
    {
        "name":   "Lea",
        "role":   "Marketing",
        "region": "Global",
        # Single-name entry from the roster — surname pending.
        "email":  "lea@massiverocket.com",
        "active": True,
    },
]


def list_owners(*, active_only: bool = True) -> list[dict[str, Any]]:
    """Return the owners list in display order. Pass active_only=False
    to include any future deactivated entries (e.g. former staff)."""
    if active_only:
        return [o for o in OWNERS if o.get("active", True)]
    return list(OWNERS)


def names(*, active_only: bool = True) -> list[str]:
    """Convenience for the bare list of names (the UI option labels)."""
    return [o["name"] for o in list_owners(active_only=active_only)]


def get_owner(name: str) -> dict[str, Any] | None:
    """Lookup by name (case-insensitive). Useful for resolving an owner
    string back to its email/role for notification flows later."""
    if not name:
        return None
    needle = name.strip().lower()
    for o in OWNERS:
        if o["name"].lower() == needle:
            return o
    return None
