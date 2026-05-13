# Massive Rocket — Lead Qualification Platform

Team-facing web app that scores companies against MR's ICP, enriches them via
Apollo, and writes the result to the Lead Qualification Tracker in Notion.

**Location:** `Massive Rocket/lead-qualification-platform/`
**GitHub:** [`benoj51/massive-rocket-lead-qualification`](https://github.com/benoj51/massive-rocket-lead-qualification)
**See also:** [PRD.md](PRD.md) · [CHANGELOG.md](CHANGELOG.md)

## What's in this repo

| File | Purpose |
| ---- | ------- |
| `qualify.html` | Single-page UI (vanilla JS + Chart.js). Two views: Qualify Lead + Pipeline. |
| `server.py` | Flask backend. Serves the UI and the JSON API. |
| `apollo.py` | Apollo REST client. File-cached (24h TTL); fixture fallback when no key. |
| `qualify_service.py` | Orchestrator: Apollo → ICP shape → scoring → signals → fit summary → stakeholders. |
| `notion_sync.py` | Direct Notion REST client (2025-09 data-source-aware API). Upsert + pipeline listing. |
| `scoring.py` | ICP scoring engine. 51-point weighted, normalised to 10. |
| `config.py` | ICP criteria, weights, vertical tiers, disqualifiers. |
| `legacy_hubspot.py` | The old HubSpot-backed Flask server, parked until the CEO greenlights HubSpot integration. |
| `tests/` | End-to-end smoke tests against the Apollo fixture. |

## Required environment variables

Set in Railway → Project → Variables (or in a local `.env` from `.env.example`).

| Var | Purpose |
| --- | ------- |
| `APOLLO_API_KEY` | Apollo REST key. Apollo admin → Settings → Integrations → API. |
| `NOTION_API_KEY` | Notion internal integration secret. Share the tracker DB with the integration. |
| `NOTION_DATA_SOURCE_ID` | Default: `31051ecc-2410-4a71-b885-f21c8dd52ba3` (Lead Qualification Tracker). |
| `APOLLO_USE_FIXTURES` | Set `1` to bypass Apollo (uses `tests/fixtures/apollo/*.json`). Leave unset in prod. |
| `FLASK_SECRET_KEY` | Any random string. |
| `PORT` | Railway sets this automatically. |

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in keys
python server.py       # http://localhost:5050
```

To run without Apollo (uses Deliveroo fixture):

```bash
APOLLO_USE_FIXTURES=1 python server.py
```

## Tests

```bash
APOLLO_USE_FIXTURES=1 python -m unittest discover tests -v
```

39 tests across:
- Orchestrator + Apollo fixtures + Notion property mapping
- Auth middleware (open / gated)
- Seeded account scoring calibration (7 accounts)
- Audit log
- Slack digest builder
- HubSpot scaffolding (disabled by default)

The Deliveroo fixture should land as QUALIFY IN / Retention with the right
signals; overrides flow through the scorer.

## Pre-deploy diagnostics

```bash
python -m diagnostics            # human-readable
python -m diagnostics --json     # machine-readable
python -m diagnostics --strict   # exit 1 if any REQUIRED check fails
```

## Post-deploy smoke test

Hits a running deployment with curl. Read-only — won't touch Notion data.

```bash
BASE_URL=https://your-app.up.railway.app TOKEN=... scripts/smoke.sh
```

## Deploy to Railway — runbook

1. **Push to GitHub.** `git push -u origin feat/qualification-platform-v2`, open PR, merge to `main`.
2. **Create Railway project.** Dashboard → New Project → Deploy from GitHub → pick `benoj51/massive-rocket-lead-qualification`.
3. **Set environment variables** (Project → Variables):
   - `APOLLO_API_KEY` — Apollo admin → Settings → Integrations → API
   - `NOTION_API_KEY` — Notion → My Integrations
   - `NOTION_DATA_SOURCE_ID` — `31051ecc-2410-4a71-b885-f21c8dd52ba3`
   - `APP_AUTH_TOKEN` — `python -c 'import secrets; print(secrets.token_urlsafe(24))'`. Share with the team via 1Password or Slack DM.
   - `ANTHROPIC_API_KEY` — optional, enables AI fit summaries.
   - `SLACK_WEBHOOK_URL` — optional, enables `/api/slack/digest` posting.
4. **Wait for build.** Railway picks up the Dockerfile + `railway.json`. Healthcheck hits `/api/health`.
5. **Smoke test.**
   ```bash
   BASE_URL=https://your-app.up.railway.app TOKEN=$APP_AUTH_TOKEN scripts/smoke.sh
   ```
6. **First real qualification.** Open the URL, paste the token, click "Demo: Deliveroo", verify the score + Notion push.
7. **(Custom domain.)** Project → Settings → Domains.

### Activating HubSpot (post-CEO approval)

Default state: `/api/hubspot/sync` returns 503 with `code: hubspot_disabled`.

To turn it on:
1. Create the custom company properties in HubSpot (or skip — the sync gracefully
   degrades to standard fields only):
   - `mr_icp_score` (number)
   - `mr_icp_status` (single-line text)
   - `mr_opportunity_type` (single-line text)
   - `mr_fit_summary` (multi-line text)
   - `mr_last_qualified` (date)
2. Set Railway vars: `HUBSPOT_API_KEY=<private-app-token>` and `HUBSPOT_SYNC_ENABLED=1`.
3. Redeploy. `/api/health → hubspot.enabled` flips to `true`.
4. Re-run `scripts/smoke.sh` — step 5 will now report "HubSpot live writes succeeded".

### Slack digest

`GET /api/slack/digest` returns the rendered Block Kit payload for preview.
`POST /api/slack/digest?send=1` posts to `SLACK_WEBHOOK_URL`. Schedule it via
Railway Cron or any external scheduler against the POST endpoint.

## Endpoints

All `/api/*` endpoints require `Authorization: Bearer <APP_AUTH_TOKEN>` when
the env var is set. `/` and `/api/health` are always open so the UI can
negotiate auth.

| Method | Path | Body | Returns |
| ------ | ---- | ---- | ------- |
| GET    | `/` | — | `qualify.html` |
| GET    | `/api/health` | — | Apollo + Notion + AI + Slack + HubSpot config status |
| POST   | `/api/qualify` | `{name, url, overrides?}` | Full qualification payload (see below) |
| POST   | `/api/notion/sync` | The payload from `/api/qualify` (with MEDDICC edits, sales_stage, owner) | `{action: created\|updated, page_id, url}` |
| GET    | `/api/pipeline?limit=100` | — | `{rows: [...], count}` from the tracker |
| GET    | `/api/pipeline/export.csv?limit=500` | — | CSV download of pipeline rows |
| POST   | `/api/hubspot/sync` | The payload from `/api/qualify` | `{action, company_id, url}` (or 503 if disabled) |
| GET    | `/api/audit?limit=100&since=ISO8601` | — | Recent audit events + roll-up summary |
| GET    | `/api/slack/digest` | — | Preview the digest payload, no Slack call |
| POST   | `/api/slack/digest?send=1` | — | Post the digest to Slack |

### `/api/qualify` payload shape

```jsonc
{
  "company":    { "name": "...", "url": "...", "apollo": { /* normalised Apollo org */ } },
  "discovered": { "revenue": "$2.4B", "employees": 4200, "vertical": "...", "tech_stack": "...", "...": "..." },
  "score":      { "normalized_score": 9.4, "status": "qualify_in", "status_display": "QUALIFY IN",
                  "total_weighted": 48, "max_weighted": 51, "opportunity_type": "retention",
                  "opportunity_label": "Retention", "breakdown": { "...per-criterion...": {} } },
  "signals":     ["Braze + Snowflake already in stack (confirmed)"],
  "disqualifiers": [],
  "fit_summary": "...",
  "next_steps":  ["...", "..."],
  "opportunity": { "type": "retention", "label": "Retention", "description": "...", "play": "..." },
  "stakeholders":[ { "name": "", "title": "", "priority": "", "why": "", "linkedin_url": "" } ],
  "meddicc":     { "metrics": {"value": "", "status": "not_started"} }
}
```

## Roadmap

- HubSpot deal sync (post-CEO sign-off). The legacy Flask app at
  `legacy_hubspot.py` already has the enrichment plumbing; wire its
  `hs_search_company` into `qualify_service` and add a `/api/hubspot/sync`
  endpoint that mirrors `/api/notion/sync`.
- AI-assisted fit summaries: swap the heuristic in
  `qualify_service._generate_fit_summary` for an Anthropic call using
  `ANTHROPIC_API_KEY` when present.
- Audit log: log every qualification + push to a lightweight events file
  (or Postgres) so we can answer "who qualified what when".
