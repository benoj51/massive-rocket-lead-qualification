#!/usr/bin/env python3
"""Seed the Q2 2026 quarterly targets from Ben's leadership doc.

Run against the live Railway deploy:

    APP_URL=https://your-app.up.railway.app \
    APP_AUTH_TOKEN=<your-token> \
    python3 scripts/seed_q2_2026_targets.py

Dry-run (prints what would change, no writes):

    APP_URL=... APP_AUTH_TOKEN=... DRY_RUN=1 \
    python3 scripts/seed_q2_2026_targets.py

Idempotent
----------
The script PATCHes cell-by-cell. Re-running with the same data is a
no-op; re-running with changed numbers overwrites only the cells that
differ. Cells the script never touches are left alone, so editor
changes Ben makes between runs are preserved.

Interpretation notes (read these before re-running)
---------------------------------------------------
The leadership-doc layout was function-as-column with one or two
metrics per row. The parsing below is my best read. Where the column
assignment was ambiguous, the rule was:

- QLs + Warm Introductions + Positive Actions: per-function values
  as listed (Marketing, Partnerships, BD, AM, Big Bets).
- Engagement signals (Email Opens, Social Engagement, Connection
  Requests, Content Views): assigned to MARKETING.
- Conversations (AE, CSM, Outbound, Referral): assigned to MARKETING.
- Content (Case Studies, LinkedIn, Blog, Newsletters, Webinar):
  assigned to MARKETING.
- Vendor meetings (Braze, Hightouch, Snowflake, Other Vendors):
  assigned to PARTNERSHIPS (these are partner-relationship metrics).
- Sequences + Expansion: assigned to ACCOUNT MANAGEMENT.
- City x City has a 50/50 split between AM and Big Bets per the
  plan doc - both rows are seeded.

Team totals are NOT auto-summed - this script leaves the "team" row
empty unless explicitly set, so Ben can decide whether to use the
team row for company-wide goals or per-function sums.

Named QL accounts (GoPuff Bevmo, KFC US, etc) are preserved in
knowledge/q2_2026_targets.md as audit trail. They don't fit the
counter-only data model.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


QUARTER_ID = "2026-Q2"

# Each entry: (metric_key, owner_function, plan, actual).
# owner = None means team-row, owner = "Marketing" etc means per-function.
SEED: list[tuple[str, str | None, int, int]] = [
    # --- QLs from Prioritised Logos ---
    ("qls_prioritised", "Marketing",            10, 0),
    ("qls_prioritised", "Partnerships",          9, 5),
    ("qls_prioritised", "Business Development",  4, 3),
    ("qls_prioritised", "Account Management",   10, 3),
    # --- QLs from Non-Prioritised Logos ---
    ("qls_non_prioritised", "Marketing",            20, 0),
    ("qls_non_prioritised", "Partnerships",         15, 6),
    ("qls_non_prioritised", "Business Development",  8, 0),
    ("qls_non_prioritised", "Account Management",   10, 1),
    # --- Positive Actions (Marketing) ---
    ("positive_actions_prioritised",     "Marketing",  25, 0),
    ("positive_actions_non_prioritised", "Marketing", 100, 0),
    # --- Warm Introductions Prioritised ---
    ("warm_intros_prioritised", "Partnerships",         18, 0),
    ("warm_intros_prioritised", "Business Development", 10, 0),
    ("warm_intros_prioritised", "Account Management",    0, 4),
    # --- Warm Introductions Non-Prioritised ---
    ("warm_intros_non_prioritised", "Partnerships",         30, 6),
    ("warm_intros_non_prioritised", "Business Development", 15, 0),
    # --- Engagement signals (Marketing) ---
    ("email_opens",                   "Marketing",  500, 118),
    ("social_engagement",             "Marketing", 1500,   0),
    ("connection_requests_accepted",  "Marketing",   75,  46),
    ("content_views",                 "Marketing", 2500,   0),
    # --- Conversations (Marketing) ---
    ("ae_conversations",                   "Marketing", 96, 45),
    ("csm_conversations",                  "Marketing", 48,  3),
    ("outbound_stakeholder_conversations", "Marketing", 60,  0),
    ("referral_conversations",             "Marketing", 12,  0),
    # --- Content (Marketing) ---
    ("case_studies",         "Marketing", 12, 5),
    ("linkedin_posts",       "Marketing", 48, 3),
    ("blog_posts",           "Marketing", 12, 2),
    ("customer_newsletters", "Marketing",  3, 0),
    ("partner_newsletters",  "Marketing",  3, 0),
    ("webinars",             "Marketing",  1, 0),
    # --- Vendor meetings (Partnerships) ---
    ("meetings_braze",          "Partnerships", 72, 22),
    ("meetings_hightouch",      "Partnerships", 50, 17),
    ("meetings_snowflake",      "Partnerships", 11,  8),
    ("meetings_other_vendors",  "Partnerships", 11,  4),
    # --- Sequences (Account Management) ---
    ("sequences_expand_new",         "Account Management", 2, 0),
    ("sequences_winback",            "Account Management", 1, 0),
    ("proactive_engagement_winback", "Account Management", 1, 0),
    # --- Expansion ---
    ("city_x_city_conversations",   "Account Management", 50, 0),
    ("city_x_city_conversations",   "Big Bets",           50, 0),
    ("expansion_strategy_sessions", "Account Management", 30, 0),
    ("multithreading_meetings",     "Account Management", 60, 0),
    ("expansion_discovery_calls",   "Account Management", 120, 0),
]


def _api_url(path: str) -> str:
    base = (os.environ.get("APP_URL") or "").rstrip("/")
    if not base:
        sys.exit("APP_URL env var required (e.g. https://web-production-b7cb5.up.railway.app)")
    return f"{base}{path}"


def _patch(quarter_id: str, body: dict, dry_run: bool) -> dict:
    url = _api_url(f"/api/quarterly-targets/{quarter_id}")
    if dry_run:
        print(f"  [DRY] PATCH {url}  body={body}")
        return {}
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, method="PATCH", data=data)
    req.add_header("Content-Type", "application/json")
    tok = os.environ.get("APP_AUTH_TOKEN", "").strip()
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        body_str = e.read().decode("utf-8", errors="replace")
        sys.exit(f"PATCH failed ({e.code}) for {body}: {body_str}")
    except urllib.error.URLError as e:
        sys.exit(f"Network error for {body}: {e}")


def main() -> None:
    dry = (os.environ.get("DRY_RUN") or "").strip() in ("1", "true", "yes")
    print(f"Seeding {QUARTER_ID}: {len(SEED) * 2} cells "
          f"({'DRY RUN' if dry else 'LIVE'})")
    for metric_key, owner, plan, actual in SEED:
        scope = owner or "<team>"
        print(f"- {metric_key:<40} {scope:<22}  plan={plan:<5} actual={actual}")
        _patch(QUARTER_ID, {
            "metric": metric_key, "kind": "plan",
            "owner":  owner, "value": plan,
        }, dry)
        _patch(QUARTER_ID, {
            "metric": metric_key, "kind": "actual",
            "owner":  owner, "value": actual,
        }, dry)
    print(f"\nDone. View at {_api_url('/').rstrip('/')}/  - Dashboard > Quarterly Targets.")


if __name__ == "__main__":
    main()
