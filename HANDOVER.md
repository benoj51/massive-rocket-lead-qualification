# Handover brief - Lead Qualification Platform

**For:** a fresh Claude / Claude Code session picking this project up on the
Massive Rocket corporate licence, with none of the prior session's memory.
**As of:** v1.0.0du, 2026-05-29.
**Owner:** Ben Ojuolape (Head of Partnerships + AE management, Massive Rocket).

If you are that new session: read this file, then [PRD.md](PRD.md) for what the
product is, then the top of [CHANGELOG.md](CHANGELOG.md) for the most recent
work. That is enough to start contributing safely.

---

## 1. What this project is, in one paragraph

A team-facing Flask + vanilla-JS single-page app that scores companies against
Massive Rocket's ICP, enriches them via Apollo, and runs the whole pre-sale
motion (discovery notes, MEDDPICC, contacts, scope, pricing, draft SOW) on top
of Notion as the system of record. It has grown to 76 Python modules, ~180 API
routes, and 1331 passing tests. Claude is used throughout for summarising,
qualifying, coaching, and drafting. Deployed on Railway. See PRD.md section 6
for the full capability list and section 10 for architecture.

## 2. Why this handover exists (the licence move)

Development has been happening on Ben's personal Claude licence, where a lot of
context lived outside the repo: a personal `CLAUDE.md`, auto-memory, custom
skills, and `~/.claude` settings. Moving to the corporate licence means a fresh
agent will **not** inherit any of that. This document encodes everything that
context used to carry, so nothing is lost in the move.

**Things to re-establish on the corporate side:**

- API keys under corporate accounts: `APOLLO_API_KEY`, `NOTION_API_KEY`,
  `ANTHROPIC_API_KEY`, optionally `SLACK_WEBHOOK_URL`, and the use-cases
  `DATABASE_URL_USECASES`. Set them in Railway, never in the repo or in chat.
- Confirm Railway project ownership / access for the corporate team.
- Confirm the git push policy (section 7). This is the single most important
  thing to get right on day one.

## 3. Repo orientation

- `server.py` - Flask backend, ~180 routes. Reads `qualify.html` into memory
  **once at boot**, so UI edits do not appear in a running server until you
  restart it.
- `qualify.html` - the entire SPA (~18k lines): markup, CSS, and JS in one file.
- `qualify_service.py` - the qualify orchestrator (Apollo -> ICP -> scoring ->
  signals -> fit summary -> stakeholders).
- `apollo.py`, `notion_sync.py`, `scoring.py`, `config.py` - integrations + the
  scoring rubric.
- `ai_summary.py`, `agent.py`, `mr_tools.py`, `mr_mcp_server.py` - Claude
  synthesis + the tool-using agent + MCP server.
- `*_store.py` (many) - JSON file stores under `cache/`, one per concern
  (calls, contacts, partners, live projects, todos, expansion, etc.).
- `tests/` - one test module per concern; `python3 -m pytest` runs all 1331.
- `README.md` (run + deploy), `SETUP.md` (stale, ignore the legacy
  `index.html`/`app.js` parts), `RAILWAY_VOLUME_MOUNT.md` (persistence).

For the env var inventory, see README.md plus the `*_STORE_DIR` family used by
the file stores. ~60 env vars total; almost all have sensible defaults.

## 4. How to run and test

```bash
pip install -r requirements.txt
# Run without external keys (uses the Deliveroo Apollo fixture):
APOLLO_USE_FIXTURES=1 python server.py        # http://localhost:5050

# Full test suite (note: python3, and pytest, not unittest in practice):
python3 -m pytest -q

# Pre-deploy diagnostics:
python3 -m diagnostics --strict
```

Checking the SPA's JavaScript after editing `qualify.html`: extract the script
blocks and run `node --check`. Beware the Chart.js `<script ...></script>` tag
near the top, whose literal `</script>` breaks naive line-boundary math. Use
explicit, verified line numbers when slicing.

## 5. The per-increment workflow (follow this every time)

Ben works in small, shippable increments. Each one:

1. Bump the version in the `<title>` of `qualify.html` (sequence is
   `v1.0.0...dt`, `du`, `dv`, ...).
2. Add a CHANGELOG.md entry at the top, in the existing style (version, date,
   short title, what changed, tests).
3. Add or extend tests for the change.
4. Run the full suite (`python3 -m pytest`), confirm green.
5. Commit. **Do not push unless Ben asks.**

Commits use a `Co-Authored-By: Claude ...` trailer. Do not amend previous
commits; always create a new one. Stage specific files, not `git add -A`.

## 6. House rules / conventions (these are firm)

- **No em-dashes** in user-facing prose or AI-generated text. UK English
  spelling (optimise, prioritise, programme, organisation, behaviour). No
  marketing tone, no emojis, no invented statistics.
- **Outreach is drafts-only.** Never auto-send email / LinkedIn / Slack.
- **Never hallucinate stats** in AI output.
- **`cache/` is gitignored** and must never be committed.
- **Never paste live secrets into chat,** especially the company `DATABASE_URL`.
  The use-cases DB is wired via `DATABASE_URL_USECASES` set in Railway.
- **Do not commit** `.claude/launch.json`, `.coverage`, or the
  `CW-Massive Rocket - Value Proposition & Messaging-*.pdf` that sits untracked
  in the repo root.

## 7. Git remotes and push policy (read before pushing anything)

Two HTTPS remotes:

- `origin` -> `github.com/benoj51/massive-rocket-lead-qualification` (Ben's
  personal fork).
- `company` -> `github.com/Massive-Rocket/massive-rocket-lead-qualification`
  (the Massive Rocket org repo).

Under the personal-licence workflow, the standing rule was: **push only to
`origin` (the personal fork), never to `company`.** The move to the corporate
licence is exactly the moment that policy may change. **Confirm with Ben which
remote is now the source of truth and who approves writes before pushing to
`company`.** Do not assume.

Current branch state at handover: `main`, **2 commits ahead of `origin/main`**
and unpushed (v1.0.0dt and v1.0.0du). Ask before pushing them.

## 8. Deployment (Railway)

- Dockerfile build, declared in `railway.json` (healthcheck `/api/health`,
  restart on failure).
- `Procfile`: `gunicorn server:app --workers 2 --timeout 120`.
- Set env vars in Railway -> Variables. JSON stores want a mounted volume so
  they survive redeploys (see `RAILWAY_VOLUME_MOUNT.md`).
- Post-deploy smoke test: `BASE_URL=... TOKEN=... scripts/smoke.sh`.

## 9. Current state and recent context

- **v1.0.0du** (latest): `apollo._resolve_person_name` now recovers a masked
  surname from the LinkedIn slug when Apollo returns only a first name, so the
  stakeholders table shows "Kirstey Mcleod" rather than "Kirstey". Strictly
  first-surname shaped, never fabricated. 7 new tests in
  `test_apollo_name_resolution.py`.
- **v1.0.0dt**: the opportunity-top AI summary gained a qualification RAG verdict
  (green/amber/red + rationale) and 2-4 AE coaching points, folded in from a
  "Discovery Gem" sales-brief prompt. Schema lives in
  `ai_summary._LEAD_SUMMARY_SYSTEM_PROMPT`; rendered by `renderAiLeadSummary` in
  qualify.html; also flows to Notion (`_format_summary_for_notion`) and the copy
  helper.
- **v1.0.0ds / dr**: Partners blurb wording (mParticle stays a partner; the
  example line names Hightouch) and the "Crisp Enterprise" light theme.
- Tests: 1331 passing. Full history in CHANGELOG.md (9000+ lines).

## 10. Known stale docs and loose ends

- `SETUP.md` describes the original `index.html` + `app.js` + localhost:5000
  flow. The real app is `server.py` + `qualify.html` on :5050. Refresh when
  convenient.
- The Obsidian note `brain/work/wiki/lead-qualification-tooling.md` describes the
  legacy `tools/` scripts, not this platform. The companion note
  `lead-qualification-platform-handover.md` (this brief, mirrored into the vault)
  is the current reference.
- `qualify_service._stakeholder_why` still emits em-dashes; bring it in line with
  the no-em-dash rule (good first task).
- PRD section 13 lists the live roadmap items.

## 11. Good first tasks for a new session

1. Push the 2 unpushed commits once the push policy (section 7) is confirmed.
2. Strip em-dashes from `_stakeholder_why` (matches the house rule, has a clear
   blast radius, exercises the full workflow in section 5).
3. Refresh `SETUP.md` to the current run model.

When in doubt, match the patterns already in the codebase, keep the increment
small, and ship it with tests and a CHANGELOG entry.
