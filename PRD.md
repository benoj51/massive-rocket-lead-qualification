# Lead Qualification Platform - PRD

**Status:** v1.0.0du (live), 2026-05-29
**Owner:** Ben Ojuolape (Head of Partnerships + AE management, Massive Rocket)
**Reviewers:** CEO, Head of GTM, AE leadership, Delivery
**Repo:** `Massive Rocket/lead-qualification-platform/`
**Companion docs:** [README.md](README.md) (run/deploy) , [HANDOVER.md](HANDOVER.md) (continuity brief for a fresh build session) , [CHANGELOG.md](CHANGELOG.md) (full version history)

> This PRD was rewritten on 2026-05-29 to reflect the platform as actually
> shipped. The original v0.2.0 PRD (2026-05-13) described a two-view scoring
> tool. The platform has since grown into a full pre-sale and account
> operations workspace (76 Python modules, ~180 API routes, 1331 tests). The
> v0.x roadmap in older revisions is superseded by section 13 here. Where the
> ICP scoring rubric is concerned (section 9), the numbers are unchanged and
> remain load-bearing.

---

## 1. Problem

Lead qualification and account work at Massive Rocket started out inconsistent.
Partner Managers, AEs, and leadership evaluated accounts with different mental
models scattered across spreadsheets, Slack threads, and ad-hoc notes. The
original pain points still frame the product:

- Slow handoffs. A lead could sit for two weeks before anyone agreed whether it
  was worth pursuing.
- Inconsistent prioritisation. Two AEs faced with the same account often reached
  different conclusions about fit.
- No shared pipeline view. Leadership could not see, at a glance, what was being
  qualified and where it sat.
- Manual enrichment. Revenue, headcount, and tech stack were hand-typed from
  LinkedIn, web search, or guesswork.

As the tool matured, the problem widened from "score a lead" to "run the whole
pre-sale motion in one place": discovery calls and notes, MEDDPICC, scope and
pricing and SOW, partner relationships, expansion across group accounts, live
project handover, and the analytics leadership needs.

## 2. Goal

A single team-facing web workspace that:

1. Scores any company against MR's ICP in seconds, with one click.
2. Enriches the account automatically (Apollo) so AEs are not typing
   revenue/headcount/tech.
3. Treats Notion as the durable system of record for the pipeline.
4. Tracks MEDDPICC, discovery calls, contacts, and stakeholder maps per account.
5. Carries a qualified deal through Project Build, Scope, Pricing, and a draft
   SOW.
6. Surfaces the analytics leadership reads weekly (pipeline, forecast,
   engagement, quarterly targets, manager report).
7. Uses Claude to summarise, qualify, coach, and draft, with a strict no-hype,
   fact-only house voice.

## 3. Non-goals

- Not a HubSpot replacement. HubSpot remains the company system of record for
  contacts and deals. A HubSpot write path exists but is disabled by default
  and parked pending CEO sign-off.
- Not a forecasting system of record. The forecast view is a working aid, not
  the board number.
- Not multi-tenant. Single MR instance, internal use only.
- Not external-facing. Behind app auth, no prospect-facing surface.
- Not a full CRM replacement for activity/email logging beyond what discovery
  notes and contact cadence cover.

## 4. Users

| Persona | Use case | Primary surfaces |
| ------- | -------- | ---------------- |
| Partner Manager (early stages) | Qualify inbound from Braze / Hightouch / Snowflake referrals, decide whether to take an intro call, track partner relationships. | Qualify, Partners, Pipeline |
| AE / Client Partner | Pick up qualified leads, run discovery, track MEDDPICC, build scope and pricing, draft SOW, work expansion. | Pipeline, lead drawer, Project Build, Expansion |
| Head of Partnerships (Ben) | Audit consistency, manage AEs, review pipeline and partner coverage, override scores. | Pipeline, Dashboard, Partners, Directory |
| CEO / leadership | Weekly glance at pipeline, forecast, quarterly targets, and the manager report. | Dashboard, Forecast |
| Delivery | Pick up validated scope, run live projects and OKRs once a deal converts. | Live, Project Build |

## 5. The platform today (navigation)

Single-page app (`qualify.html`). Top nav (restructured in v1.0.0bm):

- **Home** - morning brief, needs-attention, watched accounts, todos, activity.
- **Pipeline** (dropdown): Pipeline table , Project Build , Forecast.
- **Live** - converted engagements, OKRs, stakeholder map, concurrent agencies.
- **Expansion** - group/associated accounts, expansion targets.
- **Directory** - cross-store roster of all accounts and contacts.
- **Partners** - partner orgs (Braze, Hightouch, Snowflake, mParticle, etc.),
  partner contacts, notes, assignment to leads.
- **Insights** (dropdown): Dashboard (engagement leaderboard, loss reasons,
  weekly manager report, quarterly targets, stakeholder coverage).
- **Settings** - users/owners, enums/dropdowns, integrations status, scheduled
  agents.
- **+ Qualify** (pinned CTA) - the qualify-a-lead action.
- Global contact search (Cmd-K), a floating "Jeff" pricing assistant, and an
  agentic chat surface.

## 6. Functional capabilities

### 6.1 Qualify a lead
- Input: company name + URL.
- Auto-enrichment via Apollo `organizations/enrich`: revenue, employees,
  industry, HQ country, tech stack.
- Stakeholder discovery via Apollo `mixed_people/api_search` for marketing /
  martech / CRM / lifecycle / data leadership, with optional region filter.
  Names resolve to "First Last", recovering masked surnames from the LinkedIn
  slug where Apollo gates them (v1.0.0du).
- Scoring against the 7-criterion ICP (section 9): weighted-of-51, normalised to
  a 10-point score.
- Opportunity classification: Retention / Retention Light / Migration /
  Augmentation / Greenfield / Unknown.
- Every discovered field is click-to-edit; the user can re-score.
- Output: ICP score, status (Qualify In / Borderline / Qualify Out), positive
  signals, hard disqualifiers, fit summary, next steps, stakeholder table.

### 6.2 Discovery calls, notes, and AI synthesis
- Per-lead calls/notes store (transcript or note), with Claude extraction of
  MEDDPICC signals, competitive agencies, and tech stack.
- AI "contact suggestions": people spotted in a note, offered for one-click
  save.
- Aggregated lead summary at the top of the opportunity
  (`ai_summary.synthesise_lead`): state of play, key facts, open questions, next
  action, risks, plus a qualification RAG verdict (green/amber/red with
  rationale) and 2-4 AE coaching points (v1.0.0dt). Group/parent/sibling context
  is fed in for accounts that belong to a group.

### 6.3 MEDDPICC tracking
- Per-criterion free-text note plus a Not-Started / In-Progress / Confirmed
  toggle, with an automatic roll-up. UI labelled MEDDPICC (full Paper Process +
  Competition criteria pending Notion schema work).

### 6.4 Contacts and stakeholder mapping
- Per-lead contacts with role (sponsor/champion/user/blocker), influence, and
  interest; an influence/interest map; reports-to relationships; contact cadence
  and overdue tracking; CSV import; per-contact notes.

### 6.5 Pipeline and lifecycle
- Sortable, filterable pipeline pulled live from Notion. Sales stages and lead
  statuses are configurable enums. Stage flips prompt for loss reasons where
  relevant. Default filter excludes Nurture and Rejected. CSV export is
  sanitised against formula injection.

### 6.6 Project Build, Scope, Pricing, SOW, Roadmap
- Project Build stage between Pipeline and SOW. Five project types
  (CRM Strategy / Build / Execute / Data / Engineering). Per-criterion 3-state
  scope qualification that feeds pricing. Pricing calculator (`pricing.py`)
  reproduces the reference deal. Delivery validation gate
  (draft -> pending_validation -> validated/rejected) before pricing is sent.
  Draft SOW renderer with versioning and a compliance check. Roadmap builder
  with AI refine and extended-engagement suggestions.

### 6.7 Engagement scoring
- Per-lead engagement score from recency and activity, with snapshots over time,
  trend arrows, at-risk detection and notifications, and an owner leaderboard on
  the Dashboard.

### 6.8 Expansion and group accounts
- Parent/child account detection, group context, AI-suggested associated
  accounts, and an expansion targets store with its own contacts.

### 6.9 Live projects
- Promote a converted lead to a live project; OKRs and key results; stakeholder
  map; concurrent agencies.

### 6.10 Partners
- Partner orgs and partner contacts (tier, sentiment, seniority, team), notes,
  bulk update, CSV import, touch cadence, and assignment of the right partner
  contact to a lead. Partner-sourced notes feed the lead synthesis.

### 6.11 Account intelligence
- Account news (Google News RSS plus AI relevance scoring) per watched account,
  a watchlist, and a sweep endpoint suitable for scheduling.

### 6.12 Analytics and leadership
- Dashboard: engagement leaderboard, loss-reason breakdown, weekly manager
  report, stakeholder coverage metric. Quarterly targets (team and per-owner,
  plan vs actual). Forecast view with configurable weighting.

### 6.13 Assistants and agents
- "Jeff": a pricing/knowledge assistant grounded in a Markdown knowledge base
  (editable in-app).
- Agentic chat: a tool-using Claude agent with a persona library and a tool
  registry (`mr_tools.py`), exposed both in-app and as an MCP server
  (`mr_mcp_server.py`, read-only by default).
- Scheduled agents: cron-style recurring jobs with a Settings surface.

### 6.14 Outreach
- AI outreach drafter (email / LinkedIn / Slack) per stakeholder. Drafts only,
  never auto-sent. Em-dashes are hard-stripped from output.

### 6.15 Notion sync
- One action creates or updates the lead's page in the Lead Qualification
  Tracker. Properties are replaced; page content blocks are preserved so AE
  comments are not clobbered. Notion is the system of record for the
  qualification artefact. Backup/mirror/restore and Notion history endpoints
  guard against accidental note loss.

### 6.16 Supporting surfaces
- Notifications, todos, activity feed, append-only audit log, use-cases catalog
  (read from a Postgres database), filter presets, and a diagnostics health
  endpoint.

## 7. Non-functional requirements

- **Latency.** First qualification (cold Apollo): a few seconds. Repeat views of
  the same domain hit a 24h file cache.
- **Auth.** All `/api/*` routes require `Authorization: Bearer <APP_AUTH_TOKEN>`
  when that env var is set. `/` and `/api/health` stay open so the UI can
  negotiate auth. Query-param tokens are off by default.
- **Rate limiting + startup guard.** `rate_limit.py` plus an auth startup guard
  (v1.0.0do).
- **Security.** API keys live only in env vars, never committed, never returned
  by the API. CSV export sanitised. `MAX_CONTENT_LENGTH` set. Store paths
  slugified. CORS tightened.
- **Persistence.** Notion is the durable layer for the pipeline. App-specific
  state (calls, contacts, partners, projects, todos, etc.) lives in JSON file
  stores under `cache/`, intended to sit on a Railway volume in prod (see
  `RAILWAY_VOLUME_MOUNT.md`). The use-cases catalog is read from a separate
  Postgres database (`DATABASE_URL_USECASES`).
- **Observability.** Flask logs to stdout (Railway tail). `/api/health` and
  `/api/diagnostics/health` reflect integration status.

## 8. Success metrics

| Metric | Baseline | Target |
| ------ | -------- | ------ |
| Median time from new lead to scored | ~2 days | < 5 minutes |
| % of active leads with an ICP score in Notion | < 20% | > 90% |
| Team adoption (weekly active) | 0 | AEs + Partner Managers |
| Leadership uses the Dashboard weekly | n/a | yes |
| Apollo credit consumption | n/a | covered by cache on re-views |

## 9. ICP scoring model (unchanged, load-bearing)

| Criterion | Weight | Max | Notes |
| --------- | ------ | --- | ----- |
| Revenue | 3x | 9 | < $100M = 0 ... > $1B = 3 |
| Employees | 2x | 6 | < 500 = 0 ... 3,000+ = 3 |
| Vertical | 3x | 9 | QSR/Roadside = 9, Delivery/C-store = 7, Retail/Travel = 6, Fintech/Telecom = 5, Other = 3 |
| Tech Stack | 3x | 9 | Retention (Braze+Snowflake) = 9, Retention Light = 7, Migration = 5, Augmentation = 4, Greenfield = 2, Unknown = 0 (strict) |
| Complexity | 2x | 6 | Single = 1, Multi-brand or Multi-market = 2, Both = 3 |
| Deal Size | 3x | 9 | < GBP 10k/mo = 0 ... > GBP 50k/mo = 3 |
| Region | 1x | 3 | Other = 0, APAC = 1, NAM/EMEA = 2 (DACH supported), Multi-region = 3 |
| **Total** | | **51** | Normalised to /10. >= 7.0 Qualify In , 5.0-6.9 Borderline , < 5.0 Qualify Out |

### Hard disqualifiers (automatic Qualify Out)
Revenue < $50M , employees < 200 , no Braze and no plans to adopt , sales cycle
> 18 months , competing agency locked in (non-incumbent) , no executive sponsor
access , budget cycle > 12 months away , non-English-speaking market only.

Calibration changes are a deliberate code change in `config.py` plus a deploy,
covered by the seeded-account calibration tests.

## 10. Architecture

```
Browser (qualify.html, single-page app, vanilla JS + Chart.js)
   | fetch /api/...
Flask (server.py, ~180 routes; reads qualify.html into memory once at boot)
   |
   |- qualify_service.py  orchestrator: Apollo -> ICP shape -> scoring -> signals -> fit summary -> stakeholders
   |- apollo.py           Apollo REST client (24h file cache; fixture fallback)
   |- scoring.py + config.py   ICP engine + rubric
   |- ai_summary.py       Anthropic synthesis (summaries, RAG verdict, coaching, fit, roadmap)
   |- agent.py + mr_tools.py + mr_mcp_server.py   tool-using agent + MCP server
   |- notion_sync.py      Notion REST (2025-09 data-source-aware) upsert + pipeline
   |- *_store.py (many)   JSON file stores under cache/ (calls, contacts, partners, projects, ...)
   |- usecases_db.py      Postgres read layer for the use-cases catalog
   |- pricing.py / scope.py / sow.py / roadmap.py   pre-sale build chain
   |- engagement.py / forecast.py / dashboard.py / stakeholder_coverage.py   analytics
   `- account_news.py / slack_digest.py / outreach.py / scheduled_agents.py   integrations + jobs
```

- **Hosting:** Railway, Dockerfile build, gunicorn (`Procfile`), healthcheck on
  `/api/health` (`railway.json`).
- **Durable data:** Notion (pipeline) + Railway volume (JSON stores) + Postgres
  (use-cases).

## 11. Integrations

| Integration | Module | Status |
| ----------- | ------ | ------ |
| Apollo (enrich + people search) | `apollo.py` | Live. 24h cache. Fixture fallback when no key. |
| Notion (tracker) | `notion_sync.py` | Live. System of record. |
| Anthropic (Claude) | `ai_summary.py`, `agent.py`, `jeff_knowledge.py` | Live when `ANTHROPIC_API_KEY` set; heuristic fallbacks otherwise. |
| Postgres (use-cases) | `usecases_db.py` | Read-only catalog via `DATABASE_URL_USECASES`. |
| Slack | `slack_digest.py` | Optional weekly digest via `SLACK_WEBHOOK_URL`. |
| Google News | `account_news.py` | RSS + AI relevance for watched accounts. |
| HubSpot | `hubspot_sync.py`, `legacy_hubspot.py` | Parked. 503 unless `HUBSPOT_SYNC_ENABLED=1`. Awaits CEO sign-off. |

## 12. Conventions and engineering workflow

These are enforced and should carry to any future build session:

- **Per-increment shipping.** Each change ships as its own version: bump the
  `<title>` in `qualify.html`, add a CHANGELOG entry, add/extend tests, run the
  full suite, commit. Do not push unless asked.
- **Versioning.** Currently in a long `v1.0.0xx` alpha-suffix sequence
  (`...dt`, `du`, ...).
- **Tests.** `python3 -m pytest` (not `python`). 1331 tests at v1.0.0du.
- **House voice.** UK English. No em-dashes in user-facing prose or
  AI-generated text. No marketing tone, no emojis, no invented statistics.
- **Outreach is drafts-only.** Never auto-send.
- **Secrets.** Never paste live secrets (especially the company `DATABASE_URL`)
  into chat. Set them in Railway. `cache/` is gitignored and never committed.
- **server.py reads qualify.html once at boot,** so UI edits need a server
  restart to show in a running preview.

## 13. Roadmap / open items

- Full MEDDPICC: add Paper Process + Competition criteria and the Notion schema.
- HubSpot deal sync activation (post CEO sign-off).
- Outreach-line drafter polish per stakeholder.
- Stakeholder rationale text (`qualify_service._stakeholder_why`) still contains
  em-dashes; bring it in line with the no-em-dash rule.
- Move any remaining ephemeral state fully onto the Railway volume / durable
  storage as volume justifies.
- Refresh `SETUP.md` (it still describes the legacy `index.html` + `app.js`
  flow) and the Obsidian wiki note (legacy `tools/` scripts).

## 14. Open questions

1. Apollo billing visibility: who monitors monthly credit consumption?
2. Score recalibration cadence: when does the ICP weight table get reviewed?
3. Push policy after the move to the corporate Claude license / corporate repo
   (see HANDOVER.md): which remote is the source of truth, and who approves
   writes to it.
4. Disqualifier overrides: do we need a signed-off "qualified exception" mode?

## 15. Out of scope (deferred)

LinkedIn enrichment beyond Apollo , a native mobile app , per-vertical custom
scoring weights , role-based permissions (everyone with the URL sees
everything).
