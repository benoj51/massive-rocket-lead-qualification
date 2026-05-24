#!/usr/bin/env python3
"""One-off: backfill country + region on Hightouch partner contacts.

Run against the live Railway deploy when ready:

    APP_URL=https://your-app.up.railway.app \
    APP_AUTH_TOKEN=<your-token> \
    python3 scripts/backfill_hightouch_locations.py

Or against local (no auth):

    APP_URL=http://localhost:5000 \
    python3 scripts/backfill_hightouch_locations.py

Dry-run mode (just prints what would change):

    APP_URL=https://your-app.up.railway.app \
    APP_AUTH_TOKEN=<your-token> \
    DRY_RUN=1 \
    python3 scripts/backfill_hightouch_locations.py

What it does
------------
- GET /api/partners/hightouch/contacts            → list current state
- For each contact, infer (country, region) from title:
    country = "United States" for ALL (Ben confirmed every Hightouch
                                       contact is US-based)
    region  = "West Coast" / "East Coast" / "Central" / "APAC" when
              the title carries a clear marker; otherwise blank
- Skip contacts that already match the inferred values (idempotent)
- PATCH /api/partners/hightouch/contacts/<id> with the new fields

If you re-run after some manual edits, only the still-mismatched rows
get touched. Safe to re-run.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


PARTNER_ID = "hightouch"


def infer_region(title: str | None) -> str | None:
    t = (title or "").lower()
    if "apac" in t:
        return "APAC"
    if ", west" in t or "sales west" in t:
        return "West Coast"
    if ", east" in t or "sales east" in t or "north (east" in t:
        return "East Coast"
    if "central" in t:
        return "Central"
    return None


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
    print(f"Mode:   {'DRY-RUN (no writes)' if dry_run else 'LIVE WRITES'}")
    print()

    list_url = f"{base}/api/partners/{PARTNER_ID}/contacts"
    payload = _req("GET", list_url, token=token)
    contacts = payload.get("contacts") or []
    print(f"Fetched {len(contacts)} contacts from {list_url}\n")

    changes = []
    skipped = 0
    for c in contacts:
        cid = c.get("id")
        if not cid:
            continue
        new_country = "United States"
        new_region = infer_region(c.get("title"))
        new_regions = [new_region] if new_region else []
        before_country = c.get("country")
        before_regions = c.get("regions") or (
            [c.get("region")] if c.get("region") else [])
        if (before_country == new_country
                and sorted(before_regions) == sorted(new_regions)):
            skipped += 1
            continue
        changes.append({
            "id": cid,
            "name": c.get("name"),
            "title": c.get("title"),
            "country_was": before_country,
            "country_now": new_country,
            "region_was": before_regions,
            "region_now": new_regions,
        })

    print(f"Changes needed: {len(changes)}")
    print(f"Already correct: {skipped}\n")

    for ch in changes:
        region_str = ", ".join(ch["region_now"]) or "(none)"
        was_region = ", ".join(ch["region_was"]) or "(none)"
        print(f"  {ch['name']:<30} country: "
                f"{ch['country_was'] or '(none)':<14} → {ch['country_now']:<14} "
                f"region: {was_region:<14} → {region_str}")

    if dry_run:
        print("\nDRY_RUN set — no writes performed. Unset DRY_RUN and re-run to apply.")
        return

    if not changes:
        print("\nNothing to do. All contacts already correct.")
        return

    print(f"\nApplying {len(changes)} PATCHes...")
    for ch in changes:
        patch_url = f"{base}/api/partners/{PARTNER_ID}/contacts/{ch['id']}"
        _req("PATCH", patch_url, token=token, body={
            "country": ch["country_now"],
            "regions": ch["region_now"],
            # Keep singular `region` aligned for any older UI surfaces.
            "region":  ch["region_now"][0] if ch["region_now"] else None,
        })
        print(f"  ✓ {ch['name']}")
    print(f"\nDone. {len(changes)} contacts updated.")


if __name__ == "__main__":
    main()
