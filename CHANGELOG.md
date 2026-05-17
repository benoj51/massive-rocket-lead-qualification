# Changelog

All notable changes to the Massive Rocket Lead Qualification Platform.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.10.0c] — 2026-05-17 — Account Groups (Phase C): grouped pipeline view

The Pipeline view now has a **Flat / Grouped** toggle and a **Group**
filter dropdown. Grouped mode shows parents at the top with a "Group · N"
badge; clicking the caret expands to reveal child brands indented under
their parent. Filter by group to see "everything under Yum! Brands"
including the parent itself.

### Added
- **Pipeline Group filter** (`#pipe-filter-group`) — populated from
  the parents currently in pipeline. Selecting "Yum! Brands" filters
  to the parent + every child brand under it.
- **Flat / Grouped view-mode toggle.** Flat shows every account as a
  row (original behaviour); Grouped buckets parents at the top with
  children indented under them.
- **Group badges in the table:**
  - Parents show "Group · N" (N = number of brands) with a clickable
    expand caret in grouped mode.
  - In flat mode parents get a quieter "Group" tag next to the name.
  - Children show a `↳` indent prefix in grouped mode.
- **Per-group expand/collapse state** persisted in `state.pipeline
  .expandedGroups` (a `Set`). Survives filter changes within a session.
- **Constrained the status-chip handler** to chips that have a
  `data-filter` attribute so the new view-mode chips don't trigger it
  (would have set `state.pipeline.filter = undefined`).

### Notes
- Group-level TCV rollup (sum of project values across all brands in
  the group) is on the backlog. The current parent row shows the
  parent's own ICP/stage/owner — useful when the parent is a real
  lead, less useful when it's purely a label.
- Orphan children (whose parent isn't in the filtered view) fall
  through to a flat row below the parents so they're never silently
  hidden.

### Tests
- 276 total. No new Python tests — view-mode is UI-only. JS sanity
  check (full inline parse) green.

## [0.10.0b] — 2026-05-17 — Account Groups (Phase B): Apollo auto-detect

When you qualify KFC, the platform now reads Apollo's enrichment and
the company description, then surfaces a banner: *"Looks like this
account is part of Yum! Brands."* The AE clicks Accept (one-click link
to the parent, creating it if needed) or Override / Dismiss.

### Added
- **`parent_detector.py`** — combines two signals:
  - Apollo's structured `parent_organization_*` / `parent_account_*`
    fields (high confidence when present — rare in practice).
  - Pattern matching on `short_description` for established M&A
    phrasing: "subsidiary of X", "owned by X", "operating company of
    X", "acquired by X" (medium confidence) and "part of the X
    family", "brand of X", "division of X" (low confidence).
  - Returns `{source, name, confidence, matched_phrase}` or `None`.
- **`qualify_service.qualify()` now returns `suggested_parent`** in
  the response payload (or `None` for standalone accounts).
- **Suggestion banner in the qualify result** (between auto-discovery
  header and tiles). Renders only when a candidate exists. Shows the
  confidence pill, the source, and the matched phrase for trust.
  Three actions:
  - **Accept** — if the candidate is already in pipeline, one-click
    link. Otherwise creates the parent on save and links.
  - **Override** — dismisses the banner; AE uses the drawer picker.
  - **Dismiss** — hides the banner for this session.
- **Pending-link queue** — if the AE accepts a suggestion before the
  lead is saved to Notion, the link auto-fires after the Notion save
  completes.

### Detector details (regex hygiene)
- Name capture is case-sensitive (`[A-Z\d]`) on purpose — without it,
  `re.IGNORECASE` would let the regex eat trailing lowercase words
  like "since 2020" or "focused on cloud services".
- Trailing legal-suffix stripping is narrow: only strips a `, Inc.`
  / `, LLC` style suffix after a comma. "Yum! **Brands**", "Restaurant
  **Brands** International", "Berkshire Hathaway **Holdings**" are
  preserved because those tokens are part of the real name.
- Generic-noun guard: rejects matches that start with "the", "a",
  "global", "leading" etc. so "part of the global ecommerce industry"
  doesn't false-positive.

### Tests
- 276 total (+19). `test_parent_detector.py` covers: subsidiary/owned-by/
  operating-company-of/acquired-by (medium), part-of-family/brand-of/
  division-of (low), Apollo flat + nested + domain-fallback fields,
  empty inputs, generic-noun rejection, Apollo-beats-description
  precedence.

## [0.10.0a] — 2026-05-17 — Account Groups (Phase A)

Models the parent-brand relationship for B2B realities like Yum! Brands
→ KFC, Pizza Hut, Taco Bell, Habit Burger. Phase A is manual linking
+ drawer UX; Phases B–D (Apollo auto-detect, grouped pipeline view,
AI sibling context) land in 0.10.0b/c/d.

### Added
- **`accounts_graph.py`** — single-file JSON store at
  `cache/accounts_graph.json` mapping `{child_slug: parent_slug}`.
  One level deep on purpose; multi-level (Corp → Division → Brand) is
  deferred. Includes cycle detection, self-ref block, one-level rule
  (a parent with children cannot itself become a child).
- **Server endpoints:**
  - `GET /api/accounts/graph` — full map.
  - `PUT /api/lead/<id>/parent` — set or clear parent (body
    `{parent_account_id: "..."}` or `null`). Returns 400 on graph
    violations.
  - `GET /api/lead/<id>/children` — children enriched with pipeline
    metadata (ICP score, status, vertical).
- **`GET /api/lead/<id>` enriched** with a `group` block:
  `{parent: {id, company, icp_normalised, status} | null,
    children: [...]}`. Resolves slugs → display names from the
  pipeline so the drawer renders names not slugs.
- **`GET /api/pipeline` rows annotated** with `parent_account_id`
  and `is_parent` flags so the UI can render grouped/flat views
  without an extra round-trip (Phase C will use these).
- **Drawer UX:**
  - "Parent group" picker at the top of the Identity section
    (typeahead over the pipeline + create-on-the-fly path).
  - Header chip *"Part of: <Parent> →"* on child leads, clickable
    to open the parent's drawer.
  - "Brands in this group (N)" panel on parent leads, listing each
    child with ICP score + status, clickable.
  - "× Unlink" button when a parent is set.
  - Inline error display for graph violations (self-ref / one-level).
- Audit log captures `account_parent_set` / `account_parent_cleared`.

### Out of scope for Phase A
- Apollo auto-suggestion of parent (Phase B).
- Grouped pipeline view + group filter chips (Phase C).
- AI sibling context in lead summaries + portfolio summary (Phase D).
- Notion column sync. The graph lives in `cache/` only for now —
  durable until Railway redeploys without a volume mount. Mirror to
  Notion is on the backlog.
- Lead-account delete guard. There's no current "delete lead"
  endpoint to guard; the locked-in policy is enforced once that
  surface exists.

### Tests
- 257 total (+12). `test_accounts_graph.py` covers: empty graph,
  set/read/unlink, children-of, slug normalisation, self-ref block,
  one-level rule, persistence across process restart, can-delete guard.

## [0.9.4] — 2026-05-17

Hotfix: `✨ Refresh` returned 500 if a saved call had `extracted=None`.
Triggered in prod when a long transcript made Claude's JSON output
truncate mid-string (`Unterminated string starting at: line 29
column 23`); the call still saved with raw transcript only, but
`extracted` was stored as `None` rather than `{}`. The next refresh
crashed at `c.get("extracted", {}).get("meddpicc")` because
`dict.get(key, default)` returns the stored `None`, not the default,
when the key is present.

### Fixed
- **`_gather_lead_context` (server.py:731)** — `(c.get("extracted")
  or {}).get(...)` now safely handles both missing and explicit-None.
- **`suggest_roadmap` (ai_summary.py:190)** — same pattern.
- **`suggest_extended_engagement` (ai_summary.py:327)** — same pattern.

### Changed
- **`extract_from_notes` `max_tokens` 900 → 1800.** The original cap
  was tight enough that a longer transcript producing a full
  synthesised note + 8 MEDDPICC fields + project scope would
  truncate. Marginal token cost (~$0.005/call vs $0.003), much higher
  success rate on real call transcripts.

### Tests
- 245 total (+1). New regression
  `GatherLeadContextNoneExtractedTests.test_gather_context_handles_none_extracted`
  writes a call with `extracted=None` directly through `calls_store`
  and asserts `_gather_lead_context` no longer raises.

## [0.9.3] — 2026-05-17

UX clarity for the AI-off state. Triggered by Ben reporting "only see
the raw transcript" after pasting a call note — the underlying cause
was `ANTHROPIC_API_KEY` not being set in Railway, so Claude was silently
skipped and the synthesised-note slot looked broken.

### Added
- **AI status pill in the header bar** (`AI on` / `AI off`) sourced
  from `/api/health` and stashed in `state.healthCache`. New
  `aiIsOn()` helper drives every downstream message.
- **AI-off banner above the calls list** when `ANTHROPIC_API_KEY` is
  missing — yellow box with explicit instruction to add the variable
  in Railway → Variables.
- **AI-off banner on the empty Calls section** (before the first call
  is saved) so the AE sees the state before pasting anything.
- **Inline empty-state in the "Synthesised note" slot** when the call
  has no AE-edited note and no AI extraction:
  - If AI is off: "No synthesised note — AI is off. Click ✎ Edit
    note to write one manually, or set ANTHROPIC_API_KEY to enable
    auto-summarisation."
  - If AI is on but returned nothing: "No synthesised note yet. Click
    ✎ Edit note to write one, or re-save the call to retry AI
    extraction."

### Changed
- **`addCall()` status line** is now branch-aware:
  - extracted MEDDPICC/scope → `Saved · AI extracted N MEDDPICC…`
  - AI off → `Saved — note stored as-is (AI is off, set
    ANTHROPIC_API_KEY to auto-summarise).`
  - AI on but empty → `Saved — Claude returned nothing extractable
    from this content.`
- **`refreshLeadSummary()`** short-circuits with a clear toast when
  AI is off rather than hitting the endpoint and surfacing a generic
  503.
- **Lead Summary fallback panel** now shows an AI-off explanation
  (with the env var name) instead of a generic "click ✨ Refresh"
  prompt when Claude isn't configured.
- **Lead Summary empty-state** (no calls yet) explains AI is off so
  the AE doesn't expect a magical summary after their first note.

### Notes
- This is a pure UX layer over v0.9.2 — server semantics unchanged.
  The primary fix for the user remains: set `ANTHROPIC_API_KEY` in
  Railway. This release makes the requirement obvious from inside the
  app instead of a silent fallback to the raw transcript.

### Tests
- 244 total. No behaviour change in the Python layer.

## [0.9.2] — 2026-05-17

Claude-driven aggregated lead summary at the top of the drawer.
Previously a static roll-up of the latest call's headline + MEDDPICC
fields; now a real synthesis across every call, scope criterion,
MEDDPICC entry, and contact.

### Added
- **`ai_summary.synthesise_lead(payload)`** — Claude Haiku 4.5 prompt
  that takes the full lead context and returns a 4-section summary:
  - `state_of_play` (2–3 sentences)
  - `key_facts` (3–5 grounded bullets)
  - `open_questions` (3–4 things to ask next)
  - `next_action` (one concrete move)
  - `risks` (optional, only if concrete)
- **`lead_summary_store.py`** — JSON-per-lead cache at
  `cache/lead_summaries/<lead_id>.json`. Avoids re-running Claude on
  every drawer open.
- **`/api/lead/<id>/summary`** endpoints:
  - `GET` returns the cached summary (or `null`).
  - `POST` gathers full context — Notion lead, scope, rolling
    MEDDPICC, up to 6 recent calls (synthesised + raw excerpt),
    contacts — runs Claude, caches the result.
- **Lead Summary panel redesigned** in the drawer:
  - 13px state-of-play block at the top
  - Green "What we know" bullets
  - Yellow "Open questions" bullets
  - Accent "Next move" line
  - Red "Risks" bullets (only if any)
  - Footer with generation timestamp + call count
- **✨ Refresh button** in the section header. AE clicks to regenerate
  after adding new notes or qualification changes. Falls back to the
  raw MEDDPICC roll-up if no cached summary exists yet.
- Audit log captures `lead_summary_refreshed` events with call count.

### Notes
- AI synthesis requires `ANTHROPIC_API_KEY`. Without it the endpoint
  returns 503; the drawer falls back to a "no AI summary yet" notice
  with the raw MEDDPICC roll-up.
- The synthesis is cached per lead. Refresh is on-demand so we don't
  burn tokens automatically. A future v0.9.3 could auto-refresh after
  call save — left explicit for now.

### Tests
- 244 total (+6). Covers store round-trip, prompt schema, endpoint
  behaviour under no-Anthropic-key.

## [0.9.1] — 2026-05-17

Pricing progress is now saved. Close the tab, come back, everything's
where you left it.

### Added
- **`pricing_store.py`** — JSON-per-lead store at
  `cache/pricing_configs/<lead_id>.json` holding the pricing
  configuration: currency, rate card, months, project_ops_pct,
  contingency_pct, discount_first_half_pct, role_overrides,
  role_staffing, selected_package.
- **`GET /api/pricing/config/<lead_id>`** + **`POST` (upsert)** endpoints.
- **Auto-save on every pricing input change.**
  - Editing any of the three input rows (currency / rate card /
    package / ops % / contingency % / discount %)
  - Editing any team FTE cell
  - Picking a role's Region or Seniority (Staff Aug)
  → debounced 600ms, then a single POST persists everything.
- **"Saved HH:MM" indicator** in the Pricing preview heading. Goes
  green on every successful save; flips red if a save fails. Shows
  the full "Last saved …" timestamp on first load.
- **Auto-restore on project load.** When you open a lead's Project
  Build, the saved pricing config rehydrates: currency / rate card
  / Ops / Contingency / Discount fields all repopulate, role
  overrides + Staff Aug staffing flow back into the team table.
  The "Last saved …" timestamp confirms what state you're picking
  up.
- Audit log captures every `pricing_config_saved` event with the
  field list.

### Coverage
After v0.9.1, **every authored surface in Project Build is now
persistent**:
- Scope criteria + statuses — saved via Save scope (existing)
- MEDDPICC for the lead — saved via Save lead (existing)
- Notes / calls — saved on add (existing, v0.6.0)
- Contacts — saved on add (existing, v0.6.0)
- Roadmap milestones + extended engagement — saved via Save
  roadmap (v0.9.0)
- **Pricing config + role overrides + staffing — auto-saved
  (this release)**
- SOW versions — written on every draft (existing, v0.5.0)

### Tests
- 238 total (+7). Covers store round-trip, unknown-key filtering,
  updated_at stamping, endpoint contracts.

## [0.9.0] — 2026-05-17

Project Roadmap + Extended Engagement. A roadmap lives between scope and
SOW, anchored to real dates, refined by Claude based on the notes +
qualification details we already collect.

### Added
- **`roadmap.py`** — `Milestone` and `ExtendedItem` data classes, plus
  a JSON-per-lead store at `cache/roadmaps/<lead_id>.json`.
  - Each milestone: workstream / title / month_offset / duration_months
    / phase / description.
  - Each extended item: year / title / description / package_key /
    estimated_hours / estimated_price_usd.
  - `seed_milestones_from_package(roadmap, package)` converts any of
    the 35 packages into a milestone list with workstream and phase
    auto-tagged from the role mix.
- **AI roadmap helpers** in `ai_summary.py`:
  - `suggest_roadmap(...)` — refines milestones using current scope,
    MEDDPICC, and the 5 most recent call notes. Returns a rationale
    sentence so the AE knows what shifted.
  - `suggest_extended_engagement(...)` — proposes 3-5 follow-on
    engagements anchored to the package catalogue, with rough hours
    + price.
- **Five new endpoints:**
  - `GET    /api/roadmap/<lead_id>`
  - `POST   /api/roadmap/<lead_id>` (upsert)
  - `POST   /api/roadmap/<lead_id>/seed-from-package`
  - `POST   /api/roadmap/<lead_id>/ai-refine`
  - `POST   /api/roadmap/<lead_id>/ai-suggest-extended`
- **Project Build: Roadmap card.**
  - Start date / Months / End date (auto-derived). Edit either and
    the others stay in sync.
  - Seed milestones from any package (35 options).
  - "✨ Refine from notes" runs Claude over the call history + scope
    and rewrites the milestone list, with a rationale shown above.
  - Gantt-lite visualisation: month-by-month grid with milestone bars
    coloured per workstream (CRM Strategy / CRM Build / CRM Execute /
    Data / Engineering / Cross-cutting).
  - Editable milestone table below the timeline: change workstream,
    title, start, duration, phase, or delete. Visualisation updates
    live.
- **Project Build: Extended Engagement section.**
  - Year 2 / Year 3 / Beyond cards.
  - "✨ Suggest based on notes" populates the cards from Claude's
    proposal (grounded in the package catalogue + call history).
  - Each card is editable in place — title, description, package
    reference, estimated hours, price.
- **SOW: two new sections** when a roadmap exists:
  - "Roadmap" — table of phase / workstream / milestone / start / duration
  - "Beyond Year 1 — Future Engagement" — grouped by year, with
    estimated hours + price inline
- **Lead Detail drawer: roadmap line** in the Project & Pricing
  summary — "Roadmap: 2026-07 → 2027-06 · 7 milestones · 4 Year 2+ ideas"
  with a click-through to Project Build.

### Notes
- Roadmap is optional. SOW renders without it. Drawer chip only shows
  when at least one of `start_date` or `milestones` is present.
- AI refinement reads the actual call notes (synthesised + raw) and
  MEDDPICC entries, so the roadmap moves when discovery details
  change. Re-running it overwrites the current milestones; AE then
  refines manually.
- Extended engagement uses package keys where possible so the
  estimates stay grounded in real hours.

### Tests
- 231 total (+14). New: roadmap store CRUD, end_date auto-derivation,
  workstreams-from-scope mapping, package seeding, milestone
  normalisation, round-trip via dict, endpoint contract under
  no-Anthropic-key, SOW snapshot + HTML render include the roadmap
  sections.

## [0.8.3] — 2026-05-17

Three fixes + one new feature on top of v0.8.2.

### Fixed
- **Status toggle buttons in Project Build didn't respond to clicks.**
  When the AE ticked a stream chip, `renderScopePanels()` rendered the
  criteria rows but never re-wired the click handlers — `statusToggleBindings()`
  was only called by `pbSave` and `pbLoadProject`. Moved the binding
  call into `renderScopePanels()` itself so every render is fully
  interactive. Same root cause as the v0.8.2 ccy bug pattern: rebuild
  the DOM, forget to rewire the handlers.
- **Edit → Cancel removed the raw transcript.** The previous call-card
  layout hid the raw content inside a collapsed `<details>` block.
  When AEs clicked Edit → Cancel, the synthesised note restored but
  the user-perceived "transcript gone" was actually the details still
  collapsed. New layout shows both side-by-side, so Edit/Cancel only
  swaps the synthesised-note view — raw stays visible the whole time.

### Added
- **Lead Summary at top of drawer.** Above the Calls & Notes list, a
  new "Lead Summary" panel rolls up across every call/note for the
  lead:
  - Headline from the latest call
  - MEDDPICC entries with most-recent value (Metrics, Economic Buyer,
    Decision Criteria, Decision Process, Paper Process, Pain,
    Champion, Competition) — only fields with content show
  - Project Scope synthesis if any call has produced one
  - Footer: count of calls/notes logged
  - Auto-refreshes whenever a call is added or edited.
- **Redesigned call card.** Synthesised note rendered in a clean panel,
  followed by Raw transcript / source in a labelled, scrollable
  monospace block (no more hide-in-details). Both always visible.

### Changed
- **Project Build criteria rows** got a design pass:
  - More breathing room (14px/16px padding, 12px gaps)
  - Larger status toggle buttons (7px/10px padding vs 5px/8px)
  - New "role-driver" pill style for "↗ CRM Developer effort"
    instead of inline run-on text
  - Input fields now have visible borders + focus state
  - Hover state on the row itself (border strengthens)
  - Bigger ✎ / × buttons (6px/10px padding)
- Status toggle now supports both MEDDPICC tones (not_started /
  in_progress / confirmed) and Scope tones (unqualified / qualifying /
  qualified) with consistent colors.

### Tests
- 217 total (unchanged for this round — fixes + UI only, no new
  backend code paths).

## [0.8.2] — 2026-05-17

Hotfix + editable AI-synthesised call notes.

### Fixed
- **HOTFIX: all buttons broken on the live platform.** The v0.8.1
  `renderPricing` function declared `const ccy` twice in the same
  scope (once for the summary tiles, once for the editable team
  table). JS aborts on `SyntaxError: Identifier 'ccy' has already
  been declared`, which kills every event listener on the page.
  Removed the duplicate. Added `test_no_duplicate_const_ccy_in_renderpricing`
  to lock against regression.

### Added
- **MR Call Note format** — Claude now returns a `synthesised_note`
  alongside the MEDDPICC + project_scope extraction, structured as:
  - `## Headline` — one sentence
  - `## Attendees` — bullets, MR + prospect mixed
  - `## What we heard` — 2-4 bullet summary
  - `## Discovery` — MEDDPICC roll-up (only fields with content)
  - `## Project shaping` — 1-2 sentences if grounded in the call
  - `## Action items` — separated by **MR:** and **Prospect:**
  - `## Risks` — only if concrete
  - Sections omitted entirely when there's nothing real to say.
- **Editable call notes.** Each call card now shows the synthesised
  note (rendered from markdown to HTML inline) with an **✎ Edit**
  button. Clicking Edit opens an inline textarea, AE refines, saves
  → `PATCH /api/calls/<lead>/<call>`. The original AI draft is
  preserved in `extracted.synthesised_note`; the AE's edits live in
  the top-level `note` field. An "(edited)" badge appears in the
  card header once the AE has diverged from the AI draft.
- **Raw transcript collapsed by default.** The original raw paste is
  still available behind a `<details>` toggle on each call card.
- **`POST /api/calls/<lead>` seeds `note` from `extracted.synthesised_note`**
  on first save. AE doesn't have to retype anything to start editing.
- **`PATCH /api/calls/<lead>/<call_id>`** endpoint — `note`, `title`,
  and `attendees` are editable; the raw content + AI extraction stay
  immutable so the audit trail is intact.

### Changed
- `calls_store.add_call` accepts `note` directly and seeds it from
  `extracted.synthesised_note` if not provided.
- Each call record now carries `updated_at` separately from `created_at`.

### Tests
- 217 total (+11). New: JS syntax regression (the hotfix), call store
  seeding from extracted note, update_call round-trip, endpoint
  contract for PATCH, AI prompt schema documents the new format.

## [0.8.1] — 2026-05-16

Pricing Calculator V2.0 Phase 2. Adds gross margin analysis, Staff Aug
region/seniority pickers, package "Apply" seeding, and inline per-role
rates in the team table.

### Added
- **`internal_costs.py`** — placeholder internal-cost engine. Real
  numbers will replace the 45% sales-rate ratio when Finance shares
  the `[Database] Rate Card - Internal` tab. `is_placeholder_data()`
  returns True until then so the UI can warn.
- **Gross margin in every quote.** `compute_quote` returns a `margin`
  block with internal cost, gross profit, margin %, and band
  (green/yellow/red, defaulting to ≥40% / 30-40% / <30%). Each monthly
  row carries internal cost + per-role internal rate; per-role rows
  in the breakdown have `internal_cost_usd`.
- **Pricing card UI: Margin row.** Four tiles below the headline:
  Internal cost / Gross profit / Margin % (color-coded) / Status. The
  Margin % tile shows the target threshold. Yellow placeholder banner
  appears beneath the row while internal-costs are still stubbed.
- **Staff Augmentation: per-role Region + Seniority pickers.** When
  the AE picks the Staff Aug rate card, every team-row gets two
  dropdowns alongside the FTE inputs. Changing either re-prices live.
- **Effective hourly rate per role** in the team table — a small Rate
  column shows what each role costs at the picked currency / rate
  card / staffing.
- **Apply Package button.** Picking a package + clicking Apply
  computes hours-per-month per role, distributes evenly across the
  3 phases as FTE, and overwrites `roleOverrides`. AE then tweaks per
  phase. Confirmation prompt before overwriting.

### Changed
- `compute_quote` output gains `margin` (new top-level block) plus
  `internal_cost_usd` and `internal_rate_per_hour` fields in monthly
  rows.
- `/api/pricing/preview` accepts `role_staffing: {role: {region,
  seniority}}` and threads it into both rate AND internal-cost
  lookups so Staff Aug margins reflect the right cost basis.

### Notes
- Reference deal still produces $1,191,360 gross / $1,112,016 net.
  Margin under placeholder ratio is ~50% (the cost stub is uniform,
  so this is structurally meaningful but not precise — needs the
  real Internal Rate Card before relying on the number).
- Region/Seniority pickers default to whatever the AE picked
  previously for that role. No defaults are auto-applied — the AE
  must explicitly choose. Until they do, rate falls back to MR
  Default for that role.

### Tests
- 206 total (+13). New: internal cost = 45% of sales, margin band
  thresholds, quote returns margin block, ops uplift increases
  margin (revenue rises, cost unchanged), monthly rows carry
  internal cost, Staff Aug staffing flows through to pricing,
  fallback to MR Default when no staffing supplied, endpoint
  accepts role_staffing.

## [0.8.0] — 2026-05-16

Pricing Calculator V2.0 — multi-currency, multi-rate-card, with
Project Ops + Contingency uplifts. Data sourced directly from the
live Google Sheet workbook
(`1ghZrB-U7GoJ6IGR9K9yj3ptUbwM7IU4J_hRpFJ-00K4`), tabs
`[Database] Rate Card - Sales` and `[Reference] Packages`.

### Added
- **`rate_cards.py`** — codified rate card data:
  - **MR Default** (region-agnostic blended): £150/$200/€175 per hour
  - **Staff Augmentation** — 47 entries across role × seniority × region
    (UK, EU, LATAM, India). Includes Braze Technical Architect,
    Business Analyst, CRM Consultant (incl. AI variant), CRM Developer
    (Braze + SFMC), CRM Operations Manager, CRM Strategist, CRM Team
    Lead, CRM Director, Data Analyst, Data Engineer (CDP/Kafka/
    Snowflake), Manual QA Engineer, Platform Engineer, Project Manager,
    Scrum Master, Software Engineer, Technical Architect, Technical
    Product Owner.
  - **Client-specific cards**: Yum! Small Markets (Onboarding
    Consultant only) and Yum Thailand! (all roles, blended).
  - `rate_lookup(card, role, currency, region, seniority)` — single
    entry point. Falls back to MR Default if a role isn't on a custom
    card.
- **`packages.py`** — 35 pre-defined project packages from the
  `[Reference] Packages` sheet:
  Light Audit, Audit/Inception, Braze Onboarding & Training,
  Braze Setup & Configuration, Braze Migration, [X-small|Small|Medium|
  Large] Braze Operations, Customer 360, CDP Setup, CDP & Data
  Operations, Salesforce Connector, Braze SDK Integration / Advisory,
  CRM Development (+ game variants), Web/Mobile MVP, Support &
  Maintenance, full PLO range (Lite/Growth/Bronze/Silver/Quick Start/
  Ignite/Custom), Small Market variants, and add-on top-ups.
- **`/api/pricing/rate-cards`** — returns currencies, rate card names,
  regions, seniorities, full Staff Aug rate table, and the MR Default
  blended rates per currency. Powers the new dropdowns.
- **`/api/pricing/packages`** — returns all 35 package definitions.
- **`/api/pricing/preview` accepts new fields**:
  `currency`, `rate_card`, `project_ops_pct`, `contingency_pct`,
  `role_staffing` (per-role region/seniority for Staff Aug). All
  optional; defaults preserve v0.4 behaviour.
- **Project Build pricing card extended**:
  - Currency selector (USD / GBP / EUR)
  - Rate card selector (MR Default / Staff Augmentation / Yum! Small
    Markets / Yum Thailand!)
  - Package selector (35 options as a starting point — visual only for
    now; deeper seeding lands in P2)
  - Project Operations % input
  - Contingency % input
  - Discount % input (was hidden, now editable per quote)
  - Any change live-recomputes pricing
- **Pricing summary now currency-aware** — tiles render the right
  symbol (£/$/€). When Ops or Contingency is non-zero, the layout
  expands to show Gross / + Ops & Contingency / − Discount / Net.

### Changed
- `pricing.py` rate lookup goes through `rate_cards.rate_lookup`
  instead of a hardcoded $200 constant. `ROLE_RATES_USD_PER_HOUR`
  retained for backward-compat but no longer the source of truth.
- `compute_quote` output now includes `ops_usd`, `contingency_usd`,
  `subtotal_usd` in both monthly and totals blocks.
- The reference deal (12-month CRM Build, MR Default, USD, 15%
  first-half discount, no Ops, no Contingency) **still produces
  exactly $1,191,360 gross / $1,112,016 net / 5,957 hours** — tests
  pin this so the existing calibration doesn't drift.

### Still pending (v0.8 Phase 2)
- **`[Database] Rate Card - Internal`** tab — needed for gross margin
  calculation. The AE-visible quote works without it; the Ops-side
  margin indicator does not.
- Per-role region + seniority pickers in the team table (Staff Aug
  becomes meaningful UI-side once the AE can pick per-role staffing).
- Package "apply" — clicking a package today only shows its hours; in
  P2, applying a package seeds the team allocation table from the
  package's role × hours breakdown.

### Tests
- 193 total (+18). New: rate card lookups (UK/EU/LATAM/India + Yum
  cards), Yum Thailand reduces price, 35 packages all have valid
  components, currency switching produces proportional gross,
  Project Ops + Contingency math, backward-compat reference deal.

## [0.7.0] — 2026-05-16

Project Build is now reachable from inside the pipeline drawer, with
live editable staffing and inline coaching on how the calculator works.

### Added
- **Project & Pricing section in the Lead Detail drawer.**
  - If no project exists for the lead: "✨ Create Project" button →
    creates a draft project (defaulting to a CRM Build stream), switches
    to Project Build view, pre-fills the lead id + company name, and
    loads the project for editing.
  - If a project exists: shows validation badge, qualified-pct,
    streams selected, and the latest forecast net total. "Open Project
    Build →" button switches to the full view.
- **Editable team FTE in the Pricing preview.** The previously-read-only
  team × phase matrix now has a `<input type="number" step="0.05">`
  for every cell. Changing any FTE triggers a debounced (350ms) live
  recompute of the quote — gross / discount / net / hours all update,
  plus the Chart.js monthly bars. Inputs keep focus across recomputes.
- **Coaching tooltips.**
  - Hover any phase header (Understand / Execute / Accelerate) for a
    one-line explainer of what MR does in that phase + typical team
    shape.
  - Hover any role row for its responsibilities + typical FTE range.
  - Each scope criterion in Project Build now surfaces its role driver
    inline ("Impacts CRM Developer effort"), so the AE sees how their
    Qualifying/Qualified answers translate to pricing.
  - "How is this calculated?" link below the team table opens a 5-step
    explainer of the pricing model: baseline team → criteria-driven
    multipliers → blended rate → discount → totals.
- `pbState.roleOverrides` accumulates per-cell edits across keystrokes
  and rides with every pricing-preview call. Reset between projects so
  edits don't bleed across leads.

### Changed
- `pbPreviewPricing()` now passes `pbState.roleOverrides` to
  `/api/pricing/preview` (server already supported it).

### Notes
- No backend changes. Live recompute uses the existing
  `/api/pricing/preview` endpoint with `role_overrides`.
- The Project Build view still requires lead_id resolution to bridge
  with the drawer (page_id as lead_id). The system is consistent
  internally; the AE never sees the slug.

### Tests
- 175 total (unchanged). All UI/integration changes, no new
  server-side behaviour to test.

## [0.6.0] — 2026-05-16

The "pipeline progression" release. AEs can now keep a rolling log of
calls and notes per lead (with AI extraction), maintain a persistent
contacts list per company, mark a Key Contact, and stop seeing Notion
plumbing in the UI.

### Added
- **Persistent contacts per lead** (`contacts_store.py`). Each lead gets
  a `cache/contacts/<lead_id>.json` file with a list of contacts —
  name, title, email, LinkedIn, phone, city, country, source
  (apollo/manual), is_primary flag, and timestamp.
- **Key Contact** flag — exactly one contact per lead can be primary
  (auto-clears on others when set). Surfaced with a `KEY` chip in
  the drawer.
- **`+ Save` button on Qualify Lead stakeholders** — after the lead is
  saved to the pipeline, the AE can persist Apollo-discovered
  stakeholders one click at a time. Each saved contact is sourced
  as "apollo" for audit.
- **Manual contact entry** in the drawer — collapsible form for AEs
  who want to capture names that didn't come from Apollo.
- **Persistent calls + notes log** (`calls_store.py`). Each lead has a
  `cache/calls/<lead_id>.json` storing timestamped entries with type
  (call / note / email / transcript), title, content, and AI
  extraction results.
- **AI extraction baked into call save** — when ANTHROPIC_API_KEY is
  set, every saved call runs through `ai_summary.extract_from_notes`
  and the extracted MEDDPICC + project_scope ride with the record.
  UI surfaces "AI ✦ N MEDDPICC + scope" on each entry.
- **Calls & Notes section in the drawer** — paste form at the top,
  history below (newest first), each entry with content preview, AI
  badge, and delete button.
- **`/api/contacts/<lead_id>` and `/api/calls/<lead_id>` endpoints** —
  GET / POST / DELETE plus `POST /api/contacts/<lead_id>/<contact_id>/primary`
  for the Key Contact toggle.
- **Expanded Apollo search titles** — Apollo's `mixed_people/api_search`
  now also includes CDTO, CCO, Chief Data Officer, VP/Director/Head of
  Digital, Digital Marketing, Data, Data Engineering, Analytics, and
  Customer Data leadership. Default search returns a richer cross-
  section of the buyer mix MR actually sells into.

### Changed
- **"Push to Notion" renamed to "Save lead"** throughout the Qualify
  view (header, button, success toast). Same goes for the failure
  toast — generic "Save failed" instead of mentioning the data store.
- **"Open in Notion ↗" link removed** from the drawer header.
- The data store stays Notion, but the platform now reads as a
  pipeline app — AEs don't need to know what's behind the scenes.

### Operational notes
- Both new stores live on the container's ephemeral filesystem.
  Mount a Railway volume at `/app/cache` to keep contacts + calls
  + audit log + project store + criteria store across deploys.
- AI extraction is best-effort: if Anthropic is unconfigured or the
  call fails, the call is still saved without the `extracted` block.

### Tests
- 175 total (+18). New: Apollo roles expansion, contacts CRUD +
  bulk save + primary logic, calls CRUD + extraction aggregation,
  both endpoint contracts.

## [0.5.4] — 2026-05-15

Partner sourcing made queryable: filter Pipeline by source / sourced-for,
and aggregate the same dimensions in the Slack digest.

### Added
- **Pipeline filters: source + sourced-for.** Two dropdowns next to the
  existing status chips:
  - `All sources` — filters to leads with `opportunity_source` matching
    the picked value (e.g. "show me all Braze-sourced leads").
  - `Any sourced-for` — filters to leads where `sourced_for_partners`
    includes the picked partner (e.g. "show me everything we're sourcing
    for Snowflake").
  - Option lists populate dynamically from the rows currently loaded —
    only partners that actually appear show up.
- **Slack digest: partner sourcing section.** When `pipeline_rows`
  contains sourcing data, the digest renders:
  - `Sourced to MR by partner` — count + company list per source
  - `MR sourcing for partners` — count + company list per sourced-for
  - Up to 8 partners per section, top-5 companies inline per partner,
    sorted by count desc.
  - Section is omitted entirely if no sourcing data is present.
- `slack_digest.partner_sourcing_breakdown(rows)` — pure aggregation
  helper, usable outside the digest (e.g. for a future report endpoint).

### Changed
- `notion_sync._row_from_page` now includes `opportunity_source` and
  `sourced_for_partners` so Pipeline rows carry the data needed for
  filtering and reporting.

### Tests
- 157 total (+9). Covers row enrichment, breakdown aggregation,
  digest inclusion/omission logic.

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
