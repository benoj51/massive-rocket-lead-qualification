#!/usr/bin/env python3
"""One-off: add the 6 EMEA Hightouch contacts Ben provided.

Run against the live Railway deploy:

    APP_URL=https://your-app.up.railway.app \
    APP_AUTH_TOKEN=<your-token> \
    python3 scripts/add_hightouch_emea_contacts.py

Dry-run (just prints what would be added):

    APP_URL=... APP_AUTH_TOKEN=... DRY_RUN=1 \
    python3 scripts/add_hightouch_emea_contacts.py

Idempotent
----------
Before POSTing, the script fetches the current contact roster and
SKIPS any new contact whose name (case-insensitive) is already there.
Safe to re-run after partial failures or manual edits.

Schema notes
------------
- `city` isn't a first-class field in partner_contacts_store.
  Preserved as a tag (`tags: ["Paris"]`) so the info isn't lost.
- UK-based contacts get BOTH regions (["UK", "EMEA"]) so they show
  up under either filter. France/Italy contacts get just ["EMEA"].
- Seniority inferred from title: VP → VP, Director → Director,
  everything else → Individual Contributor.
- Tier + sentiment left blank — those are signals Ben wants to set
  after actually meeting the person.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


PARTNER_ID = "hightouch"

NEW_CONTACTS = [
    {"name": "Jennifer Timmerman",
     "title": "VP Sales Europe South & MENA",
     "country": "France", "city": "Paris",
     "regions": ["EMEA"], "seniority": "VP"},
    {"name": "Alexandre Poullard",
     "title": "Enterprise Account Executive EMEA",
     "country": "France", "city": "Paris",
     "regions": ["EMEA"], "seniority": "Individual Contributor"},
    {"name": "Alexandre Paradelo",
     "title": "Account Executive, EMEA",
     "country": "France", "city": None,
     "regions": ["EMEA"], "seniority": "Individual Contributor"},
    {"name": "Hugo Boudry",
     "title": "Account Executive EMEA",
     "country": "Italy", "city": None,
     "regions": ["EMEA"], "seniority": "Individual Contributor"},
    {"name": "John Ade",
     "title": "Senior Enterprise Account Executive",
     "country": "United Kingdom", "city": "London",
     "regions": ["UK", "EMEA"], "seniority": "Individual Contributor"},
    {"name": "George Lynch",
     "title": "Director of Technology Partnerships",
     "country": "United Kingdom", "city": "London",
     "regions": ["UK", "EMEA"], "seniority": "Director"},
]


def _req(method: str, url: str, *, body: dict | None = None,
          token: str | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read().decode() or "{}"
            return json.loads(payload)
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode()
        except Exception:
            pass
        raise SystemExit(
            f"\nHTTP {e.code} on {method} {url}\n{body_text}\n")


def main():
    base = os.environ.get("APP_URL", "").rstrip("/")
    if not base:
        raise SystemExit(
            "APP_URL env var required (e.g. https://your-app.up.railway.app)")
    token = os.environ.get("APP_AUTH_TOKEN") or None
    dry_run = os.environ.get("DRY_RUN", "").strip() not in ("", "0", "false")

    print(f"Target: {base}")
    print(f"Auth:   {'token set' if token else 'none'}")
    print(f"Mode:   {'DRY-RUN (no writes)' if dry_run else 'LIVE WRITES'}\n")

    list_url = f"{base}/api/partners/{PARTNER_ID}/contacts"
    payload = _req("GET", list_url, token=token)
    existing = payload.get("contacts") or []
    existing_names = {(c.get("name") or "").strip().lower() for c in existing}
    print(f"Current roster: {len(existing)} contacts\n")

    to_add, to_skip = [], []
    for n in NEW_CONTACTS:
        if n["name"].lower() in existing_names:
            to_skip.append(n)
        else:
            to_add.append(n)

    print(f"To add:  {len(to_add)}")
    for n in to_add:
        regions = ", ".join(n["regions"])
        city = f" · {n['city']}" if n["city"] else ""
        print(f"  + {n['name']:<22}  {n['title']}  →  {n['country']}{city}  [{regions}]")
    if to_skip:
        print(f"\nAlready present (skip): {len(to_skip)}")
        for n in to_skip:
            print(f"  - {n['name']}")

    if dry_run:
        print("\nDRY_RUN set — no writes performed.")
        return

    if not to_add:
        print("\nNothing to add. Roster is already up to date.")
        return

    print(f"\nPOSTing {len(to_add)} new contacts...")
    create_url = f"{base}/api/partners/{PARTNER_ID}/contacts"
    for n in to_add:
        body = {
            "name":      n["name"],
            "title":     n["title"],
            "country":   n["country"],
            "regions":   n["regions"],
            "seniority": n["seniority"],
            "status":    "active",
            "tags":      [n["city"]] if n["city"] else [],
        }
        _req("POST", create_url, token=token, body=body)
        print(f"  ✓ {n['name']}")
    print(f"\nDone. {len(to_add)} contacts added.")


if __name__ == "__main__":
    main()
