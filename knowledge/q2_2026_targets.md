# Q2 2026 - Quarterly targets snapshot

Source of truth = `cache/quarterly_targets.json` (writeable via
Settings → Targets in the UI). This doc preserves the **named QL
accounts** that came with Ben's leadership note, because the
counter-only store doesn't model "which deals count toward the
metric".

Re-seed the platform numbers via `scripts/seed_q2_2026_targets.py`
if the store is wiped.

## QLs - Prioritised Logos (target: 33 team-wide)

| Function | Actual | Plan | Accounts |
|---|---|---|---|
| Marketing | 0 | 10 |  |
| Partnerships | 5 | 9 | GoPuff Bevmo (Braze), Pizza Hut Thailand, KFC US (Snowflake), KFC Canada (Snowflake), Subway Canada (Braze) |
| Business Development | 3 | 4 | Sainsburys, Pret, Wise |
| Account Management | 3 | 10 | KFC UK, Taco Bell UK, Burger King Ireland |
| **Team** | **11** | **33** | |

## QLs - Non-Prioritised Logos (target: 53 team-wide)

| Function | Actual | Plan | Accounts |
|---|---|---|---|
| Marketing | 0 | 20 |  |
| Partnerships | 6 | 15 | Haivanas (Hightouch), Joe & The Juice (Braze), Barry's (Braze), Lumens (Braze), Neighbourly (Braze), xAi (Braze) |
| Business Development | 0 | 8 |  |
| Account Management | 1 | 10 | Pizza Hut Canada |
| **Team** | **7** | **53** | |

## Positive Actions (Marketing only)

| Metric | Actual | Plan |
|---|---|---|
| Positive Actions - Prioritised | 0 | 25 |
| Positive Actions - Non-Prioritised | 0 | 100 |

## Warm Introductions

| Function | Pri Actual | Pri Plan | Non-Pri Actual | Non-Pri Plan |
|---|---|---|---|---|
| Partnerships | 0 | 18 | 6 | 30 |
| Business Development | 0 | 10 | 0 | 15 |
| Account Management | 4 | - | 0 | - |

## Engagement (Marketing)

| Metric | Actual | Plan |
|---|---|---|
| Email Opens | 118 | 500 |
| Social Engagement | 0 | 1,500 |
| Connection Requests Accepted | 46 | 75 |
| Content Views | 0 | 2,500 |

## Conversations (Marketing)

| Metric | Actual | Plan |
|---|---|---|
| AE conversations | 45 | 96 |
| CSM conversations | 3 | 48 |
| Outbound stakeholder conversations | 0 | 60 |
| Referral / intro conversations | 0 | 12 |

## Content (Marketing)

| Metric | Actual | Plan |
|---|---|---|
| Case Studies / Customer Stories | 5 | 12 |
| LinkedIn Posts | 3 | 48 |
| Blog Posts | 2 | 12 |
| Customer Newsletters | 0 | 3 |
| Partner Newsletters | 0 | 3 |
| Webinars | 0 | 1 |

## Vendor / Partner Meetings (Partnerships)

| Metric | Actual | Plan |
|---|---|---|
| Meetings with Braze | 22 | 72 |
| Meetings with Hightouch | 17 | 50 |
| Meetings with Snowflake | 8 | 11 |
| Meetings with Other Vendors | 4 | 11 |

## Sequences (Account Management)

| Metric | Actual | Plan |
|---|---|---|
| Sequences per Expanded / New Logo | 0 | 2 |
| Sequence per Winback / Re-Engagement Logo | 0 | 1 |
| Proactive Engagement per Winback / Re-Engagement Logo | 0 | 1 |

## Expansion (Account Management + Big Bets)

| Metric | Actual | Plan (AM) | Plan (Big Bets) |
|---|---|---|---|
| Prospect / Client Conversations at City x City | 0 | 50 | 50 |
| Expansion Strategy Sessions | 0 | 30 | - |
| New Stakeholder / Multithreading Meetings | 0 | 60 | - |
| Expansion Discovery Calls | 0 | 120 | - |

## Big Bets initiatives

Qualitative goals (no counter):

- **City-x-City** - the prospect-meeting roadshow
- **Thierry Outreach Trial** - test outbound campaign
- **Yum Loyalty Summit** - sponsored / hosted event

## Parser caveats (Claude → seed mapping)

Where the leadership-doc layout was column-ambiguous, the seed
script used these defaults:

- "Other" column in the actuals section = "Big Bets" column in the
  plan section (same fifth column).
- Engagement signals + Conversations + Content all assigned to
  **Marketing** (Jamie's function).
- Vendor meetings assigned to **Partnerships** (these track
  partner-relationship time).
- Sequences + Expansion assigned to **Account Management**.

If any of the above is wrong, fix it via Settings → Targets - each
cell saves on blur, no script re-run needed.
