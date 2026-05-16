# Lead Qualification Platform — PRD

**Status:** v0.2.0 shipped 2026-05-13
**Owner:** Ben Ojuolape (Head of Partnerships, Massive Rocket)
**Reviewers:** CEO, Head of GTM, AE leadership

---

## 1. Problem

Lead qualification at Massive Rocket today is inconsistent. Partner Managers,
AEs, and the leadership team all evaluate inbound and outbound accounts with
different mental models, scattered across spreadsheets, Slack threads, and
ad-hoc HubSpot notes. The downstream pain:

- **Slow handoffs.** A lead can sit two weeks before anyone agrees whether
  it's worth pursuing.
- **Inconsistent prioritisation.** Two AEs faced with the same account often
  reach different conclusions about fit.
- **No shared pipeline view.** The CEO and Head of Partnerships can't see, at
  a glance, what's actively being qualified and where it sits.
- **Manual enrichment.** Revenue, headcount, tech stack — all hand-typed from
  LinkedIn, web search, or guesswork.

We have an ICP scoring engine in Python and a Notion tracker, but they're not
wired together and they're not usable by the team.

## 2. Goal

A team-facing web platform that:

1. Scores any company against MR's ICP in under 30 seconds, with one click.
2. Enriches the account automatically (Apollo) so AEs aren't typing
   revenue/headcount/tech.
3. Pushes the result to Notion as the single source of truth for pipeline.
4. Lets AEs track MEDDICC progress per account in the same view.
5. Surfaces a pipeline dashboard the whole team — and the CEO — can read.

## 3. Non-goals

- **Not a HubSpot replacement.** HubSpot remains the system of record for
  contacts and deals. (HubSpot write-back is a v0.3 feature, post-CEO sign-off.)
- **Not a forecasting tool.** Stages and weighted pipeline value live in
  HubSpot.
- **Not a full CRM.** No activity logging, no email integration.
- **Not multi-tenant.** Single MR instance, internal use only.
- **Not external-facing.** Behind Railway auth; no prospect-facing surface.

## 4. Users

| Persona | Daily use case | Primary view |
| ------- | -------------- | ------------ |
| Partner Manager (stages 1-3) | Qualify inbound from Braze/Hightouch referrals, decide whether to take an intro call. | Qualify Lead |
| AE / Client Partner (stages 4+) | Pick up qualified leads from Partner Manager, track MEDDICC, push pipeline view to leadership. | Qualify Lead + Pipeline |
| Head of Partnerships (Ben) | Audit consistency, review pipeline, override scores. | Pipeline + per-lead detail |
| CEO | Glance at top-of-funnel + qualified pipeline weekly. | Pipeline |

## 5. Functional requirements

### 5.1 Qualify a lead
- **Input:** company name + URL.
- **Auto-enrichment** via Apollo `organizations/enrich`: revenue, employee
  count, industry, headquarters country, current tech stack.
- **Stakeholder discovery** via Apollo `mixed_people/search` for CMO / VP
  CRM / Head of Lifecycle / Director Marketing roles.
- **Scoring** against the 7-criterion ICP (revenue, employees, vertical, tech
  stack, complexity, deal size, region). Output is weighted-of-51 + normalised
  10-point score.
- **Opportunity classification:** Retention / Retention Light / Migration /
  Augmentation / Greenfield / Unknown.
- **Override:** every discovered field is click-to-edit; user can re-score.
- **Output:** ICP score, status (Qualify In / Borderline / Qualify Out),
  signals, hard disqualifiers, fit summary, next-step list, stakeholder table.

### 5.2 MEDDICC tracking
- Six fields: Metrics, Economic Buyer, Decision Criteria, Decision Process,
  Identify Pain, Champion.
- Each field has a free-text note and a Not-Started / In-Progress / Confirmed
  toggle.
- Roll-up score (0-18) computed automatically.

### 5.3 Push to Notion
- Single button creates or updates a page in the Lead Qualification Tracker.
- Notion is treated as the system of record for the qualification artefact.
- On update: properties replaced, page content blocks left intact so AE
  comments aren't clobbered.

### 5.4 Pipeline dashboard
- Sortable table (Company, ICP, Status, Stage, Vertical, Opportunity Type,
  Owner, Next Step).
- Filter chips: All / Qualified / Borderline / Qualified Out / Active only.
- Data pulled live from Notion via `/api/pipeline`.

### 5.5 Configuration
- ICP weights and tier definitions live in `config.py`. Calibration changes
  require a code change and a deploy (intentional — the scoring rubric is
  load-bearing).

## 6. Non-functional requirements

- **Latency.** First qualification (cold Apollo call): under 4s. Subsequent
  qualifications of the same domain (cache hit): under 200ms.
- **Availability.** Best-effort. Single Railway instance is fine for v0.2.
- **Security.** API keys live only in Railway env vars; never committed,
  never returned by the API. UI fetches only via same-origin.
- **Data residency.** Apollo cache (24h TTL) stored in container ephemeral
  storage. Notion is the durable layer.
- **Observability.** Flask access logs to stdout (Railway tail) plus health
  endpoint reflecting upstream integration status.

## 7. Success metrics

| Metric | Baseline | 90-day target |
| ------ | -------- | ------------- |
| Median time from "new lead" to scored | ~2 days | < 5 minutes |
| % of leads with an ICP score in Notion | < 20% | > 90% |
| AE adoption (weekly active users) | 0 | 4 of 5 AEs + 3 Partner Managers |
| CEO weekly check-in uses the Pipeline view | n/a | yes, every Monday |
| Apollo credit consumption | n/a | < 200 enrichments/month (cache covers re-views) |

## 8. ICP scoring model (summary)

| Criterion | Weight | Max | Notes |
| --------- | ------ | --- | ----- |
| Revenue | 3× | 9 | < $100M = 0 ... > $1B = 3 |
| Employees | 2× | 6 | < 500 = 0 ... 3,000+ = 3 |
| Vertical | 3× | 9 | Direct weighted: QSR/Roadside = 9, Delivery/C-store = 7, Retail/Travel = 6, Fintech/Telecom = 5, Other = 3 |
| Tech Stack | 3× | 9 | Opportunity-typed: Retention (Braze+Snowflake) = 9, Retention Light = 7, Migration = 5, Augmentation = 4, Greenfield = 2, Unknown = 0 (strict) |
| Complexity | 2× | 6 | Single = 1, Multi-brand or Multi-market = 2, Both = 3 |
| Deal Size | 3× | 9 | < £10k/mo = 0 ... > £50k/mo = 3 |
| Region | 1× | 3 | Other = 0, APAC = 1, NAM/EMEA = 2, Multi-region = 3 |
| **Total** | | **51** | Normalised to /10. ≥ 7.0 Qualify In · 5.0-6.9 Borderline · < 5.0 Qualify Out |

### Hard disqualifiers (automatic Qualify Out)
- Revenue < $50M
- Employees < 200
- No Braze and no plans to adopt
- Sales cycle > 18 months
- Competing agency locked in (non-incumbent)
- No executive sponsor access
- Budget cycle > 12 months away
- Non-English-speaking market only

## 9. System architecture

```
Browser (qualify.html)
   │
   ▼  fetch /api/...
Flask (server.py)
   ├── apollo.py ──► Apollo REST (cached, 24h)
   ├── scoring.py + config.py
   └── notion_sync.py ──► Notion REST (data-source-aware)
```

- **Hosting:** Railway, Dockerfile-based deploy.
- **Data store:** Notion (Lead Qualification Tracker). No Postgres.
- **Cache:** Local file cache for Apollo responses (24h TTL).

## 10. Phases & roadmap

### v0.2 — shipped 2026-05-13
Everything in §5 above.

### v0.2.1 — shipped 2026-05-13
Shared-secret auth, Sales Stage + Owner selectors, MEDDICC notes preserved
on the Notion page, seeded-account calibration tests, AI fit summary
(v0.4 brought forward), server + auth integration tests.

### v0.3 — shipped 2026-05-13 (HubSpot disabled by default)
- `/api/hubspot/sync` mirrors `/api/notion/sync` shape.
- Creates or updates HubSpot company with ICP score, opportunity type,
  fit summary, lifecyclestage.
- **Awaits CEO approval before activation.** Toggle via `HUBSPOT_API_KEY`
  + `HUBSPOT_SYNC_ENABLED=1`. Returns 503 when off.

### v0.4 — shipped in v0.2.1 (brought forward)
AI-assisted fit summaries via Anthropic, with heuristic fallback. See
`ai_summary.py`. The "outreach line per stakeholder" piece is still TODO.

### v0.5 — shipped 2026-05-13
- Append-only JSON-lines audit log at `cache/audit.jsonl`. Every qualify
  + sync writes one event with timestamp, actor, outcome.
- `GET /api/audit` reads the log + emits a rollup summary.
- Slack weekly digest builder (`slack_digest.py`). `GET /api/slack/digest`
  previews; `POST .../digest?send=1` posts to `SLACK_WEBHOOK_URL`. Schedule
  via Railway Cron or external scheduler.

### v0.4 — shipped 2026-05-15 (Project Build + Pricing)
- **Project Build** stage between Pipeline and (future) SOW.
- 5 project types: CRM Strategy / CRM Build / CRM Execute / Data / Engineering.
- Per-criterion 3-state qualification (Unqualified → Qualifying →
  Qualified). Criteria are tagged with role drivers so scope answers
  feed pricing.
- **Pricing Calculator** codified in `pricing.py`. Reference deal reproduced
  ($1.19M gross / $1.11M net). Single blended USD/hour rate, per-phase
  team allocations, configurable discount.
- **Delivery validation gate.** Scope flows `draft →
  pending_validation → validated/rejected` before Pricing is sent.
- MEDDICC label renamed to MEDDPICC throughout the UI (criteria
  unchanged — full 8-criteria MEDDPICC pending Notion schema additions).

### v0.5 — TBD (next up)
- Draft SOW renderer pulling Apollo + scope + pricing into a single
  reviewable document.
- Slack notification when scope hits `pending_validation` so delivery
  picks it up promptly.
- Filter chips for `pending_validation` in the Pipeline view.

### v0.6 — TBD
- Outreach-line drafter per stakeholder (Anthropic).
- Move audit log + project store off ephemeral disk to durable storage
  (Railway volume or Postgres) once daily volume justifies it.
- Custom dashboard panels: stage-by-stage conversion, time-in-stage.
- Full MEDDPICC (add Paper Process + Competition criteria + Notion schema).

## 11. Open questions

1. **Apollo billing visibility.** Who monitors monthly credit consumption?
2. **Score recalibration cadence.** When does the ICP weight table get
   reviewed? (Last calibration: 7 April 2026.)
3. **Multi-owner support.** Today every page is owned by Ben on push. Should
   the UI surface an owner picker before push?
4. **Disqualifier overrides.** A hard disqualifier flips Status to Qualify
   Out automatically. Do we need a "qualified exception" mode for cases
   where a hard rule should be overridden with sign-off?

## 12. Out of scope (will defer)

- LinkedIn enrichment (Apollo covers ~80% of the LinkedIn fields we need).
- A mobile native app — the responsive web UI is sufficient.
- Per-vertical custom scoring (e.g. different weights for QSR vs Fintech).
- Permissions / role-based UI (everyone with the URL sees everything).
