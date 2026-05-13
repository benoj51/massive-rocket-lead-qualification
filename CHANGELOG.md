# Changelog

All notable changes to the Massive Rocket Lead Qualification Platform.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
