"""
Seed the Partners CRM with the Braze + Hightouch contacts referenced in
the Massive Rocket Command Centre context (v1.0.0f).

Run with:
    python3 seed_command_centre_partners.py
    APOLLO_USE_FIXTURES=1 python3 seed_command_centre_partners.py  # safer for testing

Idempotent — re-runs upsert rather than duplicate. Respects hierarchy via
`reports_to_id` where the relationship is known; leaves it null otherwise
(don't invent reporting lines we can't verify).

Data sources (from Ben's working memory):
- Braze: Glenn Bonforte (Partner Success) — confirmed
- Braze: Marina (Amoroso) Klusas — Strategic Enterprise AE, Popeyes US — confirmed
- Hightouch: no specific contacts in memory — partner record created
  for the AE to populate via UI or a later seed update

NB: Partner Success (Glenn) and Sales / Strategic AE (Marina) sit in
different functions at Braze and don't share a reporting chain, so
both land as roots in the org chart. The AE can adjust hierarchy in
the UI once the real reporting structure is known.
"""
from __future__ import annotations

import sys
from typing import Any

import partner_contacts_store
import partners_store


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

BRAZE_PARTNER = {
    "name": "Braze",
    "type": "Technology partner",
    "url": "braze.com",
    "owner": "Ben Ojuolape",
    "description": "Customer engagement platform — primary CEP partner for "
                    "MR's Retention + Migration plays.",
}

HIGHTOUCH_PARTNER = {
    "name": "Hightouch",
    "type": "Technology partner",
    "url": "hightouch.com",
    "owner": "Ben Ojuolape",
    "description": "Reverse-ETL / Composable CDP partner. Pairs with Braze "
                    "for Retention deals where the warehouse is the source "
                    "of truth.",
}

# Braze contacts — confirmed from Command Centre context.
BRAZE_CONTACTS: list[dict[str, Any]] = [
    {
        # Stable internal id so re-runs upsert rather than duplicate.
        "id": "braze-glenn-bonforte",
        "name": "Glenn Bonforte",
        "title": "Partner Success",
        # Partner Success usually covers North America strategic accounts.
        "territories": ["Strategic Enterprise", "Enterprise"],
        "regions": ["East Coast", "West Coast", "Central"],
        "country": "United States",
        "industries": ["QSR", "Retail", "Travel & Hospitality"],
        "mr_owner": "Ben Ojuolape",
        "status": "active",
        "cadence_days": 30,
        "tags": ["command_centre_seed"],
    },
    {
        "id": "braze-marina-klusas",
        "name": "Marina Klusas",
        # Maiden name Amoroso documented in Ben's memory; recording the
        # current professional name on the record.
        "title": "Strategic Enterprise Account Executive",
        "territories": ["Strategic Enterprise"],
        # Popeyes US — US-anchored. Marking East Coast as primary; AE
        # can adjust if she's actually multi-region.
        "regions": ["East Coast"],
        "country": "United States",
        "industries": ["QSR"],
        "mr_owner": "Ben Ojuolape",
        "status": "active",
        "cadence_days": 21,  # Tighter cadence for active strategic AE.
        "tags": ["command_centre_seed", "popeyes_us"],
        # reports_to_id intentionally left null — different function from
        # Glenn (Sales vs Partner Success). AE adjusts via UI when known.
    },
]

# Hightouch — partner registered, contacts to be populated by the AE.
# Adding a single PLACEHOLDER contact would risk reading as real data.
HIGHTOUCH_CONTACTS: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Seed runner
# ---------------------------------------------------------------------------

def _upsert_partner(payload: dict[str, Any]) -> str:
    saved = partners_store.save_partner(payload)
    return saved["id"]


def _upsert_contact(partner_id: str, payload: dict[str, Any]) -> str:
    saved = partner_contacts_store.save_contact(partner_id, payload)
    return saved["id"]


def seed() -> dict[str, Any]:
    """Apply the seed. Returns a summary dict for the caller."""
    summary = {
        "partners_seeded": [],
        "contacts_seeded": [],
        "contacts_skipped": [],
    }

    # Braze
    braze_id = _upsert_partner(BRAZE_PARTNER)
    summary["partners_seeded"].append({"id": braze_id, "name": BRAZE_PARTNER["name"]})
    for c in BRAZE_CONTACTS:
        try:
            cid = _upsert_contact(braze_id, c)
            summary["contacts_seeded"].append({
                "partner": "Braze", "contact_id": cid, "name": c["name"],
            })
        except partner_contacts_store.PartnerContactsStoreError as e:
            summary["contacts_skipped"].append({"name": c.get("name"), "reason": str(e)})

    # Hightouch
    ht_id = _upsert_partner(HIGHTOUCH_PARTNER)
    summary["partners_seeded"].append({"id": ht_id, "name": HIGHTOUCH_PARTNER["name"]})
    for c in HIGHTOUCH_CONTACTS:
        try:
            cid = _upsert_contact(ht_id, c)
            summary["contacts_seeded"].append({
                "partner": "Hightouch", "contact_id": cid, "name": c["name"],
            })
        except partner_contacts_store.PartnerContactsStoreError as e:
            summary["contacts_skipped"].append({"name": c.get("name"), "reason": str(e)})

    return summary


if __name__ == "__main__":
    s = seed()
    print(f"Seeded {len(s['partners_seeded'])} partners, "
          f"{len(s['contacts_seeded'])} contacts.")
    for p in s["partners_seeded"]:
        print(f"  partner: {p['name']} (id={p['id']})")
    for c in s["contacts_seeded"]:
        print(f"  contact: {c['name']} → {c['partner']}")
    if s["contacts_skipped"]:
        print(f"Skipped {len(s['contacts_skipped'])} contact(s):")
        for c in s["contacts_skipped"]:
            print(f"  - {c.get('name')}: {c.get('reason')}")
    if not HIGHTOUCH_CONTACTS:
        print("")
        print("NOTE: No Hightouch contacts seeded — partner record exists,")
        print("      add named contacts via the Partners UI when ready.")
    sys.exit(0)
