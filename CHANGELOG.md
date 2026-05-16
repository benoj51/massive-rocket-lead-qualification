# Changelog

All notable changes to the Massive Rocket Lead Qualification Platform.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.3] — 2026-05-15

Partner sourcing — track both directions of partner-led pipeline.

### Added
- **Source of opportunity** (single-select) in Qualify Lead + Lead
  Detail drawer. Captures who brought this lead *to* MR. Options:
  Braze, Hightouch, Snowflake, Talon.one, Voucherify, mParticle,
  Segment, Inbound, Outbound, Cold Outreach, Customer Referral, Other.
  Writes to existing `Partner Source` select column.
- **Sourced for partners** (multi-select chips) in Qualify Lead +
  Lead Detail drawer. Captures which partners we're sourcing this
  account *for*. Options: Braze, Hightouch, Snowflake, Talon.one,
  Voucherify, mParticle, Segment. Writes to new `Sourced For`
  multi_select column.
- `notion_sync._extract_multi_select` helper to read multi_select
  properties back from Notion.
- Both fields surfaced in `_page_to_detail`, in `update_page` (with
  clear-on-empty semantics), and in the `qualify()` payload defaults.
  Existing `partner_source` override on QualificationOverrides now
  flows through as the default `opportunity_source`.

### Required Notion schema additions
- **`Sourced For`** (multi_select) — needs to be added to the Lead
  Qualification Tracker database before pushes will work. Steps:
  1. Open the tracker DB in Notion → click the `+` to add a property
  2. Name: **Sourced For** (exactly that)
  3. Type: **Multi-select**
  4. (Optional) Pre-create the options: Braze, Hightouch, Snowflake,
     Talon.one, Voucherify, mParticle, Segment — or let Notion add
     them as you push leads.
- **`Partner Source`** already in the docs schema and used here, but
  if it doesn't exist as a select column in your DB, add it the same
  way with the option list above (plus Inbound/Outbound/Cold Outreach
  /Customer Referral/Other).

If those columns are missing, Notion 400s the push and the UI shows a
red toast. Adding them fixes both Qualify Lead pushes and Lead Detail
drawer saves immediately — no redeploy needed.

### Tests
- 148 total (+12). Covers payload defaults, Notion encode (select +
  multi_select), Notion decode (with missing-column safety), update
  flow including clearing values.

## [0.5.2] — 2026-05-15

Click any row in Pipeline → edit the lead in-platform. No more
context-switching to Notion just to bump a status.

### Added
- **Lead Detail drawer** — sliding right-side panel triggered by
  clicking any Pipeline row. Shows every editable field grouped into
  Identity / Qualification / Discovered / Notes sections.
- **`notion_sync.get_page(page_id)`** — fetches a single page and
  flattens Notion's verbose shape into an edit-friendly dict.
- **`notion_sync.update_page(page_id, edits)`** — PATCHes editable
  fields. Accepts flat dict matching get_page's keys. Selects
  (Status, Sales Stage, Vertical, Opportunity Type, Owner, Stack
  Confidence) and rich-text fields all supported. Sending `""`
  clears the property.
- **`GET /api/lead/<page_id>`** — full record for the drawer.
- **`PATCH /api/lead/<page_id>`** — apply edits. Only changed fields
  are sent (UI diffs against original) so we don't clobber unrelated
  properties.
- Every update writes an audit event (`lead_updated`) with the list
  of changed fields.
- "Open in Notion ↗" link in the drawer header for the cases where
  Notion's UI is needed (rich blocks, comments, etc.).

### Changed
- Pipeline rows are now click-to-open-drawer instead of click-to-open-Notion.
  ICP Score remains read-only in the drawer (it's a computed output).

### Tests
- 136 total (+8). Covers Notion page flattening, property-shape
  construction for updates, clearing selects/rich-text, no-op when
  there are no edits, and the endpoint contract under no-Notion-key.

## [0.5.1] — 2026-05-15

Full MEDDPICC (8 criteria), pasted-notes capture, and AI-driven
extraction so the AE doesn't fill 8 fields by hand.

### Added
- **MEDDPICC expanded to 8 criteria.** Paper Process and Competition
  added to the qualification card. The original 6 (Metrics, Economic
  Buyer, Decision Criteria, Decision Process, Identify Pain, Champion)
  unchanged. All 8 render in the Notion page body; the existing 6
  Notion *columns* still get written — Paper Process and Competition
  ride in the page body only, so no Notion schema change needed.
- **Notes & Transcripts section** in Qualify view (card "4 ·"). Big
  textarea for pasting raw call notes / Gong / Fathom / Otter transcripts.
- **Project Scope section** (card "6 ·"). One-paragraph freeform summary
  of what the engagement actually is. Auto-fillable from notes; different
  from the deep Project Build intake.
- **`POST /api/lead/extract`** — pipes notes through Anthropic
  (claude-haiku-4-5) and returns suggested MEDDPICC fills + project
  scope summary. The endpoint:
  - Requires `ANTHROPIC_API_KEY` env var (503 if absent)
  - Respects "confirmed" MEDDPICC entries (won't overwrite)
  - Returns null for fields it can't ground in the text (no
    hallucination)
- **"✨ Extract MEDDPICC + scope from notes" button** in the Notes card.
  Merges AI suggestions into the current state, upgrading
  "not_started" entries to "in_progress" so the AE knows to review.
- Every extraction writes an audit event (`lead_notes_extracted`).
- Notes + Project Scope both flow to Notion on push as page-body blocks
  (Notes split at paragraph boundaries to respect Notion's per-block
  text limit).

### Changed
- Section numbering in the Qualify view: Notes is now "4 ·", MEDDPICC
  "5 ·", Project Scope "6 ·", Fit Analysis "7 ·", Push to Notion "8 ·".
- `qualify()` payload now includes `notes: ""` and `project_scope: ""`
  fields by default. Existing callers ignore the new keys.

### Notes for the Notion DB
- The MEDDICC Score column still reflects the original 6 criteria only
  (max 18). To reflect all 8, either rename to "MEDDPICC Score" and add
  Paper Process + Competition columns, or accept the current 6-of-8 cap.
  We're not auto-adding properties to your DB without explicit consent.
- Page body now carries all 8 MEDDPICC entries + Project Scope +
  Notes/Transcript as separate sections.

### Tests
- 128 total (+10). New: MEDDPICC 8-key shape, notes/scope page block
  rendering, text chunking, extract endpoint contract under
  no-Anthropic-key conditions.

## [0.5.0] — 2026-05-15

Draft SOW renderer. The fourth and final stage of the v0.4 vision —
button-triggered (never auto-generated), snapshot-based, versioned.

### Added
- **`sow.py`** — `build_snapshot(lead_id)` freezes Apollo + scope + pricing
  into an immutable dict; `render_html(snapshot, version)` emits a
  print-friendly A4-styled HTML page with a built-in "Print / Save as PDF"
  toolbar button.
- **`sow_store.py`** — versioned per-lead storage at
  `cache/sows/<lead_id>/v<n>.json`. Versions auto-increment; snapshots are
  immutable (no overwrite path).
- **SOW endpoints:**
  - `POST /api/sow/<lead_id>` — generate a new version. Returns the
    snapshot, version number, render URL, and json URL.
  - `GET /api/sow/<lead_id>` — list all versions for a lead (newest first).
  - `GET /api/sow/<lead_id>/v<n>.json` — get a specific snapshot.
  - `GET /api/sow/<lead_id>/v<n>.html` — printable HTML rendering.
- **Project Build UI: "Draft SOW" section** —
  - Big button that POSTs to `/api/sow/<lead>`. Disabled while drafting.
  - Confirmation prompt if scope hasn't been validated by delivery yet
    (warns; doesn't block).
  - Versions table below with Open buttons. Clicking Open fetches the HTML
    with auth, converts to a blob URL, and opens in a new tab (keeps the
    token out of browser history).
- Every draft writes an audit event (`sow_drafted`) capturing version
  number, net total, and scope validation status at generation time.

### Design contract for SOWs
- **Manual trigger only.** No auto-generation. AE explicitly clicks
  "Draft SOW" each time.
- **Snapshot in time.** Once a version is saved, changes to scope or
  pricing don't propagate. To refresh, generate a new version.
- **Immutable versions.** Each version is a separate file; the latest
  is the highest integer in the lead's directory.
- **Internal review banner.** If scope isn't `validated` at the time of
  drafting, the rendered SOW includes a red "needs internal review"
  notice at the top.

### SOW template structure
1. Cover (company, version, generated timestamp)
2. Executive Summary
3. Engagement Overview (background, industry, region, revenue, headcount)
4. Scope of Work — per stream, lists only Qualified + Qualifying criteria
   (Unqualified items are surfaced as "open questions for next call")
5. Team & Phases (FTE × phase matrix from pricing)
6. Investment (gross / discount / net + monthly schedule)
7. Assumptions (5-line boilerplate)
8. Out of Scope (4-line boilerplate)
9. Term & Acceptance with dual signature blocks

### Operational notes
- SOW files live on ephemeral storage. Mount a Railway volume at `cache/`
  to keep history across deploys (same fix as audit log + project store +
  criteria store).
- PDF generation uses the browser's print dialog rather than a server-
  side rendering library, so no new dependencies and the AE can preview
  before saving.

### Tests
- 118 total (up from 102). New: 5 store tests, 4 builder tests, 7
  endpoint tests.

## [0.4.1] — 2026-05-15

Editable scope criteria. The qualification framework is no longer a deploy
to change — Ben (or anyone with platform access) can add, edit, remove,
and reorder criteria from the UI directly.

### Added
- **`criteria_store.py`** — JSON-backed criteria library at
  `cache/scope_criteria.json`. Auto-seeds from
  `scope.DEFAULT_CRITERIA_LIBRARY` on first read.
- **Admin endpoints** for the criteria library:
  - `GET    /api/admin/criteria` — full library
  - `POST   /api/admin/criteria/<project_type>` — add or replace criterion
  - `DELETE /api/admin/criteria/<project_type>/<key>` — remove
  - `POST   /api/admin/criteria/<project_type>/reorder` — `{keys: [...]}`
  - `POST   /api/admin/criteria/<project_type>/reset` — restore one stream
  - `POST   /api/admin/criteria/reset_all` — restore every stream
- **Inline UI** in Project Build:
  - Per-criterion ✎ (edit) and × (delete) buttons in each row
  - "+ Add criterion" link per stream
  - "↺ Reset" link per stream
- Every criteria mutation writes an audit event
  (`criteria_upsert` / `criteria_delete` / `criteria_reorder` / `criteria_reset` /
  `criteria_reset_all`).

### Changed
- `scope.criteria_library()` reads from the editable store with
  `DEFAULT_CRITERIA_LIBRARY` as a fallback.
- `scope.update_criterion()` is now create-or-update — appends an answer
  for previously-unknown criteria keys, so library changes after a project
  was bootstrapped don't break subsequent saves.
- Hardcoded `CRITERIA_LIBRARY` in `scope.py` renamed to
  `DEFAULT_CRITERIA_LIBRARY` and kept as the reset baseline.

### Operational notes
- Storage is on the container's ephemeral filesystem. For durable
  retention, mount a Railway volume at `cache/` (same recommendation as
  the audit log + project store).
- The UI uses native browser prompts to capture criterion fields — it's
  intentionally minimal. A proper modal can come later if friction shows
  up in usage.

### Tests
- 102 total (up from 80). New: 11 store tests, 10 admin endpoint tests,
  1 amended test for the new update_criterion semantics.

## [0.4.0] — 2026-05-15

The Project Build stage. Adds scope intake, codified pricing calculator,
and delivery-team validation between Qualify/Pipeline and the (future)
SOW renderer. Live deploy on Railway; Apollo + Notion integrations
confirmed working in production.

### Added
- **`pricing.py`** — full codified version of the Pricing Calculator. Single
  blended USD/hour rate ($200) with per-role FTE varying by phase. Three
  phases: Understand / Execute / Accelerate. Discount rules
  (15% on first half, 0% second half) baked in but overridable.
  Tests reproduce the reference deal's $1,191,360 gross / $1,112,016 net
  exactly, $5,957 hours within 10 of CSV.
- **`scope.py`** — scope intake model:
  - 5 project types: CRM Strategy / CRM Build / CRM Execute / Data work /
    Engineering
  - Criteria library (campaigns, templates, channels, stakeholders, etc.)
    with per-criterion role-driver tags so scope answers feed pricing
  - 3-state qualification status per criterion: Unqualified → Qualifying →
    Qualified
  - Validation state machine: `draft → pending_validation → validated /
    rejected`, with bounce-back to draft on rejection
  - Discovery questions library (Situation / Pain / Trap)
  - Anticipated objections library with prepared responses
  - Reference points library (Yum, RBI, IHG, Just Eat, Monzo, GoPuff +
    tech partners)
- **`project_store.py`** — JSON-file-per-lead persistence at
  `cache/projects/<lead_id>.json`. Stable lead IDs via filesystem slug.
- **`/api/scope/library`** — read-only metadata bundle for the UI
  (project types, criteria, discovery questions, objections, references,
  team templates, role catalogue)
- **`/api/scope/<lead_id>`** GET/POST/PUT — read or upsert a project scope
- **`/api/scope/<lead_id>/transition`** POST — walk the validation state
  machine. Delivery team uses this to validate/reject.
- **`/api/scope/projects`** GET — list all projects + filter by pending
  validation status
- **`/api/pricing/preview`** POST — compute a quote from either a stored
  lead's scope (with role multipliers from criteria) or raw inputs
- **Project Build UI** — new tab in `qualify.html`. Multi-select project
  streams, per-stream criteria panels (matching the existing MEDDPICC
  visual language), pricing preview card with Chart.js monthly breakdown,
  validation banner with Validate / Reject / Reopen actions, and a
  collapsible "sales toolkit" surfacing discovery questions, objections,
  and references.
- Every scope save + transition writes an audit event.

### Changed
- **MEDDICC → MEDDPICC** labels in the UI heading and Notion page-body
  section heading. Internal field names (`meddicc` payload key, Notion
  property names) stay MEDDICC to avoid breaking the existing tracker.
  This is option 2 — label-only rename, no new criteria. If you want the
  full 8-criteria framework (adding Paper Process + Competition), that's
  a follow-up that needs Notion schema additions.

### Operational notes
- Project files live in container-ephemeral storage (`cache/projects/`).
  For durable retention across deploys, mount a Railway volume at
  `cache/` (or set `PROJECT_STORE_DIR` to a mounted path).
- Pricing calc is the *client-facing* rate book (single $200/h blended).
  Internal margin accounting uses different per-role rates not captured
  here — when finance shares them we add a margin view.
- Delivery validation is gate-only — there's no Slack notification yet
  when scope hits `pending_validation`. Delivery team checks the Pipeline
  view filter "Active only" then filters by `validation_status` (TODO:
  surface filter chip).

### Test coverage
- 80 tests total. New in v0.4: pricing math (14), scope model + state
  machine + storage (15), scope endpoints (9).
- Reference deal calibration: gross matches CSV exactly, net within 1%,
  hours within 10.

## [0.3.0] — 2026-05-13

The "ready for the team to actually use" release. Roadmap phases v0.3
(HubSpot — scaffolded but off) and v0.5 (audit + Slack digest) ship in
this version. Plus pre-deploy diagnostics and a post-deploy smoke test.

### Added
- **Append-only audit log** (`audit.py`, `cache/audit.jsonl`). Every
  qualify / notion-sync / hubspot-sync / digest-send writes one JSON line
  with timestamp, actor (from `X-Actor` header), company, and outcome. New
  `GET /api/audit?limit=100` endpoint returns recent events + a roll-up
  summary.
- **Slack weekly digest** (`slack_digest.py`). Block Kit payload combining
  pipeline top-5 by ICP + recent qualification stats from the audit log.
  Gated by `SLACK_WEBHOOK_URL`; `GET /api/slack/digest` previews,
  `POST /api/slack/digest?send=1` posts.
- **HubSpot write-back scaffolding** (`hubspot_sync.py`). v0.3 roadmap item.
  **Disabled by default** per the product brief (awaiting CEO approval).
  Activation requires both `HUBSPOT_API_KEY` and `HUBSPOT_SYNC_ENABLED=1`.
  Live calls degrade gracefully if MR-custom HubSpot properties are absent.
  `POST /api/hubspot/sync` returns 503 with `code: hubspot_disabled` until
  flipped on.
- **Pipeline CSV export** — `GET /api/pipeline/export.csv` plus a download
  button in the Pipeline view. Honours auth via blob fetch.
- **Diagnostics CLI** — `python -m diagnostics` runs end-to-end env +
  Apollo + Notion connectivity checks. `--strict` exits non-zero on any
  REQUIRED failure, suitable for pre-deploy hooks.
- **Smoke test script** — `scripts/smoke.sh` hits a running deployment with
  curl (health, HTML, qualify, pipeline, HubSpot probe). Tolerant of Notion
  unconfigured + HubSpot disabled states.
- `/api/health` now reports `ai`, `slack`, and `hubspot` blocks alongside
  `apollo` and `notion`, so the UI surface knows what's available.

### Changed
- `server.py` `/` now serves `qualify.html` from an in-memory string read
  once at startup, replacing `send_from_directory`. Eliminates the
  test-runner `ResourceWarning` and removes a per-request disk read.
- `qualify.html` Pipeline view header gained Export CSV alongside Refresh.

### Fixed
- `set -u` quoting in `scripts/smoke.sh` when `AUTH_HEADER` is empty.

### Operational notes
- The CEO-pending HubSpot integration is fully wired and unit-tested as
  disabled. Re-enable by setting two env vars and redeploying — no code
  change required.
- The audit log is local to the container's ephemeral filesystem. For
  durable retention, mount a Railway volume at `cache/` (or set
  `AUDIT_LOG_PATH` to a mounted path).

## [0.2.1] — 2026-05-13

Ship-readiness hardening on top of v0.2.0. No schema changes required in
Notion.

### Added
- **Shared-secret auth** via `APP_AUTH_TOKEN`. When set, all `/api/*` calls
  require `Authorization: Bearer <token>`. `/api/health` and `/` stay open so
  the UI can negotiate auth. UI prompts the user on first load, stores the
  token in `localStorage`, retries automatically on 401, exposes a sign-out
  link in the header.
- **Sales Stage selector** in the Push-to-Notion card (Intro Call → Signature).
  Maps to the existing Notion "Sales Stage" select on push. Empty value
  leaves the property untouched.
- **Owner picker** alongside Stage. Defaults to "Ben Ojuolape".
- **MEDDICC notes preservation.** The AE's text per criterion is rendered
  into a timestamped section on the Notion page body (`MEDDICC Notes —
  YYYY-MM-DD HH:MM UTC`). On update, a fresh section is appended via the
  blocks/children API, giving an audit trail of MEDDICC progress.
- **AI-assisted fit summary** via `ai_summary.py`. Uses Claude Haiku 4.5
  when `ANTHROPIC_API_KEY` is set; otherwise falls back silently to the
  heuristic. New `fit_summary_source` field ("ai" | "heuristic") surfaced
  as a small badge in the UI.
- **Seeded-accounts calibration test** (`tests/test_seeded_accounts.py`).
  One test per account (Yum, RBI, IHG, Just Eat, Monzo, GoPuff, Murphy USA)
  asserting status band + score within ±0.5 of the engine's current output.
  Catches accidental tier-weight drift.
- **Server endpoint + auth integration tests** (`tests/test_server.py`).
  Verifies `/api/health` stays open, `/api/qualify` is gated when
  `APP_AUTH_TOKEN` is set, bearer match is hmac-safe.
- `ai.configured` flag added to `/api/health` response.

### Changed
- `/api/health` now includes `auth.required` and `ai.configured` blocks so
  the UI can render integration status without separate calls.
- `qualify_service.qualify()` now returns `fit_summary_source` alongside
  `fit_summary`.

### Fixed
- MEDDICC notes were previously written only as numeric scores and the
  free-text capture in the UI was lost on Notion push. Now preserved as
  page-body blocks.

## [0.2.0] — 2026-05-13

The "team-facing platform" rebuild. Old single-user CLI/HubSpot workflow is
retired; new web app is hosted on Railway and used directly by AEs and
Partner Managers.

### Added
- **Apollo.io enrichment** via `apollo.py` — REST client with 24h file-based
  cache, fixture fallback (`APOLLO_USE_FIXTURES=1`), and normalised output
  shape consumed everywhere downstream.
- **End-to-end orchestrator** `qualify_service.qualify(name, url, overrides)`
  — single entrypoint Flask calls. Owns Apollo → ICP shape → score → signals
  → fit summary → stakeholder discovery.
- **Stakeholder discovery** through Apollo `mixed_people/search`, defaulting
  to CMO / VP CRM / Head of Lifecycle / Director Marketing seniorities.
- **Notion data-source-aware sync** — `notion_sync.NotionSync` talks to the
  2025-09 Notion REST API directly (`data_source_id` parent), so multi-source
  databases are supported and we don't depend on `notion-client` version drift.
- **Pipeline view** in the UI — sortable, filterable table reading from
  `/api/pipeline` (Notion-backed source of truth).
- **MEDDICC tracker** — six criteria with per-criterion notes and a
  Not-Started / In-Progress / Confirmed status toggle. Scores roll into the
  Notion "MEDDICC Score" field on push.
- **Editable auto-discovered fields** — every tile (revenue, employees,
  vertical, tech stack, complexity, region, incumbent agency) is click-to-edit
  with an AUTO / MANUAL badge and a green pulse on first populate.
- **Health endpoint** `/api/health` exposing Apollo + Notion config status
  (used by Railway healthcheck and the UI header).
- **Railway deploy config** — `Dockerfile`, `Procfile`, `railway.json`.
- **End-to-end smoke tests** at `tests/test_qualify_e2e.py` — Deliveroo
  fixture, override propagation, stub mode, Notion property mapping.
- `PRD.md` documenting the product brief, users, success metrics, and roadmap.

### Changed
- **Folder renamed** `tools/` → `lead-qualification-platform/` to match the
  GitHub repo name. Git remote unchanged.
- `server.py` rewritten — HubSpot endpoints removed in favour of
  `/api/qualify`, `/api/notion/sync`, `/api/pipeline`. The HubSpot Flask app
  is preserved verbatim at `legacy_hubspot.py`.
- `notion_sync.py` rewritten to target the new "Lead Qualification Tracker"
  data source (`31051ecc-2410-4a71-b885-f21c8dd52ba3`) inside Growth &
  Partnerships Command Centre. Old DB ID `6552dcec…0f60` retired.
- `qualify.html` rebuilt from scratch — dark theme (`#0a0a0f`), MR accent
  (`#ff4d2a`), two top-level views (Qualify / Pipeline), Chart.js bar
  breakdown, single-file vanilla JS + CSS.
- `.env.example` updated with the new variable set
  (`APOLLO_API_KEY`, `NOTION_DATA_SOURCE_ID`, `APOLLO_USE_FIXTURES`).

### Removed
- HubSpot enrichment from the live server (parked in `legacy_hubspot.py`;
  will return once the CEO greenlights HubSpot integration).
- Static report HTML output (`report_*.html`) — replaced by the persistent
  Notion page generated on push.

### Migration notes
- The folder rename does not affect the git remote. To pick up the new path
  locally: `cd "Massive Rocket/lead-qualification-platform"`.
- Existing leads in the *old* Notion DB (`6552dcec…0f60`) are not migrated.
  The seven seeded accounts already live in the new tracker.

---

## [0.1.1] — 2026-04-10

### Changed
- Reverted exploratory static-serving routes from `research_server.py`;
  `server.py` remains the single Flask entry point serving `qualify.html`
  at `http://localhost:5050/`.

### Fixed
- Documented missing `notion-client` dependency needed to run `server.py`
  locally. (Subsequently removed entirely in 0.2.0 in favour of direct
  REST calls.)

## [0.1.0] — 2026-04-07

### Added
- Initial scoring engine (`scoring.py`) and ICP configuration (`config.py`).
- HubSpot-backed Flask server.
- First Notion sync targeting the legacy database.
- CLI `qualify_lead.py` and `auto_qualify.py` for one-off scoring.
