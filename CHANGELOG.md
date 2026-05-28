# Changelog

All notable changes to the Massive Rocket Lead Qualification Platform.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0di] - 2026-05-28 - Outreach drafts: hard-strip em-dashes

Ben: "When generating messages. Programme AI to make sure that it
doesn't use em-dashes to create message drafts."

The system prompt already said "no em-dashes" but Claude was still
emitting them occasionally on longer email bodies. Two-layer fix:

### Stronger prompt

New BANNED CHARACTERS section in the outreach system prompt with
explicit examples of bad/good rewrites and an honest "we strip them
anyway, so just don't" closer. Sits below the WRITING STYLE block so
the model sees it right before output rules.

### Post-process sanitiser

New `_strip_dashes()` function replaces every em-dash (U+2014),
en-dash (U+2013), and horizontal bar (U+2015) with a regular
hyphen-minus (U+002D) in BOTH subject and body before anything else
(mailto URL build, char_count). Runs unconditionally - no-op when
the model honoured the prompt, guaranteed safety net when it didn't.

### Tests

5 new tests in test_outreach.py:
- `_strip_dashes` direct unit tests (em, en, none/empty, clean pass-through)
- `draft()` end-to-end with a mock model that deliberately violates
  the em-dash rule -> verifies the user never sees one

### Verified

1217 tests pass (+5 new). Server clean.

### Followup (not in scope)

The same sanitiser pattern could apply to other AI-generated text
surfaces (synthesised lead notes in ai_summary.py, Jeff chat
responses, expansion-associates suggestions). For now they all have
"no em-dash" in their prompts. If you spot a stray one elsewhere,
flag it and I'll add the sanitiser there too.

## [1.0.0dh] - 2026-05-27 - Partner contact notes/edit as right-side drawer

Ben: notes/edit on partner contacts should open as a slide-in panel
from the right (like the lead drawer in Pipeline), not expand inline
under the table.

The inline expand was a problem on 137-row Braze/Hightouch tables -
the panel rendered far below the fold and the v1.0.0k scroll-into-
view + flash hack only partly solved it. A drawer beats both.

### Changes

- **New `#pc-drawer-overlay` + `#pc-drawer` markup** mirrors the lead
  drawer (`.drawer` + `.drawer-overlay` CSS reused, same slide-in
  animation, glass header, 560px width).
- **`openPartnerContactDrawer({title, subtitle})`** helper opens the
  drawer + sets header text + wires Esc-to-close.
- **`closePartnerContactDrawer()`** slides it back, restores focus,
  clears body after the transition.
- **`openContactForm` and `openContactNotes` retargeted** to render
  into `#pc-drawer-body` instead of `#ptn-contact-detail`. Inner
  Cancel / Done buttons now close the drawer instead of clearing
  an inline div.
- **Overlay click + Esc** both close (wired once on script init).
- **Legacy `#ptn-contact-detail` element kept in DOM** as a fallback
  mount point so any straggling code paths don't NPE - both functions
  fall back to it if the drawer body is missing.

### Verified via Preview MCP

- Drawer slides in from the right with backdrop dim
- Title shows the contact name; subtitle shows title + email
- Body renders the full 3001-char notes UI (Type / Note / Add /
  Done / Refresh summary)
- Esc + X + overlay click all close

### Followup (cosmetic, not blocking)

Inner card still has its own `<h4>Notes - {name}</h4>` header which
now duplicates the drawer's title bar. Trim that in a small followup
so the name doesn't show twice.

### Verified

1212 tests pass. Server clean. JS clean.

## [1.0.0dg] - 2026-05-26 - Use-cases catalog read layer + lead drawer card

Step 1 of 3 in integrating Ben's separate Django use-cases platform.
Schema-aligned to the catalog_* tables he pasted (industry / platform
/ featurearea / usecase + M2Ms + agent + generatedasset).

### New: usecases_db.py

psycopg-3 read layer with connection pool. Lazy init - if
`DATABASE_URL_USECASES` isn't set, every call returns empty
lists / None and the UI degrades silently (no 500s).

Public functions:
- `is_configured()` - env-var presence check
- `healthcheck()` - diagnostic ({configured, reachable, reason})
- `list_industries()` / `list_platforms()`
- `list_use_cases(industry_slug, platform_slug, status, limit)`
- `get_use_case(id)` - includes M2M slugs (platforms, feature areas,
  agents)
- `match_for_lead(industry, tech_stack, limit)` - cumulative scoring:
  +3 industry match (slug or name), +2 per platform overlap. Returns
  ranked candidates with match_score.

### Endpoints

- `GET /api/use-cases?industry=&platform=&status=&limit=` - filtered list
- `GET /api/use-cases/<id>` - single use case detail
- `GET /api/use-cases/lookups` - industries + platforms for filter UIs
- `GET /api/use-cases/match?industry=&tech_stack=Braze,Snowflake` -
  ranked matches for a lead

All endpoints return `{configured: false, use_cases: []}` shape when
the DB is unwired, so callers can render gracefully.

### UI: Lead drawer "Relevant proof points" card

Lives between News and Calls. Hidden when no industry + no
tech_stack on the lead, or when DB returns no matches. Each card
row shows:

- Title
- Client name (or "Anon" if `is_anonymised`)
- Match score chip
- Up to 3 metric chips from the `metrics` JSONB field
- First 220 chars of `outcome` (truncated)

### Dependencies

Added `psycopg[binary]>=3.2` to requirements.txt. Binary wheel so
Railway doesn't need libpq + build tools.

### Deploy notes

To activate on Railway:
1. The use-cases Django app is running on Railway with a Postgres
   add-on. Find its internal DB URL (Railway Variables → Postgres
   add-on → DATABASE_URL).
2. Create a read-only DB role for this platform:
   ```sql
   CREATE ROLE qualification_reader LOGIN PASSWORD '<pick>';
   GRANT CONNECT ON DATABASE <dbname> TO qualification_reader;
   GRANT USAGE ON SCHEMA public TO qualification_reader;
   GRANT SELECT ON catalog_industry, catalog_platform,
                    catalog_featurearea, catalog_usecase,
                    catalog_usecase_platforms,
                    catalog_usecase_feature_areas,
                    catalog_agent, catalog_usecase_agents_used,
                    catalog_generatedasset,
                    catalog_generatedasset_selected_use_cases
   TO qualification_reader;
   ```
   (v1.0.0dh will need INSERT / UPDATE on `catalog_usecase` +
   the M2M tables for the write path. Add when shipping that.)
3. Set `DATABASE_URL_USECASES` env var on the lead-qualification
   Railway service to:
   `postgresql://qualification_reader:<pwd>@<host>:5432/<dbname>`
4. Redeploy. The card auto-appears on leads with matching
   industry / tech_stack.

### Verified

1212 tests pass (+11 new). Server clean. JS clean. End-to-end via
mocked psycopg cursor.

## [1.0.0df] - 2026-05-26 - Outreach draft button (email / LinkedIn / Slack)

Ben: "Is it possible to build an easy outreach button to create an
email, slack or linkedin message to send out?"

### New module: outreach.py

`draft(contact, channel, *, tone, context_hint, recent_notes,
sender_name)` returns a channel-aware message:

- **email**: `Subject: <line>` + 2-3 paragraph body, signed,
  with a ready-to-open `mailto:` link
- **linkedin**: single message < 280 chars, no subject, no
  signature (LinkedIn DM cap is 300; leave headroom)
- **slack**: single message < 200 chars, casual

Channel rules + tone presets (friendly / re-engagement / intro /
update) are baked into the system prompt so the model can't drift.
Writing style enforced: no em-dashes, no "I hope this finds you
well" cliches, one concrete ask per message.

Drafts only - never auto-sends. The platform doesn't have IMAP /
LinkedIn / Slack credentials by design.

### Endpoint

`POST /api/outreach/draft`
- Body: `{contact_kind, partner_id|lead_id, contact_id, channel,
  tone, context_hint, sender_name}`
- Resolves the contact (partner_contact + lead_contact supported)
- Pulls recent notes (partner_notes_store / calls_store) for
  grounding context
- Returns `{draft: {subject, body, mailto, char_count, ...}}`

### UI

New **envelope icon button** on each partner contact row, between
the + todo and edit buttons. Click opens a modal:

- **Channel** chips: Email / LinkedIn / Slack (disables Email if
  the contact has no email; defaults to whichever channel has
  contact info)
- **Tone** chips: Friendly / Re-engagement / Intro / Update
- **Context** textarea: optional one-line goal
- **Generate** -> draft renders with Subject (email only) +
  Body fields, both readonly+editable
- Action buttons: Copy subject / Copy body / Open in mail client
  (mailto, email only) / Open LinkedIn profile (linkedin only) /
  Save as note on contact

The "Save as note" path attaches the draft + channel + tone as a
typed `outreach` note on the partner contact so there's a record
even if the message never actually sends.

### Verified

1201 tests pass (+10 new). Server clean. JS clean. Anthropic mocked
end-to-end for the endpoint tests.

### What's not in v1 (followups)

- Lead-contact + expansion-target rows: same button shape, will land
  in v1.0.0dg when Ben asks
- Auto-send via integration (Gmail OAuth / Slack API): not designed -
  drafts only by intent
- Sequence builder (multi-step nurture): scoped out

## [1.0.0de] - 2026-05-26 - Drop City x City from default metrics

Ben: "For city x city let's remove that. That is more for events
when we have them."

Removed `city_x_city_conversations` from:
- `_DEFAULT_METRICS` in quarterly_targets_store.py
- `scripts/seed_q2_2026_targets.py` (both AM and Big Bets seed rows)
- `knowledge/q2_2026_targets.md` (replaced the row with a note about
  per-quarter ad-hoc add when an event is running)

Behaviour: new quarters no longer show the metric. The platform's
auto-merge for custom metric keys still works, so when a future
event quarter calls for it, the team can add `city_x_city_q3_event`
(or similar) via the editor and it'll render alongside the standing
metrics for that quarter only.

Anyone who already ran the seed before this commit has City x City
rows in their Q2 2026 data. Clear via Settings -> Targets - set
both plan + actual to 0; the metric will continue to render as a
custom key but won't pull the eye since both numbers are zero.
(Or run the updated seed script again - it's idempotent and skips
the now-removed City x City lines.)

## [1.0.0dd] - 2026-05-26 - Key stakeholder coverage metric

Ben: "I'd like coverage across key stakeholders as a metric. Will
need to identify who are the key stakeholders with the team."

Crucial clarification: key stakeholders = **partnership team's
contacts** (Marina at Braze, Jamie at Hightouch, etc.), not buyer-
side MEDDPICC roles. And "covered" = identified AND engaged
recently.

### Lean v1

- New `is_key_stakeholder: bool` field on `partner_contacts_store`.
  Manually toggled per the team's call on who counts as key.
- `_PARTNER_CONTACT_PATCH_FIELDS` extended so PATCH accepts the flag.
- Truthy-tolerant `_coerce_bool` helper (accepts JS true, "true",
  "1", "yes", 1, etc).

### stakeholder_coverage.py (new module)

Single `compute(window_days=30)` entry point. Iterates partners +
their contacts, filters to `is_key_stakeholder=True` and excludes
`status=left`. Buckets each into covered / stale / never_touched
based on `last_touched_at`. Returns:

- totals (`coverage_pct`, `key_total`, etc.)
- by_partner array sorted worst-coverage-first (action priority)
- stale_contacts + never_touched action lists (capped at 50 each)

### Endpoint

`GET /api/metrics/stakeholder-coverage?window=30` - window clamps
to 1..365.

### UI

**Partner contacts table:** new `Key` column with a star icon
(★/☆). Click toggles + PATCHes optimistically. Yellow filled star
when key, grey outline when not.

**Dashboard card:** new "Key Stakeholder Coverage" card above
Quarterly Targets. Shows:
- Big % with bar (green ≥75, accent ≥50, red below)
- Covered / stale / never-touched counts
- Per-partner breakdown sorted worst-first, click partner name to
  jump to that partner detail
- Collapsible "N stale contacts need a touch" action list

Window picker: 30 / 60 / 90 days.

### Quarterly target metric

New default key `partner_stakeholder_coverage_pct` ships with the
default metrics list. Plan-side is editable in Settings -> Targets;
actual rolls up live from the coverage endpoint.

### Verified

1191 tests pass (+10 new). Server clean. JS clean.

## [1.0.0dc] - 2026-05-26 - Q2 2026 seed + extended target metrics

Ben dropped the full Q2 2026 leadership-doc data: 28 metrics across
5 functions (Marketing / Partnerships / Business Development /
Account Management / Big Bets), per-function plan + actual, plus
named QL accounts (GoPuff Bevmo, KFC US, Sainsburys, KFC UK, etc.).

### Changes

1. **`_DEFAULT_METRICS` extended** to 33 entries covering the
   leadership framework: Pipeline (QLs + Warm Intros + Positive
   Actions), Engagement signals, Conversations, Content, Vendor
   meetings, Sequences, Expansion. Legacy `opportunities` and
   `re_engagements` kept so older quarters still render with nice
   labels.

2. **`scripts/seed_q2_2026_targets.py`** - cell-by-cell PATCH script
   that loads the data via the existing API. Dry-run + idempotent.
   Run:
   ```
   APP_URL=https://web-production-b7cb5.up.railway.app \
   APP_AUTH_TOKEN=<token> \
   python3 scripts/seed_q2_2026_targets.py
   ```

3. **`knowledge/q2_2026_targets.md`** - human-readable snapshot
   preserving the named QL accounts (which don't fit the counter-
   only store) as audit trail. Includes parser caveats listing the
   defaults I picked where the leadership doc was column-ambiguous.

### Parser interpretations (verify after seed)

The leadership doc's layout was function-as-column. Where columns
were unambiguous I followed them. Where ambiguous I defaulted:

- "Other" column in actuals = "Big Bets" column in plan
- Engagement signals + Conversations + Content → Marketing
- Vendor meetings (Braze/HT/Snowflake/Other) → Partnerships
- Sequences + Expansion → Account Management
- City x City Conversations → both AM (50) and Big Bets (50)

Anything wrong, fix via Settings → Targets - each cell saves on
blur.

## [1.0.0db] - 2026-05-26 - Quarterly targets (plan vs actual, team + per-owner)

Ben: "Here are our quarterly targets (actuals and plan) as a team
for engagements and opportunities. Bake this in to the dashboard
for leadership visibility to see and work around. Need a way to
edit this as we go along as well."

Clarified: 'engagement' = re-engagement (winning back lost / nurture
accounts via outreach), NOT live project or signed deal. So the
two default metrics are:

- **opportunities** - new qualified leads in the quarter
- **re_engagements** - accounts won back from Closed Lost / Nurture

Both editable per quarter, with team total + per-owner split. The
editor also accepts arbitrary metric keys (revenue, etc) so admins
can extend without code changes.

### New module: quarterly_targets_store.py

- Calendar-quarter id convention: `YYYY-Qn` (e.g. `2026-Q2`)
- Shape: `{quarters: [{id, year, quarter, metrics: {<key>: {team:
  {plan, actual}, by_owner: {<name>: {plan, actual}}}}}]}`
- Atomic writes via json_file_store
- Single-cell PATCH path for inline editor responsiveness
- 14 store tests + 5 endpoint tests = 19 new tests

### Endpoints

- `GET  /api/quarterly-targets` - list quarters + default metric specs
- `POST /api/quarterly-targets` - upsert a whole quarter
- `PATCH /api/quarterly-targets/<qid>` - one-cell update
  `{metric, kind, owner|null, value}`
- `DELETE /api/quarterly-targets/<qid>` - remove

### UI

**Dashboard:** new "Quarterly Targets" card above the weekly
report. Defaults to current calendar quarter with a picker for
other quarters. Each metric shows team plan/actual + a percent-of-
plan progress bar (green ≥100, accent ≥75, yellow below), with a
collapsible per-owner breakdown. "No targets yet" empty state
links straight to the Settings editor.

**Settings → Targets tab:** one card per quarter, table rows for
Team total + every known owner (pulled from mr_owners + any saved
target owners). Each cell is a number input that PATCHes on blur -
type, tab, done. "+ Add quarter" modal uses year + quarter picker.
Delete confirms.

### Verified

- 1180 tests pass (+19 new), server clean, node --check clean

## [1.0.0da] - 2026-05-26 - Show owner on Expansion page

Ben: "Need to make sure who the accounts are assigned to on the
expansion page is included."

Server: /api/expansion/overview builds an `owner_by_lead` index
alongside `name_by_lead` from the pipeline rows it already pulls.
Each anchor dict gets an `owner` field (pipeline owner first,
live_project owner as fallback). Already-present `pipeline_match`
on targets continues to carry its own owner.

UI: anchor header now shows the owner as a small chip with a red
dot, or "unassigned" italic when missing. Each target row that
has a pipeline_match shows the matched lead's owner inline.

## [1.0.0cz] - 2026-05-26 - Fix project scope build (auto-save before preview)

Ben: "The project scope build isn't working. All seems to default
with the same pricing and same team for a project."

### Root cause

The Preview Pricing button sent only `{lead_id, currency, rate_card,
months, role_overrides, role_staffing, ...}` to /api/pricing/preview.
The server loaded the saved project from disk and called
`scope.role_drivers_for_project()` to derive role-effort multipliers
from the persisted `scope.streams[].criteria[]`.

But the AE's typed scope answers in the form only existed in DOM
state until they clicked Save scope. Preview Pricing didn't auto-
save first.

Consequence: every Preview ran against an empty/baseline scope,
returning the same team template + the same numbers regardless of
what the AE filled in.

### Fix

`pbPreviewPricing()` now calls `pbSave({silent: true})` first when
`pbState.current` exists. That POSTs the DOM-collected scope
criteria to /api/scope/<lead_id>, which calls scope.update_criteria
under the hood. Idempotent + non-fatal: if the silent save fails
(network blip), we still try the preview with whatever was last
persisted.

After this fix, two different scope inputs produce two different
quotes:
- 1 SDK migration + 10 campaigns -> baseline crm_execute team
- 100 campaigns + 5 channels + India staffing -> larger team,
  effort multipliers applied per scope criteria, region-specific
  rate card

### Verified

- 1161 tests pass (scope/role_driver paths covered by
  test_v08_phase2_margin + test_v08_rate_cards_packages)
- Server clean, node --check clean

## [1.0.0cy] - 2026-05-26 - Fix AI suggest 500 (NotionSync.get_page shape)

Ben caught: "AI suggestions isn't working."

Root cause: v1.0.0cw's suggest-associates endpoint assumed
`NotionSync.get_page(lead_id)["company"]` returned a dict like
`{name, apollo, parent_group}`. It actually returns just the
company name as a plain string. Calling `.get("name")` on a string
raised AttributeError and 500'd the endpoint with no user-friendly
error.

Fix: handle both shapes defensively. Use the company name (which
is what Claude needs for sister-brand enumeration anyway). Apollo
description + parent_group remain optional - they're only set
when the qualify-result dict shape is passed, which doesn't
happen for stored Notion leads.

Also: log warning on get_page failure so future occurrences land
in Railway logs.

## [1.0.0cx] - 2026-05-26 - Add account from Directory

Ben: "Should be able to add an account to the directory as well."

The Directory page was read-only until now. Accounts landed in
there only via the full Qualify flow or by promoting to live.
Now there's a + Add account button next to the search box.

Clicking opens a single-shot modal:
- Company name (required)
- Website (optional)
- Add as: Lead (skinny Notion row, lands in Pipeline) or
  Expansion target (under a picked anchor account)
- Anchor account picker - shown when there are existing anchors
- Notes (optional) - if set on a Lead path, attached as a 'note'
  type call after the page is created

Lead path posts to /api/notion/sync with a minimal payload
(company name + URL + owner + status="New"). The full pipeline
runs Notion-side, the platform pulls the row on next directory
refresh.

Expansion-target path posts to /api/expansion-targets with the
picked anchor. Anchor picker only renders if there's at least
one valid candidate (lead or live-project) in the directory.

## [1.0.0cw] - 2026-05-26 - Note-loss audit + Expansion polish + AI associates

Three things landed together since they're all Expansion / data-
durability work.

### v1.0.0cu - Note-loss audit + atomic writes

Ben asked: "double check if notes are still susceptible to being
lost". Audit found 2 critical + 3 medium risks. The most impactful
ones are now fixed:

1. **Atomic JSON writes** in `json_file_store.write_json` -
   tempfile + os.replace. calls_store + partner_notes_store both
   route through this now. A crash mid-write can no longer corrupt
   a notes file. Both stores load via try-except so a corrupt JSON
   would silently return [] - that's the failure mode this prevents.
2. **localStorage draft** for the qualify view's #notes-text. Was
   in-memory only; browser refresh wiped it. Now: every keystroke
   writes a draft keyed in localStorage, restored on next visit,
   cleared only after a successful lead save.
3. **pendingNotes flush** keeps failed notes in the buffer instead
   of nuking it unconditionally. Toast tells the user how many
   stayed so they can retry.

Two remaining audit items (lead-drawer textarea clear timing, raw
qualify-context retry queue) are MEDIUM-risk edge cases worth a
follow-up but not blockers - the jsonFetch path already throws on
non-2xx so the most common failure mode preserves the textarea.

### v1.0.0cv - Expansion design polish + open-account button

Ben: "Account Expansion page looks a bit bland."

- Totals strip uses .stat / .stat-grid (32px tabular numbers,
  eyebrow labels) - matches Home + Dashboard
- New "Converted" stat added (was implied via filter only)
- Anchor card header bigger (16px company name, gradient surface),
  cleaner project-status pill
- New "Open account" button on each anchor - opens the landed
  lead in the drawer so users see contacts + notes + activity
  without leaving Expansion
- New "AI suggest" button on each anchor (powers v1.0.0cw below)
- Filter chips use the proper .filters / .chip styles (was inline
  smaller pills)

### v1.0.0cw - AI-suggested associated accounts

Ben: "When dealing with groups e.g. parent child accounts, AI
should help on the Expansion page by indicating if it's found
associated accounts to create and add to the directory."

Endpoint `/api/expansion/<lead_id>/suggest-associates`:
- Resolves the anchor's company name + Apollo description +
  parent_group hint
- Asks Claude to enumerate sister brands, subsidiaries, regional
  units, joint ventures - max 8, one-phrase rationale per pick
- Server-side dedup against existing pipeline rows + existing
  expansion targets so the modal only shows NEW candidates
- Logs `expansion_associates_suggested` audit event

UI: clicking "AI suggest" on an anchor opens a modal listing
candidates with checkboxes (all checked by default), name, kind
(sister_brand / subsidiary / regional_unit), and a short
rationale. "Add as expansion targets" creates them in bulk with
"[AI suggested - <kind>] <rationale>" stored in the target notes
so the source is auditable.

## [1.0.0ct] - 2026-05-26 - Weekly manager report + Apollo diagnostics + expansion linking

Three things landed together since they're all Dashboard-area work.

### v1.0.0cr - Apollo search diagnostic UX

Ben hit "Search Apollo for contacts" and got no results; couldn't
tell whether the lead URL was wrong, the country filter was too
narrow, or Apollo just had nothing on the domain. The empty-state
"No matches" message was unhelpful.

Now: empty state shows the actual domain searched, the country
filter applied (if any), the Apollo mode (live vs fixtures), and
three concrete causes the user can act on. Errors land inline too
(not just as a toast that auto-dismisses). Server adds `mode` to
the response so the UI surfaces it.

### v1.0.0cs - Expansion target links to pipeline lead

When an expansion target's company name matches an existing
pipeline lead (case-insensitive), the card now shows an "IN
PIPELINE - <stage>" badge plus a "View lead ->" button that opens
the lead drawer. Left-edge accent in MR blue. No more duplicate
expansion work on accounts that are already active leads.

Server: `/api/expansion/overview` builds an inverse name->lead
index from the pipeline rows it already pulls; attaches a
`pipeline_match` field per target with lead_id, status, stage,
owner. Client renders the badge + button conditionally.

### v1.0.0ct - Weekly manager report card

New card on the Dashboard view above the KPI strip. Sunday-night
rolling 7-day summary, in-app only (no email yet), per-owner
filter via the existing Dashboard owner picker.

Surfaces:
- Opportunities (new leads created in window)
- Touches (partner notes + lead calls)
- Partner notes, Lead calls (split)
- Stage flips (audit-derived)
- Closed Won / Closed Lost counts
- Top loss reasons in the window

Endpoint `/api/dashboard/weekly-report` reuses
`dashboard.build_dashboard` for touch counts, then layers
`audit.read_events(since=...)` for movement signals. Owner filter
scopes both layers.

## [1.0.0cq] - 2026-05-26 - Note synthesis fixes (qualify-context + sourcing partner)

Two real bugs Ben caught on live:

### 1. Qualify-form notes never persisted to the lead

The `#notes-text` textarea on the qualify view was used only for AI
extraction (MEDDPICC, scope, tech_stack), then thrown away. When
the AE saved the lead and opened the account view, their typed
context was gone. Only the structured extractions made it through.

Fix: after `pushToNotion` succeeds and the lead has a page_id, POST
the raw `#notes-text` content to `/api/calls/<page_id>` as a `note`
typed "Qualification context". This lands in calls_store, shows up
in the Account view's timeline, and feeds the synthesis prompt on
subsequent lead-summary refreshes. partner_source is attached if
the AE marked a sourcing partner via the sourced-for chips.

### 2. Tech-stack extractor mislabelled sourcing partners

When the AE typed "Sourced via Marina at Braze" or "Hightouch is
pitching this for us", the AI extractor would add Braze /
Hightouch to the prospect's `tech_stack` field. Wrong: a referral
partner is a RELATIONSHIP, not part of the prospect's stack. The
prospect might be on a totally different platform.

Fix in three layers:

1. **Prompt update** (`ai_summary.py` TECH_STACK_MENTIONED rubric):
   added a CRITICAL EXCLUSION section with 5 concrete examples
   showing partner-referral patterns and explicitly saying the
   model should NOT include them in tech_stack.

2. **Server-side context injection** (`server.py` `/api/lead/extract`):
   accepts `sourcing_partners` (list, single string, or partner_source
   dict shape). Names get prepended to the user message so the model
   knows what to exclude.

3. **Post-extraction filter** (`ai_summary.extract_from_notes`):
   case-insensitive strip of any sourcing-partner name from the
   returned `tech_stack_mentioned`. Belt-and-braces for when the
   model still slips up. Logged at INFO level.

4 new tests in `test_call_extraction_agencies_tech.py` covering the
filter: explicit exclusion, case-insensitive match, no-op when no
sourcing partner provided, multiple sourcing partners.

### Verified

- 1161 tests pass (4 new, 1157 unchanged)
- node --check on both inline scripts clean
- Server imports clean

## [1.0.0cp] - 2026-05-26 - More industries: MEGS / Consumer Goods / General Business

Ben asked to add: MEGS, General Business, Consumer Goods, Media,
Entertainment, Gaming, Sports, Travel & Hospitality. The last
five already shipped in v1.0.0ac. Added the three new ones.

Final INDUSTRIES (16 values):

```
QSR, C-Store / Gas, Retail, Consumer Goods, Financial Services,
Travel & Hospitality, Healthcare, MEGS, Media, Entertainment,
Gaming, Sports, Telecom, SaaS, General Business, Other
```

Order is intentional:
- Retail-adjacent verticals cluster at the top (QSR through Retail
  and Consumer Goods)
- Financial Services + Travel & Hospitality + Healthcare follow as
  major standalone verticals
- MEGS sits before the four industries it parents (Media,
  Entertainment, Gaming, Sports) so it reads as a grouping rather
  than a sibling
- General Business + Other land at the tail as catch-alls

Same caveat as DACH: production's saved enum_config.json from
earlier customisation overrides defaults, so admins still need to
add MEGS, Consumer Goods, and General Business via Settings →
Dropdowns → Industries.

## [1.0.0co] - 2026-05-26 - DACH region + Dropdowns tab in Settings

Ben asked for two related things:
1. Add DACH (Germany/Austria/Switzerland) to the regions list.
2. Make regions editable.

Regions were already editable via `enum_config_store` but the
editor was buried behind the Settings button inside the Partners
view, which is not where you'd look. Fix in two parts:

### DACH added to default REGIONS

`partner_contacts_store.REGIONS` now ships with DACH at index 1
(right after UK). Cleanly picks up in every dropdown that reads
from the enum config when no user override exists.

Note: production has an existing `enum_config.json` saved with
the previous region list, so DACH won't appear automatically
there. Use the new Dropdowns tab (below) to add it.

### Dropdowns tab on the global Settings page

The chip-list enum editor (previously rendered only into
`#ptn-settings-panel` on the Partners view) is now also rendered
into the global Settings → Dropdowns tab.

Implementation reuses `_renderEnumSettings` cleanly: when the
Dropdowns tab activates, the host element is temporarily
re-id'd to `ptn-settings-panel` so the existing render function
writes into it, then renamed back. Same component, two surfaces.
Both panels are never visible simultaneously so the id swap is
safe.

Covers every editable enum: Industries, Territories, Regions,
Contact statuses, Partner sentiments, Tiers, Seniorities, Sales
stages, Lead statuses.

## [1.0.0cn] - 2026-05-26 - Collapse partner filter row

Ben caught: the Hightouch (and every other) partner detail view
was burying the contact table under 600+ pixels of stacked
filter dropdowns. The 8 enum filters (Territory, Region, Country,
Industry, Status, Sentiment, Tier, Seniority) plus the preset
picker meant you had to scroll past a wall of empty dropdowns to
see contacts.

Root cause: v1.0.0ci's global `select { width: 100% }` made every
dropdown stretch to the full row width. Even though the parent
was `display: flex; flex-wrap: wrap`, each 100%-wide select
forced a vertical stack.

Fix in two layers:

1. **Scoped width override** - new `.filter-row` class wraps any
   filter toolbar. Children get `width: auto`, putting them back
   to natural size so they flow horizontally.

2. **Collapsible panel** - wrapped the 8 enum filters + preset
   row in a `<details>` element. Closed by default. Pill-shaped
   `<summary>` shows "Filters (N active)" with N counted from the
   filter state. Panel auto-opens if any filter is non-empty so
   users can see what's filtered.

Inline actions kept visible: "My contacts" toggle, "Import CSV",
"+ Add contact" stay on the main row.

### Numbers

- Closed state: 75px tall (was ~600px)
- Open state: 212px tall (a 2-row wrap grid of selects)
- 8× space savings when collapsed

### Verified

- node --check on both inline scripts: clean
- Preview MCP: panel opens/closes via click, count text updates
  live as filters change
- Screenshots before/after show the contact table now visible
  above the fold

## [1.0.0cm] - 2026-05-26 - Drop em-dashes (no AI tone)

Per Ben's writing-style memory ("drop em-dashes and the polished
AI cadence for anything externally-shared"). The platform UI
counts. Replaced every em-dash (U+2014) with a regular hyphen
(U+002D) across qualify.html.

533 substitutions. Verified:
- `grep -c "—" qualify.html` returns 0
- DOM `innerText.match(/—/g)` returns null on load
- node --check on both inline scripts: clean
- Visual surfaces (Home KPIs, drawer header, profile picker)
  read natural with hyphens

Note: only qualify.html touched. CHANGELOG entries above this one
still contain em-dashes since that's historical record. Future
entries (this one onward) avoid them too.

## [1.0.0cl] - 2026-05-26 - Dialog z-index above drawer

Ben caught: when flipping a lead to Closed Lost, the "Closing this
lead as lost" reason prompt was being clipped on the right side
by the open lead drawer. The dialog was rendering BEHIND the
drawer, so its visible area shrank to the gap left of the drawer.

Root cause: dialog overlay z-index was 80, drawer is at 90. CSS
stacking ordered them wrong way around.

Fix: bump both dialog overlay z-indexes 80 → 120 so they always
render above the drawer (90), notif-panel (100), and toast (100).

- `_dialogOverlay()` (covers confirmDialog + promptDialog)
- `multiFieldDialog()` (its own overlay)

These are the only two dialog primitive overlays in the file;
all 30+ confirm/prompt sites route through them. Surgical fix.

## [1.0.0ck] — 2026-05-26 — KPI alignment fix

Ben caught a real bug on the live v1.0.0cj build: when one stat
label wraps to 2 lines (e.g. "PARTNER CONTACTS OWNED"), its big
number sits lower than the other cards, breaking the row baseline.

Three complementary fixes:

1. **`.stat-label` reserves 2 lines of vertical space**
   (`min-height: 2.7em`, `line-height: 1.35`, `display: flex;
   align-items: flex-end`). A 1-line and 2-line label now occupy
   the same height; the value below sits at the same Y position
   regardless.

2. **`.stat` is `display: flex; flex-direction: column`** so the
   vertical rhythm is predictable rather than dependent on
   sibling content.

3. **`.stat-delta` also gets a 2-line `min-height`** so cards
   without a subtext line don't collapse shorter than cards with
   one. Whole row stays the same height.

4. **`.stat-grid` bumped from `minmax(180px, 1fr)` to
   `minmax(200px, 1fr)`** so labels have more horizontal room
   and wrap less often. At 1280px main width, 5 columns still
   fit comfortably (5 × 200 = 1000px + gaps).

### Verified

- `getBoundingClientRect().top` on all 5 Home KPI `.stat-value`
  elements → all return `329` at 1440px (perfectly row-aligned)
- All 5 `.stat-label` heights → `30px` (uniform)
- At 1100px the grid wraps to 4+1; within each row, values stay
  aligned at the same Y
- Screenshot before vs after — row baseline restored

## [1.0.0cj] — 2026-05-26 — Inter + warm paper palette

Ben: "It looks the same to me" — for v1.0.0ci, two passes in a row.
Lesson absorbed (see new skill files at `.claude/skills/`): tokens-
only refinement reads as no-change to humans. The platform needed
the two changes humans actually perceive first — **font** and
**background colour** — before any further component polish makes
sense.

### Skills committed (the meta-change)

Three new skill files at `.claude/skills/` capture the postmortem:

- `frontend-design-verify.md` — the verify-before-claim loop:
  boot the Preview MCP, screenshot before + after, refuse to ship
  if the visual diff isn't obvious to a casual glance
- `visible-design-changes.md` — a taxonomy of visible vs.
  invisible CSS axes. "Border shade darker by 4%" is invisible.
  "System font → Inter" is visible. Combine 2–3 from the visible
  column for a perceived redesign.
- `railway-deploy-check.md` — when the user says "same on
  Railway", verify the deploy succeeded BEFORE shipping more CSS.

### The single biggest change: Inter

Switched `--sans` from system-ui to **Inter** (Google Fonts).
Every word on every surface stops looking like a default OS
dashboard. Inter has tighter spacing, taller x-height, more
geometric numerals — the platform now reads as a designed
product, not a Bootstrap default. Mono switched to **JetBrains
Mono** for the same reason.

Inter ships via `<link rel="stylesheet">` with `display=swap` and
preconnect hints so first paint uses system fallback while Inter
streams in. Zero JS risk.

### The second biggest: warm paper palette

Background moved from flat cold grey `#f6f6f6` to warm paper
`#f4f1ea`. Surfaces follow:

- `--surface`: `#ffffff` → `#fffefb` (off-white, sits on paper)
- `--surface-2`: `#f4f4ef` → `#ede9df` (warm tint)
- `--border`: `#e6e6df` → `#d8d3c2` (warm, visibly different)
- `--text`: `#212227` → `#14151a` (sharper on paper)

This is the change Ben asked for. The platform now feels closer
to Notion / Attio / Stripe Dashboard than to a generic admin
template.

### The third: secondary accent

Added `--accent-2` (slate-blue `#3b5b80`, tied to MR brand
swatch) + `--accent-2-soft` / `--accent-2-text`. Single-accent
designs read as "default brand bootstrap"; two accents read as
"designed". Available now in CSS — components will start opting
in via subsequent passes (Refresh / Save view / Export buttons
are the natural first adopters).

### Title version stamp

`<title>` now ends with `· v1.0.0cj`. Future Railway-deploy
verification is one tab-glance: if the version in the browser
tab doesn't match the latest commit, the deploy didn't go
through.

### Verified (this time, properly)

- `mcp__Claude_Preview__preview_start` to boot Flask locally
- `getComputedStyle(body).backgroundColor` confirms
  `rgb(244, 241, 234)` (was `rgb(246, 246, 246)`)
- `getComputedStyle(body).fontFamily` confirms `Inter, -apple-system, ...`
- `document.querySelector('link[href*="Inter"]')` returns the
  stylesheet link
- Screenshots before + after on Home + Partners — visibly
  different (paper-coloured background, off-white cards)
- 1157 tests — 1 pre-existing flake in
  `test_engagement_timeline` (passes in isolation, state-bleed
  in full-suite), unrelated to CSS
- `node --check` on both inline scripts: clean

### Why this should actually register

Inter is the single most-used custom font in modern B2B SaaS.
Side-by-side with system-ui, Inter renders visibly taller and
tighter — characters are obviously different shapes. Combined
with the warm paper background (5+ RGB points difference per
channel, well above perception threshold), this is exactly the
2-axis change my new `visible-design-changes` skill recommends.

### What's still queued (component-level)

Now that font + palette are set, the next pass can polish
components within the new aesthetic:

- Dashboard `By MR owner` / `By partner` tables still have
  uppercase column headers (v1.0.0ci only updated
  `table.stakeholders, table.pipeline` selectors)
- Refresh / Save view / Export buttons could adopt `--accent-2`
- Stat cards could grow optional sparkline glyphs
- Left-sidebar nav remains an option for a future major version

## [1.0.0ci] — 2026-05-26 — Bolder design pass (LoopAI-inspired)

`v1.0.0ch` shipped real refinements but at a scale Ben called out as
invisible ("I don't see any changes"). This pass cranks the dial:
the same conservative-by-default discipline, but every change is
deliberately big enough to register on first glance. Inspiration
from the Dribbble LoopAI CRM B2B SaaS dashboard — generous
whitespace, big numbers, sentence-case everything.

### Surface scale

- `--pad` 22 → 28px (Linear / Stripe breathing room)
- `<main>` 1180 → 1280px wide; vertical padding 28 → 36px
- 14px base font + 1.5 line-height (was a 13/14 mix that read
  cramped)
- Header taller (14 → 18px padding) with thicker blur + saturate
  for a proper sticky-glass feel

### Typography — drop the SHOUTY UPPERCASE

The platform used uppercase + letter-spacing for almost every
section heading, label, and table column. Modern dashboards
reserve uppercase for tiny eyebrows and overlines — everywhere
else reads as sentence-case at proper weight.

- `card h2` 15px uppercase → 18px sentence-case, weight 600
- `card h3` 13px uppercase → 14px sentence-case, weight 600
- Form `<label>` 11px uppercase → 13px sentence-case, weight 500
- Table headers 11px uppercase → 12px sentence-case + subtle
  surface-2 fill + bottom-border
- New `.overline` utility for the few places uppercase is still
  the right call (above big stat numbers)

### Big-number KPIs — `.stat` / `.stat-grid`

The single most "I see it now" change. Home + Dashboard KPI
strips were tiny 22px numbers stuffed into cramped 12px-padding
tiles. Now they render as proper stat cards:

- 32px number, weight 600, tabular-nums
- 11px uppercase eyebrow label above
- Optional `.stat-delta` line below for sub-text / trend
- 22/24 padding, 16px radius, soft shadow
- Auto-fill grid (was a rigid 5-col lock)

Applied to:
- `#home-kpis` — Home KPI strip
- `#db-kpis` — Dashboard KPI strip

### Buttons — gradient + lift

Primary `.btn` now uses a red→darker gradient + brand-tinted
shadow + 1px lift on hover. Reads as an action surface, not a
plain coloured rectangle. Taller too (10/18 → 11/20). Matches the
nav CTA so the visual language is consistent.

- New `.btn.sm` variant for table-row + drawer-header inline
  actions where the larger primary feels heavy
- `.btn.ghost` cleans up — drops the gradient + brand shadow,
  reads clearly as secondary
- `.btn.success` gets the same gradient treatment in green

### Tables — modern CRM look

- Row padding 10/12 → 14/16 (was cramped)
- Header row: muted surface-2 fill, thicker bottom border
- Subtle zebra striping (every other row gets a fractional tint)
  for scannability without obvious banding
- Cleaner hover, last-row border drops naturally
- 13px → 14px row font

### Filters / chips — segmented control feel

`.chip` reads as a proper segmented control now: 8/16 padding (was
6/14), 13px font (was 12), active state drops the brand red for a
subtler "surface + strong border + weight 600" treatment that
matches the LoopAI / Linear filter look.

### Nav buttons

- Bigger tap target (7/13 → 9/16)
- 14px font, weight 500 at rest / 600 active
- Active state: surface-2 fill + border + subtle shadow (was a
  whisper-quiet underline)
- Dropped the SHOUTY UPPERCASE inline filter labels on Dashboard

### Inputs

- Border softened (border-strong → border) + 12px radius
- Padding 10/12 → 11/14 to match label rhythm

### Why this works

The pattern across LoopAI / Linear / Stripe Dashboard / Pipedrive
is the same: bigger surfaces, calmer typography, big numbers when
the data is the point, sentence-case everywhere except true
eyebrows. This pass aligns the platform with that pattern without
changing a single line of JS or a single ID/class wired from the
backend — same render pipeline, modern look.

### Verified

- 1157 tests pass, `import server` clean
- Node `--check` on both inline scripts: clean
- Zero JS / HTML structure change; pure CSS + the KPI card render
  function (which still hands the same data to the same DOM
  parent, just with different classes / fewer inline styles)

## [1.0.0ch] — 2026-05-26 — Design modernization (tokens + key components)

Pure CSS refresh — zero structure change, zero JS touched, every
ID + class preserved. The platform looks more modern without
risking anything functional.

### Token scale

Replaced single-shadow `--shadow` with a layered scale:
`--shadow-xs` → `--shadow-xl`. Each token stacks a tight contact
shadow with a softer ambient diffuse one — surfaces now look "lit"
rather than "cut out". Light + dark themes both get refined values.

Radius scale made explicit: `--radius-xs / sm / (default) / lg /
xl / pill`. Components opt into the right curve by name instead
of hard-coding pixels.

Dark theme borders softened (`#2a2a3a` → `#32323f` border,
matching `#3a3a4d` → `#42424f` border-strong) so cards don't have
that sharp Lego look. Muted text lifted slightly across the board.

### Components polished

- **Cards** — radius 12 → 16, layered shadow at rest, gentle lift on
  hover (was just a border-colour change)
- **Buttons** — dropped the heavy red-glow on hover (felt mid-2010s),
  added a subtle shadow at rest + a tighter brightness shift on
  hover. `.btn.ghost` is cleaner — no shadow until you interact.
- **Inputs** — added a subtle hover state (border darkens) +
  tightened focus ring (3px → 2px). Affordance without busyness.
- **Tags / chips** — softer at-rest, smoother transitions
- **Tiles** — radius bumped, shadow lift on hover
- **Nav buttons** — tighter horizontal spacing, hover now adds
  background tint instead of just colour change
- **+ Qualify CTA** — proper layered red shadow instead of
  brightness-only hover
- **Dialog primitives** (modal overlays) — backdrop now blurred
  (2px) instead of just darkened, dialog radius 12 → 16, shadow
  upgraded to `--shadow-xl`
- **Drawer** — layered edge shadow (sharp contact + diffuse
  ambient) instead of single `-16px 40px`
- **Jeff panel** — same layered shadow + radius treatment
- **Toasts** — radius bumped, shadow upgraded

### What I deliberately did NOT touch

- Layout (no restructuring)
- View structure (Home / Pipeline / Live / Expansion / Directory /
  Partners / Insights / Settings unchanged)
- JS event wiring (every `data-*` attribute, every ID, every class
  the JS depends on is preserved)
- Drawer structure
- Table renders
- Anything outside `<style>` other than 2 inline overlay styles

Pure tokens + component polish. Backend untouched. Full suite:
**1157 passing**. JS syntax clean.

---

## [1.0.0cg] — 2026-05-26 — Shared helpers: json_file_store + contact_cadence

Duplication-audit Phase 1. Extracts the highest-impact shared
primitives the audit flagged. Server.py decorators (the third
audit win) deferred to v1.0.0ch — they're stylistic, not
bug-preventing, and the diff was already large enough.

### `json_file_store.py` — file-store primitives

Single source of truth for `now_iso()`, `new_id()`, `slugify()`,
`safe_id()`, `store_dir()`, `load_list()`, `load_dict()`,
`write_json()`. Module-level `RLock` so all writes share a lock
(per-store locks were over-engineering for low-contention JSON
files).

Migrating a store is a 3-line change — replace the local
`_DEFAULT_DIR` / `_LOCK` / `_now` boilerplate with imports. This
commit migrates only the stores that share cadence logic (since
they're touched anyway); the audit's recommendation to migrate
all 22 stores is deferred — each migration is mechanical but
risky if done en masse. Future commits can adopt as stores get
edited.

### `contact_cadence.py` — touch-cadence engine

`contacts_store.annotate_touch_state` and
`partner_contacts_store.annotate_touch_state` were **byte-identical**.
The contacts-store version even had the comment "Mirror of
partner_contacts_store.annotate_touch_state." Both stores now
re-export from the shared module:

```py
from contact_cadence import (
    parse_iso as _parse_iso,
    annotate_touch_state,
)
```

The shim names are kept so any external caller that imports them
by the old name keeps working. Test confirms `is` identity (real
shim, not copy).

### `partners_store._now()` precision drift — fixed

The audit flagged: `partners_store._now()` returned **microsecond**
precision while every other store returned **second** precision.
A real bug — `updated_at` was inconsistent across the system.
Aligned to second precision; the one test that depended on
microsecond resolution (`test_update_preserves_created_at`) now
sleeps 1.1s before the second save instead of 10ms. Honest tradeoff:
~1s slower test suite for system-wide timestamp consistency.

### Tests

17 new in `test_shared_helpers.py`:
- json_file_store: now_iso seconds precision, new_id length + alphabet,
  slugify, safe_id (accept + reject path-traversal), store_dir env
  override, load_list/dict round-trip, corrupt-JSON graceful
- contact_cadence: contacts_store + partner_contacts_store re-export
  via `is` identity, overdue / never-touched / default-cadence behaviour
- partners_store: _now() now second precision

Full suite: **1157 passing**.

### Deferred to v1.0.0ch (or later)

- Sweep remaining 22 `*_store.py` files to use `json_file_store`
- `server.py` `@json_body` + `not_found_if()` decorators (97 + 138
  call-site simplifications — purely stylistic since the calls all
  work today)

---

## [1.0.0cf] — 2026-05-26 — CSV import for lead + expansion target contacts

v1.0.0bv shipped CSV import for partner contacts. Lead contacts and
expansion target embedded contacts had no bulk-add path until now.

### Refactor: shared `_import_csv_into_store` helper

The partner endpoint was 175 lines; extracting the parsing /
matching / dry-run logic into `_import_csv_into_store` shrank it
to 22 lines and let the two new endpoints reuse the same code.
Each call site supplies four callbacks:

- `list_existing()` → contacts to match against
- `save_one(payload)` → store-specific save
- `normalise_one(payload)` → store-specific shape preview (dry-run)
- `save_error` → exception class the store raises on validation

Plus an optional `allowed_keys` set for stores with narrower
schemas (expansion target contacts only support
name/title/email/source/notes; tier/region/etc. from the CSV are
silently dropped instead of erroring the row).

### New endpoints

- `POST /api/contacts/<lead_id>/import-csv` — bulk-add prospect
  contacts after a discovery call. Full `contacts_store` schema
  including stakeholder_role + cadence.
- `POST /api/expansion-targets/<id>/contacts/import-csv` — bulk-add
  contacts at a greenfield target. Narrower schema; the adapter
  also routes name-matched rows to `update_contact` instead of
  `add_contact` so re-importing the same list doesn't duplicate.

### UI

The CSV import modal (built in v1.0.0bv) refactored to accept a
config object:

```js
openCsvImportModal({
  endpoint:   '/api/contacts/lead-abc/import-csv',
  targetName: 'Shell Loyalty',
  onSuccess:  () => loadLeadContacts('lead-abc'),
});
```

Backward-compatible: passing a partner object (old signature) still
works. New "↑ Import CSV" buttons in:
- Lead drawer → Contacts section (next to Add contact)
- Expansion target detail (next to + Add contact)

### Tests

11 new in `test_contacts_csv_import.py`:
- Lead contacts: dry-run, commit, update-by-name, empty CSV 400,
  row-without-identity errors, stakeholder fields round-trip
- Expansion target contacts: unknown target 404, commit writes
  embedded, narrower schema drops extra fields, update-by-name
  doesn't duplicate, row-without-identity errors

Partner CSV import (20 tests) still passes through the refactored
helper unchanged. Full suite: **1140 passing**. JS clean.

---

## [1.0.0ce] — 2026-05-26 — Multi-tag inline edit (Territory / Region / Industries)

v1.0.0bt added inline single-select cells (Tier / Sentiment /
Seniority). The three multi-tag cells alongside them (Territory,
Region, Industries) stayed display-only — you had to open the
contact form to change them. Closing that gap.

### New primitive: `_renderInlineMultiTagCell` + popover

Renders the current tags as small chips + a hover-only pencil
affordance. Click the cell → popover opens below with checkboxes
for every enum option. Stage your edits, hit **Save** to commit
(PATCH the contact with the new array). **Cancel**, **Esc**, or
click outside discards.

The popover stages changes atomically — you can tick/untick five
options without firing five separate PATCHes. The change-handler
keeps the singular `territory` / `region` alias in sync so any
older reader that consumes `c.region` (not `c.regions[0]`) keeps
working.

### Visual

At rest the cell looks identical to the previous static chip row
(same `tag signal` styling). On hover the cell border + pencil
icon surface so the affordance is discoverable. The popover uses
the same surface / border / shadow tokens as the other modals.

### Backend

No new endpoint — the existing partner-contact PATCH already
accepts `territories` / `regions` / `industries` (allowlisted in
v1.0.0cb). UI just calls it with the new array per save.

Backend untouched. **1129 still passing.** JS syntax clean.

---

## [1.0.0cd] — 2026-05-26 — Multi-prompt chains → modals

v1.0.0bx retired native `window.prompt` but left three flows that
still fired `promptDialog` sequentially — Add Expansion Target
(2 prompts), Add OKR (2 prompts), Add Agency (3 prompts). They
worked but were clunky.

### New primitive: `multiFieldDialog`

Lives next to `confirmDialog` / `promptDialog`. Builds a one-shot
form modal from a fields spec:

```js
const values = await multiFieldDialog({
  title: 'Add expansion target',
  fields: [
    { key: 'name', label: 'Target name', required: true,
      placeholder: 'e.g. Shell UK' },
    { key: 'notes', label: 'Notes', type: 'textarea', rows: 3 },
    { key: 'priority', type: 'select',
      options: ['low', 'med', 'high'], default: 'med' },
  ],
  confirmLabel: 'Add target',
});
if (!values) return;  // user cancelled
```

Supported field types: `text` (default), `textarea`, `email`, `url`,
`select`, `number`. Required-validation with inline error. Esc
cancels, Enter submits (Shift+Enter inserts newline in textareas;
Cmd/Ctrl+Enter submits from a textarea).

### Migrated flows

- **Add Expansion Target** — 2 prompts → 1 modal (added Vertical +
  Notes fields that the prompt-chain didn't expose)
- **Add OKR** — 2 prompts → 1 modal (quarter pre-defaults to the
  current calendar quarter so the user usually just types the
  objective)
- **Add Agency** — 3 prompts → 1 modal (type field is now a
  proper select instead of a free-text prompt)

### What's NOT touched

Editing flows (`_editAgency`, `_editOkr`) still use `promptDialog`.
They could migrate too, but the edit paths are lower-frequency and
each needs slightly different field rules — defer to when someone
actually hits them.

Backend untouched. Full suite: **1129 passing**. JS syntax clean.

---

## [1.0.0cc] — 2026-05-26 — Jeff KB editor + loss-reason Dashboard card

Two items from the "anything I missed?" list.

### #5 — Jeff KB editor in Settings

`/api/jeff/knowledge` GET + PUT have existed since v1.0.0bs but
needed a UI. New `Settings → Jeff KB` tab: full-width markdown
textarea, Reload / Save buttons, status line showing char count +
whether Jeff is currently on. Lazy-loads the first time the tab
opens. Edits take effect on the next chat turn — no deploy needed.

### #13 — Top loss reasons on the Dashboard

After v1.0.0ca's Closed Lost flow captures `close_reason`, the team
needed the aggregation. New endpoint:

- `GET /api/dashboard/loss-reasons?limit=N` — buckets Nurture +
  Rejected leads by their close_reason (case + whitespace
  normalised so "Budget pulled" and "budget pulled" merge), ranked
  by count, tie-broken by recency

New Dashboard card surfaces the top 10. Each reason shows count +
up to 3 clickable lead chips that open the lead drawer. Totals
strip shows closed count / with-reason / without-reason so the
team can see how often they're forgetting to capture a reason.

`_row_from_page` (Notion pipeline mapping) now includes
`close_reason` so the aggregator doesn't need a second fetch per
lead.

### Tests

8 new in `test_loss_reasons.py`: empty pipeline, active leads
excluded, case-insensitive bucketing, sort by count desc,
missing-reason counted separately, limit clamping, lead-preview
cap at 5, Notion-outage graceful fallback.

Full suite: **1129 passing**.

---

## [1.0.0cb] — 2026-05-26 — Small wins bundle

Five small items from the "anything I missed?" review, each too
trivial for its own commit but coherent as a group.

### #9 — Engagement scoring excludes Nurture + Rejected

Three places in `server.py` used `status not in {"Disqualified",
"On Hold", "Closed Lost"}` to filter the "needs attention" list +
related at-risk computations. After v1.0.0ca added Nurture +
Rejected, those statuses were getting flagged for low engagement
when by definition they're not in active rotation. Extended the
exclusion set to `{Disqualified, On Hold, Closed Lost, Nurture,
Rejected}` everywhere.

### #11 — Drawer-header inline stage + status edit

Status chip in the drawer header is now an inline `<select>`
(hydrated from `/api/settings/enums`). Same for a new Sales Stage
chip. Click → native dropdown → on change, mirrors into the form's
`[data-ld]` select and fires an input event so the existing dirty
state + saveLead flow (incl. the Closed Won/Lost workflows) picks
it up. No new save code path. Removes the friction of opening the
collapsed Qualification accordion just to change status.

### #12 — Settings → Integrations clearer AI hint

The AI (Claude) row previously said "Note synthesis + contact
extraction" — accurate when first written, but Jeff + news
relevance scoring also depend on the same key now. Updated hint:
"Powers Jeff, note synthesis, contact extraction, account-news
relevance scoring. Set ANTHROPIC_API_KEY in Railway → Variables."

### #7 — Three low-sev security items from the audit

- **Partner mass-assignment allowlist** — `/api/partners/<id>` and
  `/api/partners/<id>/contacts/<id>` PATCH endpoints used
  `{**existing, **body}` with no input filter. Client-submitted
  keys like `created_at`, `id`, or arbitrary fields would silently
  merge into the stored record. Added explicit allowlists
  (`_PARTNER_PATCH_FIELDS`, `_PARTNER_CONTACT_PATCH_FIELDS`) and a
  shared `_filter_body()` helper.
- **Jeff context value cleaning** — values flowing into the system
  prompt from `context.lead.vertical` etc. are now stripped of
  newlines, leading markdown control chars, and capped at 120
  chars. Defends against `"\n\n## SYSTEM OVERRIDE: …"`-style
  injection.
- **Google News response body redacted from logs** — was
  `resp.text[:200]` which can echo the query (company name) into
  log destinations we don't fully control. Now status code only.

### #10 — `filter=all` preset migration

No code change. Just noting: existing saved presets with
`filter=all` still mean "literal all rows" (including Nurture +
Rejected), so a long-time user's preset shows MORE rows than the
new "In pipeline" default. They'll only notice if they re-save the
preset. Worth a heads-up in any team comms about v1.0.0ca.

### Tests

5 new in `test_security_hardening.py`:
- Partner PATCH strips arbitrary keys + spoofed `created_at` / `id`
- Partner-contact PATCH same
- Jeff context: newlines stripped (no SYSTEM OVERRIDE injection)
- Jeff context: long values truncated to 120 chars
- Jeff context: leading markdown chars stripped

Full suite: **1121 passing**.

---

## [1.0.0ca] — 2026-05-26 — Editable stages + Closed Won/Lost/Rejected lifecycle

### The ask

> "Should be able to edit the sales stages. e.g. There should be a
> closed lost opportunities and closed won. Once closed won, there
> should be a prompt to move it to live. Once closed lost it should
> be moved to nurture list so it isn't in pipeline for us to review.
> There should be a rejected list which wouldn't put them in the
> nurture list."

Four asks bundled together — editable stages, new closed values,
nurture flow on Closed Lost, separate Rejected list. Plus three
edge cases Ben picked: reversibility, audit tracking, reason capture.

### Model

Two enums on a lead now, with these defaults (admin-editable):

**Sales stages** (deal motion): Intro Call → Discovery → Technical
Fit → Proposal → Negotiation → Legal/Procurement → Verbal Commit →
Signature → **Closed Won** → **Closed Lost**.

**Lead statuses** (lifecycle): New / Researching / Qualified /
Disqualified / On Hold / **Nurture** / **Rejected**.

`Disqualified` (didn't meet ICP) stays distinct from `Rejected`
(we decided not to pursue) — same outcome from a visibility
standpoint but very different signal.

### Three new workflows on Save

1. **`sales_stage → Closed Won`** — post-save, the Promote-to-Live
   modal auto-opens with the composed name ("Shell — CRM Build")
   prefilled. User confirms to create the live project or cancels.

2. **`sales_stage → Closed Lost`** — pre-save reason prompt
   ("Why? Helps the team build a loss-reason dataset"). On confirm:
   reason saved to `close_reason`, status auto-flips to `Nurture`
   so the lead leaves the active pipeline view. Cancel aborts the
   save entirely (no half-flip).

3. **`status → Rejected`** — pre-save prompt with OPTIONAL reason.
   Lead moves to the Rejected list, out of every active surface.
   Reversible by changing status back.

### Pipeline view restructured

New filter chips: **In pipeline** (default — excludes Nurture +
Rejected + Disqualified), Qualified, Borderline, Qualified Out,
**Nurture**, **Rejected**, All. The default Pipeline view is now
genuinely "what should I be working today" — Nurture and Rejected
leads have explicit chips for when you want to scan them.

### Editability

`enum_config_store` extended to accept lead-side enums alongside
the existing partner-side ones. `Settings → Customise dropdowns`
panel surfaces **Sales stages** + **Lead statuses** as two new
editable cards. Lead drawer's Status + Sales Stage `<select>`
elements hydrate from `/api/settings/enums` on init, so admin
edits flow through without a code change. Static `<option>` HTML
stays as the SSR-friendly fallback.

### Notion

- Status select mapping extended to accept `Nurture` and `Rejected`
- New `close_reason` rich-text field round-trips through `update_page`
  ↔ `_page_to_detail`
- Boot self-heal includes `Close Reason` property so freshly-cloned
  Notion DBs get the column automatically

### Reversibility (Ben's edge-case pick)

Moving a lead OUT of Nurture / Rejected is just changing status
back to Researching / Qualified / whatever. No state-machine
gates. The audit log captures both directions via the existing
`lead_updated` event (with the changed fields list).

### Tests

12 new tests in `test_lead_lifecycle.py`:
- Constants extended (sales_stages + lead_statuses)
- enum_config_store surfaces both, admin save round-trips
- /api/settings/enums returns both keys
- Notion status mapping accepts Nurture + Rejected
- `close_reason` writes as rich-text + round-trips via page-detail
- Boot self-heal spec includes Close Reason at both call sites

Full suite: **1116 passing**. JS syntax check clean.

---

## [1.0.0bz] — 2026-05-25 — Security pack: 1 High + 4 Mediums

Run-through-the-codebase security audit found one High-severity
information disclosure + four Medium-severity hardening gaps. All
five fixed in this commit. No Criticals — auth is correctly gated,
no RCE / SQLi vectors, no unsafe deserialisation, secrets aren't
logged.

### High — stack trace exposed to client

`/api/qualify` returned `traceback.format_exc()` in the JSON
response when the handler crashed. Auth-gated, so external
attackers couldn't reach it, but any logged-in user (or XSS-pivoted
attacker) got file paths, line numbers, and frame locals — exactly
what's useful for planning follow-on exploits. The full trace stays
in `log.exception` + audit; the client just gets the short error
message. (`server.py:234`)

### Medium — CSV formula injection in pipeline export

A lead named `=cmd|'/c calc'!A1` or `@SUM(...)` would execute when
an analyst opened `pipeline.csv` in Excel or Google Sheets — the
classic CSV injection. Added `_csv_safe()` helper that prefixes
cells starting with `=`, `+`, `-`, `@`, tab, or CR with a single
quote. Excel hides the leading quote when rendering, so visible
output is unchanged for safe values. (`server.py:1588-1623`)

### Medium — no MAX_CONTENT_LENGTH cap

Flask happily JSON-parsed multi-MB bodies on every POST/PATCH
endpoint. An authenticated abuser (or hijacked session) could DoS
the Railway dyno or fill the persistent volume with repeated large
writes. Now capped at 4MB (`MAX_CONTENT_LENGTH` env var to
override). 413 on oversize. (`server.py:82-90`)

### Medium — path-traversal latent in three stores

`expansion_targets_store`, `live_projects_store`, and
`live_project_okrs_store` all wrote files at
`cache/<dir>/{id}.json` with the raw ID. Flask's URL converter
blocks `/`, so URL-route exploitation wasn't possible today — but
any future code path (e.g. a bulk-import endpoint) that called
`_path` with non-URL-sourced data could escape the cache dir. Added
a strict `_safe_id()` guard in each that rejects anything outside
`[A-Za-z0-9_-]{1,64}`. (3 store files)

### Medium — CORS wildcard + token-in-query

`CORS(app)` allowed any origin to read responses, and the auth
layer accepted `?token=<secret>` in the query string. Query tokens
end up in: server access logs, browser history, the `Referer`
header (so any outbound link from the app leaked the token to the
third party). Now:

- CORS pinned to env-configured origins (`CORS_ORIGINS` comma
  list), with explicit opt-in for permissive (`CORS_ALLOW_ANY=1`).
  Production default is same-origin only.
- Query-string token rejected by default. Set
  `AUTH_TOKEN_ALLOW_QUERY=1` to opt back in for any legacy tooling.
  (`server.py:82-110, 121-152`)

### Tests

11 new tests in `test_security_hardening.py` — one regression test
per fix. Mocks the Anthropic / Notion boundary so the pure
hardening behaviour is what's pinned.

Backend-only change. Full suite: **1104 passing**.

---

## [1.0.0by] — 2026-05-25 — Promote-to-Live name = "Company — Opportunity Type"

### The ask

> "Promote live should take the existing pipeline name and then use
> the type of project to be listed in the live area"

Live Projects list used to show bare company names. So when the
same anchor account had multiple workstreams over time — Shell
finishes a CRM Build, then starts a Retention engagement — every
row read "Shell" and you couldn't tell them apart at a glance.

### Fix

New naming convention: **`<company> — <opportunity type>`**

- "Shell North America — CRM Build"
- "Popeyes — Retention"
- "BP — Migration"

### Where the composition happens

A single helper, `_compose_live_project_name(company, opp_type)`,
lives in `server.py` and is mirrored in `qualify.html` as
`_composeLiveProjectName()`. Same logic both sides:

- Both set → `"<company> — <opp>"`
- Opp type missing or "Unknown" (case-insensitive) → bare company
- Company missing → bare opp
- Both missing → fallback (the `lead_id` server-side)

Trims whitespace on both inputs.

### Plumbing

- **Server**: `/api/lead/<id>/promote-to-live` reads
  `opportunity_type` from the Notion page and uses the composed
  name as the default. Explicit `body.name` still wins (UI can
  override), so the contract stays symmetric.
- **UI**: Lead drawer's Promote button now passes
  `lead.opportunity_type` through to `_promoteLeadToLive`, which
  pre-fills the new modal prompt with the composed default. User
  can still edit it before confirming.
- **Prompt itself** also got upgraded to the options-object form
  (added in v1.0.0bx): proper title, label, placeholder, "Promote"
  confirm button — was a bare one-liner before.

### Tests

4 new in `test_live_projects.py`:
- Default composes from opportunity type
- "Unknown" opp falls back to bare company
- Explicit body name overrides default
- Direct unit test on the helper covering the matrix (both set,
  missing, blank, "Unknown", whitespace, fallback)

Full suite: **1093 passing**. JS syntax check clean.

---

## [1.0.0bx] — 2026-05-25 — In-app dialog primitives; native prompt/confirm retired

### The pattern problem

After Ben caught the Settings → Edit user flow stalling (browsers
suppress repeat `window.prompt()` calls), it was obvious the same
problem hid behind every other dialog in the app. **68 native
prompt/confirm calls** scattered across Expansion, Live Projects,
Project Build criteria editor, partner contacts, account watchlist,
Jeff, filter presets, etc. All of them subject to the same browser
throttling, all visually inconsistent with the rest of the platform,
none keyboard-friendly beyond the OS defaults.

### Primitives

Two promise-returning helpers in `qualify.html`:

```js
await confirmDialog('Delete this contact?')
await confirmDialog({ title: 'Delete?', message: '…', danger: true })

await promptDialog('New name', 'Old name')
await promptDialog({ title: 'Rename', label: 'New name',
                      default: 'Old', placeholder: '…' })
```

- **Drop-in-friendly signatures**: bare string OR options object,
  so the mechanical sweep was a one-line code change at each call
  site (just adding `await`).
- **Single recycled overlay** (`#mr-dialog-overlay`) — only one
  dialog open at a time. Opening a second cancels the first.
- **Esc cancels, Enter submits**, focus + select-all on the input
  for prompts so a single keystroke replaces the default.
- **Danger variant** (`danger: true`) renders the confirm button
  in MR red for destructive actions.
- **Click-outside cancels** without needing the Cancel button.
- Exposed on `window` for ad-hoc / console use.

### The sweep

- All 27 `window.confirm(...)` → `await confirmDialog(...)`
- All 41 `window.prompt(...)` → `await promptDialog(...)`
- 7 enclosing handlers converted to `async` (4 named functions, 1
  setTimeout callback, the `_jeffClear` helper, and
  `_bulkPickFromEnum`)
- Syntax-checked the whole 612KB inline JS via `node --check` —
  zero errors

### Out of scope (for later)

The **multi-prompt chains** (Add expansion target with 4 prompts,
Add OKR with quarter+objective+KR, Add agency with name+scope+type+contact)
still call the new `promptDialog` sequentially. They work — no
browser throttling now — but they're still a UX wart. Each deserves
a feature-specific modal (like Settings Edit got in v1.0.0bw, or
the CSV import modal in v1.0.0bv). Will pick them off as Ben
hits the friction.

Backend untouched. Full suite: **1089 passing**.

---

## [1.0.0bw] — 2026-05-24 — Fix: Settings → Edit user is now a real modal

Reported: "Edit didn't work" on the Settings → Users page.

The v1.0.0bq implementation fired **four sequential** `window.prompt()`
dialogs (Name → Role → Region → Email). Browsers throttle / suppress
repeat prompts after a few — so Edit visibly stalled mid-flow with no
explanation, looking broken. Add was the same shape and same problem.

Replaced both with a proper modal:
- One screen, all four fields visible
- Validation (Name required, inline error chip)
- Cancel / Save buttons + Esc to close + Enter to submit
- Save button shows spinner during the PATCH
- Backend errors surface as the inline error (instead of dying as
  a toast that disappears in 4 seconds)

Both Add and Edit now share the same modal — single source of truth,
single submit path. `_addSettingsUser` / `_editSettingsUser` are thin
shims so the existing button wiring + call sites didn't have to
change.

Backend untouched — pure UX fix. Full suite: **1089 passing**.

---

## [1.0.0bv] — 2026-05-24 — CSV import for partner contacts

### The ask

After hand-running the 6-contact EMEA Hightouch batch through a
one-off script, Ben asked for a real bulk-add path. Sales teams add
rosters of 10+ partner contacts at a time — typing one-at-a-time
through the contact form is the wrong shape of UX.

### What's new

**+ Import CSV** button on every Partner detail page, next to
**+ Add contact**. Opens a modal with three steps:

1. **Upload** — file picker (drag a `.csv` in), or paste CSV into a
   textarea. A "Download template" button gives a pre-filled
   single-row CSV covering every supported field, so users see the
   schema instead of guessing.
2. **Preview** — server parses + returns a per-row plan: add /
   update / error. Summary strip shows totals (X to add, Y to update,
   Z errors). Unknown column headers surface as a warning so typos
   get caught before commit.
3. **Commit** — same endpoint, `dry_run: false`. Returns the result
   shape + the partner detail re-renders so new rows are visible
   immediately.

### CSV shape

- **Required**: at least one of `name` or `email`
- **Optional headers** (with synonyms — case + space + underscore
  insensitive): `title`/`role`, `country`, `city`, `region(s)`,
  `territory(ies)`, `industries`, `tier`, `sentiment`, `seniority`,
  `mr_owner`/`owner`, `linkedin_url`/`linkedin`, `phone`, `tags`,
  `status`, `cadence_days`
- **Multi-tag cells** (regions, territories, industries, tags):
  comma, pipe, or semicolon separator. Excel exports vary; all three
  work
- **City** is preserved in `tags[]` since the schema has no
  first-class city field — no information lost
- **UTF-8 BOM tolerated** (Excel saves them by default)

### Update mode (per Ben's pick)

When a CSV row matches an existing contact by name (case-insensitive)
OR email, the existing row is **updated** with the CSV's non-empty
fields. Empty CSV cells **do not** overwrite existing data — so
"bulk-update titles" works without wiping every other field on those
rows. Intra-CSV duplicates (same name twice) collapse to the last
row's values, preventing accidental twins.

### Architecture

- `POST /api/partners/<partner_id>/contacts/import-csv` — one
  endpoint, `dry_run` flag controls write
- Header normalisation: `_csv_normalise_header()` lowercases,
  underscores, applies the synonym table
- Multi-tag splitting: `_csv_split_multi()` on comma/pipe/semicolon
- Match-then-merge: snapshot the roster once, build name + email
  indexes, classify each row before writing
- Successful commits emit `partner_contacts_csv_import` audit events

### Tests

20 new tests in `test_partner_contacts_csv_import.py`:
- Dry-run vs commit behaviour
- Header synonyms + case-insensitive + space-tolerant
- Unknown-header warnings
- Multi-tag splits (all three separators)
- City → tags
- Update by name OR email match
- Empty cells preserve neighbours (the headline contract)
- Intra-CSV dupe collapse
- BOM tolerance
- End-to-end with the actual Hightouch EMEA roster

Full suite: **1089 passing**.

---

## [1.0.0bu] — 2026-05-24 — Fix: inline Tier cells rendering blank

Ben caught a v1.0.0bt regression: the Tier column was showing as an
empty pill instead of the value. Three bugs compounding:

1. **Inline `style="background:..."` was a shorthand**, which CSS-resets
   `background-image` to none. That killed the dropdown-arrow gradient
   defined in the stylesheet. (Sentiment hid it under its coloured
   pill so the bug only stood out on Tier's plain styling.)
2. **No `min-width` on the cell** — in a narrow column the select
   shrunk until the text got clipped to invisible. The same pattern
   `select.inline-owner-cell` solved this with `min-width: 130px`;
   we'd just forgotten to copy it.
3. **Legacy values weren't surfaced** — if a contact's tier wasn't in
   the current enum list (e.g. an admin removed an option, or the
   value was set before the enum was tightened), the select rendered
   blank. Now the helper detects the mismatch and injects a synthetic
   `<option>` labelled "(legacy)" so the value stays visible and the
   user can keep or replace it.

Fixes:
- CSS: `background-color` (not `background`) in the inline style +
  `min-width: 90px` + `text-overflow: ellipsis` + `overflow: hidden`.
- JS: synthetic legacy option, change handler also uses `backgroundColor`
  not `background`, hover tooltip refreshes on save.

Full suite: **1069 passing**, same coverage as v1.0.0bt — the bug
was purely in styling/rendering, not behaviour.

---

## [1.0.0bt] — 2026-05-24 — Inline-edit Tier / Sentiment / Seniority in Partners table

### Reported

> "Should be able to change these with the drop down without having
> to go into the contact."

Ben sent a screenshot of the Partners contacts table — every row
in the TIER / SENTIMENT / SENIORITY columns showing dashes — making
the point that editing required opening each contact's form
individually. For a team triaging dozens of partner relationships,
that's a real friction.

### Fix

Those three cells now render as inline `<select>` dropdowns. At
rest they look identical to the previous static badges (sentiment
keeps its colour palette, tier keeps its `tag signal` look,
seniority stays muted). On hover the cell gets a subtle outline so
the affordance is discoverable. On change:

1. PATCH `/api/partners/<pid>/contacts/<cid>` with just the
   changed field
2. Optimistic local update — the partner-contact object in memory
   gets the new value so any later re-render doesn't flash stale
3. Background re-style for the cell's badge colour
4. Subtle "Saved" toast confirmation
5. On failure: revert to the previous value + show the error

The empty option in each dropdown is labelled `—` so the same
control doubles as a clear action (no separate "remove" button).

### Why a native `<select>` over click-to-edit

- Keyboard navigation + screen-reader semantics for free
- One canonical interaction pattern — no separate "edit mode"
  toggle to maintain or get out of sync
- Selecting `—` clears the field; no awkward second affordance

### Backend

`/api/partners/<partner_id>/contacts/<contact_id>` PATCH already
existed; the inline UI just calls it with a single field. The
merge logic preserves all other fields on partial updates — pinned
by 8 new tests so we don't regress that contract:

- Single-field PATCH for tier / sentiment / seniority each
  preserve every neighbour (industries, email, country, mr_owner)
- Clearing a value with `null` or `""` normalises to `None`
- Rapid sequential edits (three back-to-back) accumulate correctly
- Unknown contact ID returns 404

Full suite: **1069 passing**.

---

## [1.0.0bs] — 2026-05-24 — Jeff: in-app pricing + scoping assistant

### The ask

Pricing is the #1 point of friction in MR's sales cycle. AEs forget
which rate card applies, can't remember when to add Project Ops vs
Contingency, freeze when a client pushes back on $200/hour. They
need a "phone a friend" surface that knows MR's pricing model + the
team's best-practice playbook + the current deal context.

### Jeff

A floating button (bottom-right, MR red, marked **J**) on every
view. Click → chat panel slides up.

**What Jeff knows**

Two sources, by design:

1. **Pricing facts** — read live from `pricing.py` + `rate_cards.py`
   on every turn: blended rate, hours per FTE-month, default phase
   split, available rate cards, team templates per project type.
   The factual ground truth — drifting from it would immediately
   make Jeff wrong, so it's never cached.
2. **Best-practice guidance** — admin-editable markdown at
   `knowledge/pricing_best_practices.md`. Covers project-type
   selection, rate-card decisions, contingency policy, common client
   objections + responses, common AE mistakes, escalation paths.
   Editable in the UI (Settings — Jeff KB tab coming v1.0.0bt).

**Skill-aware**

The chat header has a Beginner / Intermediate / Expert dropdown
(persists in localStorage). The skill level translates into a
verbosity + jargon instruction in the system prompt:

- Beginner — explains terminology, walks through step by step,
  prefers worked examples
- Intermediate (default) — assumes basics, focuses on tradeoffs
  and the *why* behind recommendations
- Expert — terse, technical, surfaces edge cases without
  restating fundamentals

**Context-aware**

Jeff sees the user's current view, the open lead (company /
vertical / opportunity type / region / deal size), and the
in-progress pricing config from Project Build (rate card / months
/ project ops % / contingency %). Lets him say "for THIS Shell
deal, given you've already picked crm_build…" rather than generic
advice.

**Conversation UX**

- Markdown-rendered replies (paragraphs, bold, italic, code, lists,
  H3) — tiny in-house renderer so we don't pull a markdown lib
- Enter sends, Shift+Enter inserts a newline
- Esc closes the panel
- Clear button wipes the conversation
- 4 starter prompts shown on empty state to reduce blank-page
  hesitation
- History capped at the last 20 turns server-side so a long
  conversation doesn't blow the context window

**Architecture**

- `jeff_knowledge.py` — system prompt builder. Pure, no I/O beyond
  reading the KB file
- `knowledge/pricing_best_practices.md` — seeded with MR's
  current playbook
- `POST /api/jeff/chat` — body: `{messages, skill, context}`,
  returns `{message}` or error code. Honest disabled-mode response
  (503 `jeff_disabled`) when ANTHROPIC_API_KEY isn't set
- `GET /api/jeff/knowledge` / `PUT /api/jeff/knowledge` — admin
  edit surface
- Model: `claude-sonnet-4-5` (override via `JEFF_MODEL` env)

**Out of scope for v1**

Jeff answers; he doesn't yet *do*. Form-filling, value suggestion,
quote generation — these are v2 surfaces once the chat shape is
proven. Easier to add capability than walk it back.

### Tests

32 new tests in `test_jeff.py`:
- Prompt builder: identity, skill framing (all 3 levels + unknown
  fallback), pricing facts pulled from `pricing.py`, context block
  rendering, KB merge, round-trip read/write
- `is_configured()` truth table (missing / blank / set)
- Chat endpoint: 503 when disabled, 400 on missing/empty messages,
  happy path, system prompt carries skill + context, message
  normalisation (role coercion + 8000-char cap), 502 on upstream
  failure, last-20-turns cap
- KB endpoints: empty default, round-trip, non-string rejection,
  clear via empty string

Full suite: **1061 passing**.

---

## [1.0.0br] — 2026-05-24 — Directory: accounts + contacts cross-store roster

### Why

Until now there was no single place to answer "who do we know at
X?" or "show me every contact we have across MR." Lead contacts
lived per-Notion-lead, partner contacts lived per-partner, agency
contacts were embedded inside lead agencies, expansion target
contacts were embedded inside targets. Each surface was good at
its job; none of them gave you a roster.

### What's new

A **Directory** nav item between Expansion and Partners opens a
view with two tabs:

**Accounts tab** — every account we have data on, deduped by
lead_id where possible:
- Pipeline leads from Notion
- Expansion target anchors that aren't yet in the pipeline get
  synthetic rows (kind = `expansion_target_orphan`) so the team's
  early-stage research stays visible even before the lead exists
- Each row enriched with: has-live-project flag + status, expansion
  target count, contact count

**Contacts tab** — every person we know, with source attribution:
- `lead` — contacts_store (per Notion lead)
- `partner` — partner_contacts_store (Braze/Snowflake/etc rosters)
- `agency` — embedded in lead_agencies_store (concurrent agencies
  on live deals)
- `expansion` — embedded in expansion_targets_store (contacts at
  greenfield accounts)
- Colour-coded source pills so the user can scan and tell at a
  glance who's a partner-side contact vs deal-side
- Lead contacts carry their stakeholder_role (champion / blocker /
  sponsor) so the directory doubles as a high-level stakeholder map
- Row click on lead contacts opens the lead drawer

Both tabs share a debounced search box (filters by name / email /
title / company / vertical / owner). Contacts tab also has source
filter chips (All / Lead / Partner / Agency / Expansion).

### Resilience

Both aggregators degrade gracefully when Notion is unreachable —
local stores (live projects, expansion targets, partner contacts,
agency contacts) still surface so the directory isn't a blank page
during a pipeline outage. The lead-source company-name resolution
uses a slug round-trip so `shell_na` on-disk maps back to `Shell`
in the UI.

### Architecture

- `GET /api/directory/accounts?q=…` — anchor-aware aggregate
- `GET /api/directory/contacts?q=…&source=…` — cross-store contact roster
- Per-source totals + grand totals on both endpoints so the UI can
  render the counts strip without re-walking the data

### Tests

24 new tests in `test_directory.py` covering:
- Account aggregation: pipeline → list, live-project enrichment,
  expansion-target enrichment, contact-count enrichment, orphan
  anchors, query filter on name/owner/vertical, Notion-failure
  resilience, alphabetical sort
- Contact aggregation: all four sources surface independently and
  combined; lead contacts carry stakeholder_role; partner contacts
  carry partner name; agency contacts get "agency (via lead)"
  format; expansion contacts carry target name; query filter on
  name/email/title; source filter; agency contacts without names
  skipped; Notion-failure resilience

Full suite: **1029 passing**.

---

## [1.0.0bq] — 2026-05-24 — Settings view + writable users + utility strip

Ben asked for two things back-to-back: a place to edit users from the
UI rather than from `mr_owners.py`, and the integration-status strip
made always-visible instead of buried at the right edge of a crowded
nav row. This commit ships both.

### Settings view (new top-nav surface)

A gear icon between Insights and the + Qualify CTA opens a Settings
view with two tabs:

- **Users** — full CRUD on MR teammates. Add, rename, edit role /
  region / email, deactivate (preserves the row so historical
  `lead.owner = "Old Name"` references still resolve), or
  hard-delete. The list is the same one that drives every owner
  dropdown across Pipeline / Qualify / Lead drawer / Partner
  contacts, plus the profile picker.
- **Integrations** — read-only status for Apollo / Notion / AI
  (Claude) / HubSpot. One row per service with the env-var hint so
  an admin can wire credentials in Railway without grepping docs.

### Writable owners store

`mr_owners.py` used to be hard-coded — every roster change required
a code edit + Railway deploy. We now persist owners as JSON in
`cache/mr_owners/owners.json` via `mr_owners_store.py`, seeded from
the existing 12 names on first read so the upgrade is invisible.
`mr_owners.list_owners` / `get_owner` / `names` / `OWNERS` all
delegate to the store — every caller (notifications, dropdowns,
scoring) sees live edits without an import change. Endpoints:

- `GET /api/settings/users` — admin list (includes inactive)
- `POST /api/settings/users` — create
- `PATCH /api/settings/users/<id>` — edit any field, including
  `active` toggle
- `DELETE /api/settings/users/<id>` — hard delete
- `GET /api/owners` — unchanged read-only public surface
  (active-only, used by every dropdown)

All mutations audit-logged
(`settings_user_{created,updated,deleted}`).

### Utility strip

The integration health pills + theme toggle now live in a thin
sticky bar above the main nav. Always visible, never wraps, never
gets pushed off-screen on smaller windows. The main header sticks
from below the strip so the visual stack stays clean.

### Tests

34 new tests in `test_settings_users.py`:
- Store CRUD + seed-on-first-read + ordering preserved
- Rename / duplicate-name rejection / case-insensitive lookup
- Deactivated owners still resolve via `get_owner` (audit trail
  safety)
- `mr_owners.py` shim backward-compat
- Endpoint contracts (GET / POST / PATCH / DELETE + 400 / 404 paths)
- `/api/owners` still returns active-only after deactivation

Full suite: **1005 passing**.

---

## [1.0.0bp] — 2026-05-24 — Click-to-edit account name + honest partial-save reporting

### The bug

Ben reported: "Still can't edit account names."

Two things were going wrong, only one of which was a bug:

**UX bug**: the `Company` input lived inside the `Identity` accordion
section — which is collapsed by default. Users opened a lead drawer,
saw the company name at the top of the header, and tried to click it
to rename. Nothing happened, because the title was a static `<div>`.
Nobody thought to scroll down, find a collapsed section, expand it,
edit a labelled input field, then hit Save.

**Latent silent-failure**: the missing-property recovery added in
v1.0.0aq dropped Notion properties without surfacing the drop to
the caller. If a save legitimately couldn't write `Company` (or
anything else), the user got a green "Saved" toast and the rename
never landed. Hadn't bitten yet — but would the first time anyone
ran the platform against a freshly-cloned Notion DB.

### Fix

**Click-to-edit on the drawer title.** Click `#ld-title` → swaps to
an inline input → Enter or blur commits, Esc reverts. The committed
value mirrors into the hidden `[data-ld="company"]` field and fires
the `input` event, so the existing dirty-state + `saveLead` flow
handles persistence. Single source of truth — no separate code path
to keep in sync. Hover affordance: dashed border + pencil hint
("✎") so the affordance is discoverable without a docs lookup.

**Honest partial-save reporting.** The recovery now returns
`(page, dropped_property_names)` and loops through ALL missing
properties in one save (previously it retried once and gave up if a
second property was also missing). `update_page` surfaces
`dropped_props` in its response; the PATCH endpoint forwards it
verbatim + writes it to the audit log so a partial save is a
permanent, queryable record. The drawer's Save handler shows a red
toast when any property was dropped — "Save partially failed — your
Notion DB is missing these columns: X. Restart to auto-add them, or
add them manually in Notion."

### Tests

4 new tests in `test_notion_missing_property_recovery.py`:
- Recovery loops through multiple missing properties in one save
- Full-success path returns `dropped == []` (not `None`)
- `update_page` surfaces `dropped_props` end-to-end
- `dropped_props` key omitted when nothing dropped (no empty-list
  noise for clean saves)

Existing 6 recovery tests updated to unpack the new `(page, dropped)`
return tuple. Full suite: 971 passing.

---

## [1.0.0bo] — 2026-05-24 — Account expansion: land-and-expand view

The team's motion isn't "win once, walk away" — it's "win Shell
North America, then work Shell UK, Shell EMEA, Shell APAC." Until
now the platform had no surface for that pre-qualification research.
Expansion targets sat in someone's head or a side-doc, and the
hand-off from "we know there's an opportunity" to "this is now a
real lead in Notion" had no system of record.

### What's new

A dedicated **Expansion** view (top nav, between Live and Partners)
shows every landed account ("anchor") and the expansion targets
mapped to it. Each target captures:

- **Region / vertical** — Shell UK, Shell EMEA, Popeyes Canada
- **Status** — `greenfield` → `researching` → `qualifying` →
  `converted_to_lead` (or `dropped`)
- **Contacts** — full CRUD with name / title / email / source
  ("via Marina at Braze") so the team can map relationships
  before there's a deal
- **Notes** — free-form intel, hand-off context, blockers
- **Convert** — promotes a target into the Qualify flow, then
  marks the target `converted_to_lead` with a reference to the
  new lead's page_id so the lineage stays intact for audit

### Why a separate store (not the lead pipeline)

Targets aren't leads yet. Forcing them through the qualified-lead
pipeline before they're ready would pollute pipeline metrics and
force premature scoring. They aren't live projects either — nothing
to deliver. They're a third thing: pre-qualification research
anchored to a won account.

### Architecture

- `expansion_targets_store.py` — per-target JSON store with the
  same shape as our other domain stores. Statuses, embedded
  contacts array, `mark_converted` helper.
- Endpoints:
  - `GET  /api/expansion/overview` — anchor-grouped aggregate
    with totals (greenfield, in_progress, converted)
  - `POST /api/expansion-targets` (+ GET/PATCH/DELETE on `<id>`)
  - `POST /api/expansion-targets/<id>/contacts` (+ PATCH/DELETE
    on `<contact_id>`)
  - `POST /api/expansion-targets/<id>/convert-to-lead`
    (idempotent — last write wins)
- All target mutations emit audit events
  (`expansion_target_{created,updated,deleted,converted}`).

### Overview aggregator behaviour

Anchors with targets sort first (more work to do). Within each
anchor, greenfield surfaces above in-progress, which surfaces above
dropped/converted. Targets whose `anchor_lead_id` doesn't match any
live project still get a synthetic anchor row so they stay visible
— never lose a target to a deleted anchor.

### Tests

51 new tests in `test_expansion_targets.py` (store CRUD, endpoint
contracts, overview aggregation + sort, convert idempotence).
Full suite: 967 tests passing.

---

## [1.0.0bn] — 2026-05-24 — Design pass II: drawer header + live tabs + colour audit

The three remaining items from the v1.0.0bm review.

### Drawer header tightened

Before: **5 buttons** (Restore / Rescore / Promote-to-Live / Save / Close)
After: **Save / Close** primary + **⋯** overflow menu for secondary
actions.

- `⋯` overflow menu contains Rescore + Promote-to-Live. Mirrors the
  nav-dropdown pattern (click trigger to open, outside click to close).
- Restore stays at the top level because it signals data-loss
  recovery — too important to bury. Only shows when local cache
  looks empty for the lead, so it's rare anyway.
- The dropdown sets `display:block` via the `.open` modifier on the
  wrap; the inline `display:none` on `#ld-actions-menu` is the safe
  default that the `!important` rule overrides when open.

### Live Project detail wrapped in tabs

Before: **6 stacked sections** (header, status/owner, summary, OKRs,
stakeholder map, agencies). Long scroll, hard to navigate.

After: **Overview / OKRs / Stakeholders / Agencies** tabs.
- Overview = name + status + owner + summary in one focused screen
- Tab counts on the chip labels (`OKRs 3`, `Stakeholders 8`,
  `Agencies 2`) so the user sees weight without clicking
- Reuses the v1.0.0bm `.tab-strip` + `.tab-pane` CSS — one design
  vocabulary, two surfaces

### MR-red colour audit

The brand red was doing two jobs: brand identity AND alarm state.
When one colour does both, neither reads as intended.

**Kept MR-red** (brand identity surfaces):
- `.nav-cta` (+ Qualify button) — primary CTA
- `.tab-strip` active chip border + count badge — active state
- Notification bell badge — brand touchpoint
- Chart colours for the "CRM Build" service + the forecast "Net"
  bar — MR's primary product surfaces
- Notification unread dot — signals "something for you"
- `.tile.manual`, `.btn:hover` glow, `--focus-ring`, hero radial —
  ambient brand presence

**Switched to `var(--red)`** (semantic alarm token):
- Todo due-date overdue colour — alarm signal
- Todo delete button — destructive action

Two changes is small but precise. The brand surfaces now read as
brand; the alarm surfaces read as alarm. Future alarm states (engagement
drops, deletion confirms, etc) should default to `var(--red)`.

### Tests

No new tests — pure frontend cosmetics. All 916 tests pass unchanged.

## [1.0.0bm] — 2026-05-24 — Design pass: nav restructure + Home consolidation

Ben asked for a design review. Two biggest issues:
- **Nav had 8 flat buttons**, mixing destinations (Pipeline, Live) with
  actions (Qualify Lead) and adjacent analytics (Forecast, Dashboard).
- **Home view had ~10 stacked cards** with overlap (Morning brief
  duplicated Notifications + part of Todos + Needs attention flags).

This commit fixes both without functional change.

### Nav: 8 buttons → 5 main + 1 CTA

```
Before:  Home · Qualify Lead · Pipeline · Forecast · Dashboard · Project Build · Live · Partners
After:   Home · Pipeline ▾ · Live · Partners · Insights ▾ · [+ Qualify]
```

- **Pipeline ▾** dropdown: Pipeline / Project Build / Forecast (pre-
  sale flow grouped together)
- **Insights ▾** dropdown: Dashboard (room for engagement leaderboard,
  exports later)
- **+ Qualify** CTA pinned right — Qualify is an action, not a
  destination
- Parent dropdown trigger gets active state when a child view is
  current, so the user can see which group they're inside
- Click outside closes any open dropdown

### Home: 10 cards → 5

```
Before stack (10 cards):
  Morning brief
  Greeting
  KPIs (5-card grid)
  [Overdue contacts] [Active leads]
  Role extras
  Needs attention
  Watched accounts
  Todos
  Notifications
  Activity
  Team snapshot

After (5 cards):
  Morning brief
  Greeting
  KPIs
  Your accounts   ── Needs attention · Active · Watched · Overdue contacts
  Your work       ── Todos · Notifications · Activity
  Team pulse      ── collapsed <details>, expand for snapshot
```

- **Your accounts** card with 4 tabs. Auto-selects Needs attention
  when there's anything <50 engagement; otherwise defaults to Active.
- **Your work** card with 3 tabs. Per-tab header buttons (Clear
  completed / Refresh feed / See all) only show when their tab is
  active.
- **Team pulse** collapsed by default — the personal stuff above is
  what AEs scan first; team snapshot is reference context, not
  always-on.
- Tab counts on the chip labels so users see weight without clicking.

### Added (CSS infra)

- `.nav-dropdown` + `.nav-dropdown-menu` for the new sub-nav pattern.
  Light/dark theme aware. Active state propagates up.
- `.nav-cta` for the pinned-right action button (MR red).
- `.tab-strip` + `.tab-pane` for the Home tabs. Active chip gets
  bottom-border MR red. Tab counts in `.tab-count` badges that
  highlight in MR red on the active tab.

### What's not in this commit (v1.0.0bn)

- **Drawer header tightening** — 5 buttons (Restore / Rescore /
  Promote-to-Live / Save / Close) is still a lot. Move secondary
  actions into a "..." menu.
- **Live project detail tabs** — 6 stacked sections (header, status,
  summary, OKRs, stakeholders, agencies) — wrap in Overview / OKRs
  / Stakeholders / Agencies tabs.
- **Color audit** — MR red is overworked. Keep it for primary CTAs +
  brand surfaces, switch alarm states to a distinct red token.

### Tests

No new tests — this is pure frontend restructuring with no behaviour
change. The full 916-test suite passes unchanged.

## [1.0.0bl] — 2026-05-24 — Stakeholder map + concurrent agencies

Completes the live-project surface Ben asked for. v1.0.0bk shipped
the project + OKRs spine; this commit adds:
- a stakeholder influence×interest matrix per project (driven by
  fields on existing contacts — no parallel store)
- concurrent agencies (other agencies on the account alongside MR,
  with scope + embedded contacts)

Both extend existing stores rather than build new ones, so the
upgrade is backward-compatible and there's no data migration.

### Added

- **`contacts_store` extended** with `stakeholder_role`
  (sponsor|champion|user|blocker|unknown), `influence`
  (high|medium|low), `interest` (high|medium|low). All optional,
  default None. Case-insensitive on save. Invalid values normalise
  to None (so a typo doesn't pollute the matrix).
- **`lead_agencies_store` extended** with:
  - `TYPE_CONCURRENT = "concurrent"` sibling to
    incumbent/previous/competitor — for agencies working
    *alongside* MR on a live engagement.
  - `contacts: [{id, name, title, email, phone, notes}]` embedded
    array (small + tightly scoped — these only make sense in the
    context of the agency they work at).
  - Preserved across updates: if the caller doesn't supply
    `contacts` on a re-save, the existing list is kept.
- **`/api/live-projects/<id>` detail endpoint** now returns
  `contacts` + `agencies` alongside the project + OKRs, so the
  detail card renders the stakeholder map + concurrent agencies
  without further fetches.
- **Stakeholder map UI** on the live project detail:
  - 2×2 influence×interest matrix with named quadrants
    ("Manage closely", "Keep satisfied", "Keep informed",
    "Monitor")
  - Per-contact inline editor (role / influence / interest
    dropdowns) — change saves to `/api/contacts/<lead_id>` POST +
    re-renders the matrix immediately
  - Yellow warning when contacts aren't placed yet ("3 contacts
    not yet placed — set influence + interest below")
  - "medium" influence/interest counts as "high" for the 2×2
    placement (medium-interest stakeholders are interested enough
    to track in the closer quadrants)
- **Concurrent agencies UI** on the live project detail:
  - List of all agencies on the account, colour-coded by type
    (concurrent green, incumbent yellow, competitor red,
    previous muted)
  - Each card shows scope + embedded contacts
  - Add / edit (with contact-append) / delete via prompts

### Tests

- **`tests/test_stakeholder_map_concurrent_agencies.py`** — 13
  tests:
  - **5 stakeholder-fields tests** on contacts_store: defaults
    None, valid values stick, invalid → None, case-insensitive,
    round-trip through list_contacts.
  - **6 concurrent-agency tests** on lead_agencies_store: type
    accepted, existing types still work (backward-compat), invalid
    type still rejected, embedded contacts persist + dedup-by-name,
    contacts preserved through update when caller omits the field.
  - **1 integration test**: the live-project detail endpoint
    includes contacts (with stakeholder fields populated) +
    agencies (concurrent with embedded contact).

### Why extending the existing stores

Two reasons for not creating new
`live_project_stakeholders_store` and
`live_project_agencies_store`:
1. **Single source of truth** — a contact's role / influence /
   interest is true regardless of whether we're looking through
   the lead drawer or the live project. Mirroring them across two
   stores guarantees drift.
2. **Backward compat** — every contact + agency that already
   exists in the platform "just works" in the new UI. Mapping
   them is opt-in.

## [1.0.0bk] — 2026-05-24 — Live Projects (post-sale delivery + OKRs)

Ben asked for a "live projects" section — accounts that have moved
past sales into active delivery, with quarterly measurable OKRs,
contacts carried over, stakeholders, other agencies. This commit
ships the spine: live projects + OKRs + the promote-from-lead flow.
v1.0.0bl follows with the stakeholder map + concurrent agencies.

### Added

- **`live_projects_store.py`** — one JSON file per project. Fields:
  id, lead_id (link back), name, status (active|paused|completed|
  archived), owner, started_at, ended_at, summary, tags. Enforces
  one-live-project-per-lead. Status transitions auto-set ended_at
  on completed/archived; clear it on active/paused.
- **`live_project_okrs_store.py`** — per-project quarterly OKRs.
  Each OKR: quarter (free-form label like "Q2 2026"), objective,
  key_results [{description, metric, unit, target, current, status
  (on_track|at_risk|missed|done), notes}]. Per-KR addressable via
  helpers so the UI can add/edit/remove individually.
  `summarise(okr)` returns `{total_krs, on_track, at_risk, missed,
  done, health_pct}` for the UI.
- **API surface** (~10 endpoints):
  - `GET /api/live-projects?status=` — list with company-name
    enrichment + OKR health roll-up per project
  - `GET /api/live-projects/<id>` — detail with full OKR list
  - `PATCH /api/live-projects/<id>` — partial update
  - `DELETE /api/live-projects/<id>` — hard delete
  - `POST /api/lead/<lead_id>/promote-to-live` — convert a lead;
    defaults name from lead's company, owner from lead's owner.
    Idempotent (second call returns the existing project, 200 not
    409). Doesn't copy contacts/agencies — references the lead so
    the data stays single-source.
  - `POST /api/live-projects/<id>/okrs` — add an OKR
  - `PATCH /api/okrs/<id>` — update an OKR (quarter / objective /
    full key_results array)
  - `DELETE /api/okrs/<id>` — drop an OKR
  - `POST /api/okrs/<id>/key-results` — add a KR
  - `PATCH /api/okrs/<id>/key-results/<kr_id>` — update a KR
    (status flip, current-value update, edit description)
  - `DELETE /api/okrs/<id>/key-results/<kr_id>` — drop a KR
- **Live Projects nav button** + view: list with status chips,
  owner, started_at, OKR health bar + counts. Click any row to
  open the detail card (sticky below the list).
- **Project detail** with:
  - In-place editable name, owner, summary, status
  - Per-quarter OKR sections with KR table (target/current/status
    chip), add/edit/delete buttons for both OKRs and KRs
  - "Open lead" button — jumps back to the source lead drawer
- **"Promote to Live →" button** in the lead drawer header.
  Becomes "→ Live Project" once promoted (one-click jump back to
  the live project detail). Reflects state on every drawer open.
- **Audit events**: `live_project_created`, `live_project_updated`,
  `live_project_deleted`, `live_project_okr_created`. Picked up by
  the team activity feed automatically.

### Tests

- **`tests/test_live_projects.py`** — 27 tests across the three
  layers:
  - **13 live_projects_store units**: create + get, today default
    for started_at, one-live-per-lead enforcement, get_by_lead,
    status filter, status→ended_at auto-set + back-to-active clear,
    validation (enum / date / unknown field / required fields),
    delete + delete-missing.
  - **9 OKRs store units**: create with KRs, summarise (all 4
    statuses + empty), add/update/delete KR, sort by quarter,
    enum + required validation.
  - **5 endpoint tests**: promote-to-live creates with sensible
    defaults from Notion lead, promote idempotent (201 first,
    200 second, same id), status filter on list, end-to-end OKR
    lifecycle (create project → add OKR → add KR → update KR →
    delete KR), unknown project → 404.

### Coming in v1.0.0bl

- **Stakeholder map**: extend `contacts_store` with role / influence
  / interest fields; render the influence×interest matrix per
  account.
- **Concurrent agencies**: extend `lead_agencies_store` with
  TYPE_CONCURRENT (sibling to incumbent / previous / competitor) +
  per-agency scope field + contact entries. UI surface on both the
  lead drawer and the live project detail.

## [1.0.0bj] — 2026-05-24 — News fetcher + AI relevance + watcher notifications

Completes the watch-list system Ben asked for. Watched accounts now
get real news scanned against them; Claude scores each headline
against MR's specific offer; watchers get a bell notification when
something material lands.

### Added

- **`account_news.py`** — fetcher + AI relevance scorer:
  - `fetch_for_company(company_name, since_iso=, limit=)` pulls
    Google News RSS (no API key, free, returns ~30 days), parses
    items in-house (no `feedparser` dep — RSS is well-formed
    enough that a regex parser is reliable for one feed).
  - `score_relevance(items, company_name)` runs each through
    Claude with an MR-specific rubric: 9-10 = directly material
    (loyalty programme, CMO hire, data platform RFP), 6-8 =
    indirectly relevant (marketing spend commentary, mobile app),
    4-5 = tangentially interesting, 0-3 = noise. **Drops anything
    below 4** so the AE only sees signal. Each surviving item gets
    `why_relevant` (one line) + `mr_action_hint` (optional concrete
    next move). Tunable threshold via `_RELEVANCE_THRESHOLD`.
- **`account_news_store.py`** — JSON-per-lead persistence with
  dedup by item id (sha1 of title+link). `upsert_many` reports
  added vs updated vs new_items so the sweep knows which to
  notify on. Ring-cap 100 items per lead.
- **API endpoints**:
  - `GET /api/lead/<id>/news` — return persisted items (cheap,
    no LLM call, no Google News hit)
  - `POST /api/lead/<id>/news/refresh` — fetch+score+persist on
    demand; skips already-seen ids to save tokens
  - `POST /api/admin/watchlist/sweep` — daily-cron-shaped endpoint
    that scans every watched account, fans notifications out to
    every watcher (`kind: news_alert`), bumps each watcher's
    `last_news_seen_at` high-water mark. Optional `?lead_id=`
    scopes to one lead (testing / per-lead refresh).
- **News card in the lead drawer** under the hero, listing items
  newest-first with the relevance score, the AI's "why this
  matters", and a clickable headline link. Refresh button triggers
  the per-lead refresh endpoint.

### Notifications

- New `kind: news_alert` follows the existing notifications
  contract — bell badge bumps, click opens the lead drawer (the
  link uses the standard `{kind: "lead", lead_id}` shape so
  `_openTodoLink` routes it correctly without any new UI work).
- Dedup is per-watcher: each user gets notified once per article
  per lead, not once per sweep.

### Tests

- **`tests/test_account_news.py`** — 18 tests across three layers:
  - **9 fetcher/scorer units** (Anthropic SDK stubbed inline,
    `requests.get` patched): RSS parse extracts items with
    source/date/snippet, deterministic item_id, HTTP failure → empty,
    since_iso filters, no-filter returns all, scoring drops below
    threshold, returns empty when Anthropic off, handles malformed
    JSON, sorts highest-first.
  - **5 store units**: upsert adds + dedup updates, list newest-
    first by published_at, ids_already_seen for sweep dedup,
    per-lead isolation.
  - **4 sweep endpoint tests** (NotionSync + fetch + scorer all
    stubbed): no-watchers returns zero, two watchers on same lead
    → both get notified, second sweep on same news dedupes
    (notifications_fired=0), `?lead_id=` scopes to one lead.

### How to use

1. Open any lead → click the **Watch** toggle next to the ENG chip.
2. The Watched accounts card on Home now lists it.
3. Click **Refresh** on the news card in the drawer for an
   on-demand scan.
4. Trigger `POST /api/admin/watchlist/sweep` daily (or on-demand)
   to scan all watched accounts in one shot and fire bell
   notifications to all watchers. A cron service or Railway
   scheduled job can fire this nightly.

### What's not in this commit

- Annual report parsing (PDF fetch + Claude summarisation). The
  rubric example called this out. It needs a separate path because
  annual reports are PDFs not RSS items, and the Claude prompt
  for "summarise this 200-page PDF against MR's offer" is bigger
  than the per-headline scorer. Reasonable v1.0.0bk if you want it.
- Auto-cron on Railway. The sweep endpoint works; you'd wire a
  Railway scheduled job (or external scheduler) to POST it daily.

## [1.0.0bi] — 2026-05-24 — Account watch list (foundation)

Ben: "I'd like the team to be able to create an account watch list
meaning that they will receive notification on relevant news for the
account based on Massive Rocket's needs."

This ships the watch-list foundation — store, endpoints, drawer
toggle, Home card. v1.0.0bj will wire in the news fetcher + AI
relevance scoring + the bell notifications. Splitting in two keeps
each commit reviewable and ships something testable today (you can
already mark accounts to watch + see them on Home).

### Added

- **`account_watchlist_store.py`** — per-user JSON store. Each
  entry: `{lead_id, added_at, last_news_seen_at}`. The
  `last_news_seen_at` high-water mark is the foundation v1.0.0bj
  will use so the news fetcher only considers new items since the
  last scan. API: `list_for`, `add` (idempotent), `remove`,
  `is_watching`, `watchers_of(lead_id)` (inverse lookup for
  fan-out), `mark_news_seen`. Cap 200 per user.
- **API endpoints**:
  - `GET /api/watchlist?user=` — list, enriched with company name
    via best-effort Notion pipeline lookup
  - `POST /api/watchlist/<lead_id>` body `{user}` → 201 + entry
  - `DELETE /api/watchlist/<lead_id>?user=` → `{removed, watching}`
  - `GET /api/watchlist/<lead_id>/status?user=` — cheap is-watching
    check (drawer toggle uses this on open)
- **`/api/home` payload** now includes `watched_accounts` (top 10)
  so the Home card renders with the first paint, no second fetch.
- **Watch toggle on the lead drawer header** next to the ENG chip.
  Eye icon + "Watch" / green eye + "Watching" state. Click flips
  via POST or DELETE. Hidden when no profile is set.
- **Watched accounts card on Home** — grid of clickable pills
  showing company name + "Last news Xd ago" / "No news scanned
  yet". Hidden when nothing is watched (the toggle is the entry
  point so an empty state would confuse). Click any pill →
  lead drawer opens.
- **Audit events**: `watchlist_added`, `watchlist_removed` so the
  team activity feed (v1.0.0ap) surfaces watch state changes.

### Tests

- **`tests/test_account_watchlist.py`** — 20 tests:
  - 13 store units: add+list, add idempotent, newest-first sort,
    remove (first + second), is_watching, per-user isolation,
    watchers_of (inverse lookup + empty case),
    mark_news_seen (bumps + missing), validation (user/lead_id
    required), 200-per-user cap.
  - 7 endpoint tests with NotionSync patched: list requires user,
    add+list with company enrichment, add returns 201, remove,
    remove unknown returns removed=false, status check on/off,
    missing-user 400.

### Next (v1.0.0bj)

- News fetcher (Google News RSS per company query)
- AI relevance scorer (Claude reads headlines, scores 0-10 against
  MR's offer of CRM / data / loyalty / engineering, drops anything
  below threshold)
- `kind: news_alert` notification on materially-relevant items
- News digest feed in the lead drawer

## [1.0.0bh] — 2026-05-23 — Fix: partner-sourced notes not synthesised

Ben: "Added notes which were given by a partner on Shell but the
notes were not synthesised as they should be."

Root cause: the call-save handler had this gate around the lead-
summary refresh:

    if ai_summary.is_configured() and extracted is not None:
        # ... synthesise_lead(ctx) ...

When `extract_from_notes` returned None (transient Anthropic API
error, malformed JSON response, rate limit, timeout, etc), the
**synthesis was silently skipped**. The user saved a partner note,
saw "Saved", but the lead-summary tile never updated — and there
was no toast explaining why.

But `synthesise_lead` doesn't depend on this one call's extract.
It pulls from the FULL call history + lead context, so it can
write a meaningful summary even when this particular extraction
failed. The two paths are conceptually independent.

### Fixed

- **De-coupled synthesis from extraction** in
  `server.api_calls_add`. Synthesis now runs whenever AI is
  configured, regardless of whether `extracted` is None.
- **Surface the failure** when synthesis itself fails (rate limit,
  Anthropic outage, malformed response). New `summary_refresh_error`
  field in the `/api/calls/<lead>` POST response. UI toasts it
  honestly: *"AI synthesis returned no result — click Refresh on
  the lead summary to retry."* or the raw exception message,
  truncated to 200 chars.
- Two UI sites updated to surface the error: inline "Save note now"
  toast + combined-save toast.

### Tests

- **`tests/test_partner_note_synthesis.py`** — 5 tests that lock
  in the de-coupling so this doesn't regress:
  - synthesis fires when extraction returns None (the regression
    case Ben hit)
  - summary_refresh_error surfaces when synth raises an exception
  - summary_refresh_error tells the user to retry when synth
    returns None (no exception, just no result)
  - AI-off skips synthesis entirely and doesn't toast an error
    (the existing "AI off" banner already covers that case)
  - partner_source on the call propagates into the synthesis
    context, so the prompt's attribution rubric ("Marina at Braze
    told us...") has something to work with

## [1.0.0bg] — 2026-05-23 — Fix: contacts showing only first names

Ben: "Why is it only showing the first name in contacts it should
provide their full name (first and last names)"

Root cause: the AI-extracted `contacts_mentioned` field surfaces
people exactly as they were spoken in the call notes. In practice
people get referred to by first name only ("Sarah said yes",
"Marina mentioned…") and that first-name-only string was getting
saved as the contact's `name`. v1.0.0x already fixed this for
Apollo's contact search; the AI-extraction path still leaked
half-names through.

### Fixed

- **AI rubric tightened** in `_EXTRACT_SYSTEM_PROMPT`:
  - First + last preferred whenever both knowable from the notes
  - If only a first name is said, the AI is now told to look
    elsewhere (signature lines, email addresses, attendee lists,
    later references like "Sarah Johnson in legal") to pair the
    surname back
  - If only a first name + no email → **omit the entry** rather
    than save a half-named contact
  - Single-name + email pair is the one exception (email lets the
    AE disambiguate later)
- **Defensive parser filter** in `extract_from_notes` — drops
  single-word names without an email, as a belt-and-braces under
  the rubric. Stops the contact list filling up with cleanup
  work when the LLM ignores the rubric.
- **Editable contact-suggestion UI** in the lead drawer:
  - Name + title are now `<input>` fields (not just display text)
    so the AE can complete a truncated name on the fly before
    clicking Add
  - Single-name suggestions get a yellow "NEEDS LAST NAME" badge
  - The save handler reads from the editable inputs, not the
    original AI output, so corrections actually persist
  - One final guard: if the AE clicks Add with a name still
    truncated, a confirm() asks "Add anyway?" with the names
    listed — gives one more chance to correct without forcing it

### Tests

- **`tests/test_call_extraction_agencies_tech.py`** grew 11 → 13
  with 2 new cases:
  - `test_drops_single_word_contacts_without_email`: {name:"Sarah",
    role:"prospect-side"} → dropped; {name:"John Doe"} → kept
  - `test_keeps_single_word_contact_when_email_present`: {name:
    "Sarah", email:"sarah@acme.com"} → kept (email
    disambiguates)

### Doesn't fix (out of scope for this commit)

- **Backfilling existing contacts** whose names are already saved
  as just first names — these stay as-is. The AE can either delete
  + re-add (cleaner) or open the edit form and add the surname
  manually. A future commit could Apollo-enrich existing single-
  name contacts via the lead's domain.

## [1.0.0bf] — 2026-05-23 — Morning brief on Home

The first thing the user sees when they open the app: a single
"what should I look at first" card that aggregates the day's
notable signals. Closes the loop on every store this session has
shipped — engagement, todos, notifications, all in one glance.

### Added

- **`GET /api/home/morning-brief?owner=`** — server-side aggregator.
  Pulls every unread notification for the owner, partitions into:
  - `engagement_drops`: notifications of kind `engagement_dropped`
  - `new_assignments`: notifications of kind `assigned_lead` or
    `assigned_partner_contact`
  Pulls open todos for the owner, splits into:
  - `todos_due_today`: due_date == today, sorted by priority
  - `todos_overdue`: due_date < today, sorted most-overdue first
  Plus a synthesised `headline` (e.g. *"2 accounts dropped engagement
  · 3 overdue todos · 1 due today"*) and an `is_empty` flag so the
  UI hides the card when there's nothing to nag about.
- **Morning brief card** at the top of Home — first thing AE sees.
  Header: title + headline + Dismiss button. Body: up to four
  coloured sections (engagement drops red, overdue red, due-today
  yellow, new assignments green). Each entry shows the title + body
  preview + click-through to the entity. Dismiss is session-scoped
  (sessionStorage) so it doesn't reappear during the current tab
  visit but does come back tomorrow / on reload.
- **Reuses the `_openTodoLink` router** so click-through routing
  stays consistent with every other "click to open entity" surface
  in the platform.

### Tests

- **`tests/test_morning_brief.py`** — 9 tests:
  - owner-required validation
  - empty state (no signals → is_empty=True, headline=None)
  - engagement drops surfaced with slim shape (notification_id)
  - read notifications excluded (don't keep nagging after the user
    acknowledged the drop)
  - todos split correctly by due_date (today/overdue/future/no-due),
    only today + overdue surface
  - completed todos excluded
  - overdue sorted most-overdue-first
  - new assignments (both kinds) surface
  - headline correctly concatenates counts across signal types

### Why a separate endpoint, not folded into `/api/home`

`/api/home` already does dashboard rollup + Notion pipeline + per-
lead engagement scoring for at-risk leads. Adding the brief
aggregation would compound the latency on the most-visited
endpoint. The brief is small and fast on its own; a parallel fetch
keeps the Home greeting + KPIs painting immediately while the
brief backfills.

## [1.0.0be] — 2026-05-23 — Tech stack chips in lead drawer

After v1.0.0bb's auto-merge wrote new tools into the lead's
comma-separated `tech_stack` field, the raw input got hard to scan.
This renders each entry as a removable chip below the input.

### Added

- **Chip rendering** below the Tech Stack input. Comma-separated
  value parsed, case-insensitively deduped, each shown as a
  `<span>` with a × button. Click × → input updates → dirty
  tracker fires (so Save lights up) → chips re-render.
- **Live update on typing** — the chip list reforms as the AE
  types commas, so they see the structure they're building.

### Why chips, not multi-select

The Notion `Tech Stack` field is a `rich_text` column; the platform
treats it as a comma-separated string. Switching to a true
multi-select would require a Notion schema change and migrate
every existing lead. Chips give the AE the multi-select feel
without changing the storage contract.

## [1.0.0bd] — 2026-05-23 — Pipeline filter presets

v1.0.0ay shipped filter presets for partner contacts. The Pipeline
has its own filter combo (status × source × sourced-for × group ×
engagement-band × view-mode × sort). Same store, just scope=
"pipeline".

### Added

- **Preset picker row** above the Pipeline filter chips: dropdown
  + Save current + Delete. Hidden until a profile is set. Lazy-
  inits on first nav to Pipeline.
- **`_savePipelinePreset`** snapshots only the filter slice of
  `state.pipeline` (filter, sourceFilter, sourcedForFilter,
  groupFilter, engagementFilter, viewMode, sort) — runtime fields
  like `rows` and `engagementScores` are deliberately excluded.
- **`_syncPipelineFiltersFromState`** mirror that hydrates every
  on-screen filter widget (chips, dropdowns, view-mode toggle)
  from `state.pipeline` after a preset apply. Otherwise the data
  would change but the widgets would still show the previous
  selection.

### Server

No change. The v1.0.0ay store accepts arbitrary `scope` values; the
endpoints already route by it.

### Why share the store with partner contacts

The two surfaces have different filter shapes but identical store
needs: per-user, named, opaque-payload, scope-keyed. Sharing the
store means one place to evolve (notifications when a preset is
shared, "favourite" flag, sort presets, etc.). The scope discriminator
keeps the two surfaces' presets cleanly separated.

## [1.0.0bc] — 2026-05-23 — Engagement trends (deltas, arrows, drop notifications)

A single engagement score (v1.0.0at) tells you the state today. A
sequence tells you whether the account is going up or down — and
the platform can flag it when an AE's account drops a band.

### Added

- **`engagement_snapshots_store.py`** — daily-deduped snapshots per
  lead. Ring-capped at 30 entries. Key API: `record()` (insert-or-
  update for today, idempotent), `history()`, `previous_snapshot()`
  (strictly before a date), `delta(days_ago=7)` (with graceful
  fallback to oldest available when history is shallow),
  `band_downgraded(prev, now)` helper for the notification trigger.
- **Snapshot recording wired into `_compute_engagement_for_lead`**.
  Every drawer load + batch fetch records today's snapshot
  (same-day calls update in place). Notification side-effects are
  guarded so opening the drawer twice on the same day doesn't
  re-fire the bell.
- **`engagement_dropped` notification kind**. Fires when today's
  band is strictly worse than the most recent prior snapshot's
  band. Routes to the lead's owner (best-effort via NotionSync);
  body explains the drop: *"Acme dropped to cold. Engagement fell
  from 75 (strong) to 35 (weak) since 2026-05-22."* Click goes to
  the lead drawer.
- **`trend` field on `/api/lead/<id>/engagement-score`** with
  `{now, then, delta, direction, days_compared, then_band,
  now_band}`. The batch endpoint also returns `trend_direction +
  trend_delta` per lead so Pipeline + Home chips render the arrow.
- **Trend arrows in the UI**:
  - Lead drawer ENG chip: `ENG 75/100 ↑` (or ↓ / nothing for flat)
  - Pipeline ENG column: same arrow next to the score
  - Home active-leads chips: `ENG 75 ↑`
  - Tooltip includes "Trend: +12 vs 7d ago (63 → 75)" so the AE
    sees the magnitude on hover.

### Tests

- **`tests/test_engagement_snapshots.py`** — 19 tests:
  - 14 store units: record + same-day dedup (update in place),
    multi-day accumulation, 30-entry ring cap, per-lead isolation,
    previous_snapshot (excludes today, finds most-recent prior,
    None when no history), delta (none on single snapshot, finds
    N-days-ago, direction up/down/flat, falls back to oldest when
    not enough history), band_downgraded matrix
  - 5 integration tests (NotionSync patched): band downgrade fires
    notification with correct lead link + body, same-day repeat
    doesn't re-fire (dedup), no notification when band unchanged,
    no notification when band IMPROVES, trend field present in
    score response with correct then/now.

### Why per-day dedup + same-day update-in-place

Two callers will frequently compute the same lead's score on the
same day (e.g. AE opens the drawer, then the Pipeline view re-runs
the batch). Without dedup we'd write multiple rows per day and
inflate the file with noise. Update-in-place means the snapshot
represents end-of-day state — useful for the next day's comparison.

The notification fires only on the FIRST recording of today
(checked via `history()` before calling `record()`) so the bell
doesn't ping each time the user navigates back to the lead.

## [1.0.0bb] — 2026-05-23 — Calls auto-extract competitive agencies + tech stack

Ben: "Notes should also be able to pick up on competitive agencies or
tech stack mentioned to be added to the respective account."

Today, AI extraction from call notes captures MEDDPICC + contacts +
scope criteria. This adds two more dimensions and auto-links them
to the lead so the AE doesn't have to copy/paste from notes into
fields.

### Added

- **Two new fields on the AI extraction schema**:
  - `competitive_agencies: [{name, context}]` where context ∈
    {`current incumbent`, `previously evaluated`,
    `pitching against mr`, `mentioned in passing`}. Rubric in the
    prompt steers the LLM to capture AGENCIES (WPP, Razorfish,
    Wunderman, Accenture, R/GA) and explicitly NOT tech vendors.
  - `tech_stack_mentioned: [str]` — named tools the prospect uses,
    evaluates, migrated from, or plans to adopt. Rubric explicitly
    rejects generic categories ("a CDP", "their analytics tool").
  - Parser dedupes case-insensitively within a single call's
    extraction; an extra defensive filter strips overly-generic
    phrases that occasionally slip through despite the rubric.
- **Auto-link competitive agencies → `lead_agencies_store`**:
  - New `TYPE_COMPETITOR` constant (sibling of `incumbent` +
    `previous`); rows tagged with `source="call_extracted"` +
    `source_call_id` for provenance so the AE can see "this came
    from call X".
  - `lead_agencies_store.get_by_name(lead_id, name)` for the
    auto-link's case-insensitive dedup against existing entries.
    Already-tracked agencies are skipped (no spam, no overwriting
    AE-set type).
  - When the AI's `context` is `"previously evaluated"` the auto-
    link saves as `previous` instead of `competitor` (more honest
    categorisation).
- **Auto-merge tech stack → lead's Notion `Tech Stack` field**:
  - On every call save, fetches the lead's current `tech_stack`,
    compares case-insensitively against `tech_stack_mentioned`,
    appends any new tools comma-separated. Empty field initialises
    cleanly (no stray leading comma).
  - Best-effort: Notion outage or PATCH failure is logged but
    doesn't block the call save.
- **`calls_store.aggregate_extractions` extended** to roll up
  tech_stack + agencies across every call on the lead. Each entry
  carries mention count, first/last seen timestamps, and the call
  IDs that mentioned it so the UI can deep-link back to the source.
- **"Discovered in calls" panel** in the lead drawer hero. Renders
  chip rows for tech stack tools (accent-coloured) + agencies
  (MR-red), each with a mention count badge. Hidden when nothing's
  been extracted yet.
- **Audit events**: `lead_agency_auto_added` +
  `lead_tech_stack_auto_appended` so the team-activity feed
  (v1.0.0ap) surfaces the AI auto-actions.

### Tests

- **`tests/test_call_extraction_agencies_tech.py`** — 11 tests
  across three layers:
  - **5 extraction parser tests** (Anthropic SDK stubbed inline):
    parses agencies with context, case-insensitive dedup within a
    call, invalid context normalises to null, generic tech mentions
    filtered, null/empty entries skipped.
  - **2 aggregator tests**: cross-call rollup with mention counts +
    call_ids, empty extraction → empty rollups.
  - **4 end-to-end tests via the call POST endpoint** (NotionSync
    patched): agencies auto-added with correct type + source,
    already-present agencies skipped (no dupes), tech stack
    auto-merged with case-insensitive dedup against existing field,
    empty-field initialises without stray comma.

### Why auto-merge to Notion (and not just surface)

I considered just rendering the "Discovered in calls" panel and
letting the AE click to merge. Decided against because Ben said
"to be added to the respective account" — they want it on the
account record, not buried in a panel. The trade-off is that an
AI hallucination could land bogus tech names in the Notion field.
Mitigated by: (a) rubric explicitly rejects generic terms, (b)
defensive filter in parser, (c) audit log captures every auto-add
so it's reversible. Agencies are safer because the AGENCIES
section is supplementary (not a Notion field).

## [1.0.0az] — 2026-05-23 — Sortable ENG column on Pipeline

Tiny but high-utility: click the ENG column header on the Pipeline to
sort by engagement score. First click → ascending (worst first, so
the rescue list floats to the top). Second click → descending (best
first). Pairs with the v1.0.0av engagement-band filter for a "show
me the cold ones, sorted by score" workflow.

### Changed

- **`renderPipeline` sort branch**: special-case for the
  `engagement_score` key. Reads from the in-state
  `engagementScores` cache populated by the v1.0.0au batch
  hydrator, not from row fields (which don't carry the score).
  Rows without a cached score sink to the bottom regardless of
  direction so unscored leads don't bury the actually-low ones at
  the top of an ascending sort.
- **`_hydratePipelineEngagementScores` re-render**: if the current
  sort is `engagement_score` and the scores arrive after the
  initial paint, re-trigger `renderPipeline` so the table re-sorts
  with the fresh data. Other sort keys are score-independent and
  don't need this.
- **ENG `<th>` made sortable**: added `data-sort="engagement_score"`
  so the existing pipeline header-click handler picks it up
  automatically. No new wiring needed.

No new tests — pure frontend wiring against an already-tested
endpoint. The existing pipeline sort tests cover the regression
surface; the new branch is small and well-isolated.

## [1.0.0ay] — 2026-05-23 — Saved filter presets for partner contacts

The partner contacts table has 8 filter dimensions (territory, region,
country, industry, status, sentiment, tier, seniority, +my-contacts).
The same combos get configured again and again — "My Champions in
QSR", "Strategic AEs in EU", "Cold contacts on Braze". This ships
per-user saved presets so a combo gets typed once and recalled with
one click.

### Added

- **`filter_presets_store.py`** — per-user JSON store. Each preset:
  `{id, user, scope, name, filters, created_at, updated_at}`. The
  `filters` payload is opaque to the store — the UI defines the
  shape, so the same store can power pipeline-filter presets later.
  Name uniqueness enforced per (user, scope); duplicate save raises
  `PresetExists`. Cap 50 presets per user.
- **API**:
  - `GET /api/filter-presets?user=&scope=` — list (alphabetical
    by name)
  - `POST /api/filter-presets` body `{user, name, filters, scope?}`
    → 201 + preset, or 409 if name collides
  - `PATCH /api/filter-presets/<id>` body `{user, name?, filters?}`
  - `DELETE /api/filter-presets/<id>?user=`
- **Preset picker row** in the partner contacts toolbar: dropdown
  of saved presets + "Save current" + "Delete" buttons. Hidden
  until a profile is set. Selecting a preset hydrates
  `partnersState.filter` via `Object.assign` (so future filter
  dimensions inherit the saved-filter behaviour automatically) and
  re-opens the partner detail to repaint the dropdowns and table.

### Tests

- **`tests/test_filter_presets.py`** — 26 tests:
  - 20 store unit tests: create+list, alphabetical sort, duplicate-
    name (case-insensitive) raises, same-name-different-scope OK,
    per-user isolation, get/get-missing, update name/filters/missing,
    update rejects duplicate, update-to-same-name is fine,
    unknown-field update raises, delete + delete-missing, validation
    (empty name, 80-char cap, filters-must-be-dict, user required),
    scope filter on list
  - 6 endpoint tests: list-requires-user, create+list end-to-end,
    duplicate → 409, update, delete, missing-name → 400

### Why a separate store (not jam into `enum_config_store`)

`enum_config_store` holds the *available options* for each filter
dropdown (which territories exist, which tiers, etc.). Presets are
*chosen combinations* across those options. Different lifetimes
(enums change on org evolution; presets change per AE workflow),
different scope (enums are org-wide; presets are per-user).
Mixing them would tangle two concerns.

## [1.0.0ax] — 2026-05-23 — Bulk operations on partner contacts

After v1.0.0ac added tier/sentiment/seniority, existing rows often
need batch field updates (set 30 contacts to "Tier 2", reassign 20
to a new owner after a re-org, mark a chunk dormant when a team
restructures). Doing them one at a time is painful. This ships
multi-select + a bulk-update flow that does it in one round-trip.

### Added

- **`POST /api/partners/<id>/contacts/bulk-update`** — body
  `{contact_ids: [...], updates: {field: value}}`. Allowlisted
  fields: `mr_owner`, `tier`, `partner_sentiment`, `seniority`,
  `status`, `cadence_days`. Free-text fields (name, email, title)
  deliberately excluded to prevent accidental wipeouts. Returns
  `{updated, errors: [{contact_id, error}], notified}`. Cap 200
  contacts per call.
- **Notification contract preserved**: an `mr_owner` change fires
  one `assigned_partner_contact` notification per contact, mirroring
  the single-PATCH path. Idempotent — if a contact already has the
  new owner, no notification fires (no spam on bulk re-set).
- **Selection checkboxes** on every partner contacts table row +
  a select-all checkbox in the header that respects the current
  filter chips. Indeterminate state when partial selection.
- **Floating action bar** appears at the bottom of the partner
  detail when any row is selected. Shows count + "X hidden by
  filters" warning if relevant. Buttons: Reassign owner / Set tier
  / Set sentiment / Set status / Clear. Each opens a tiny prompt-
  based picker, runs the bulk update, toasts the result count +
  notification count + any failures.
- **Audit event** `partner_contacts_bulk_updated` so the v1.0.0ap
  team-activity feed picks up the bulk action.

### Tests

- **`tests/test_partner_contacts_bulk_update.py`** — 11 tests:
  - 5 validation: missing/empty contact_ids → 400, missing updates
    → 400, disallowed field (name) → 400, >200 contacts → 400
  - 3 happy paths: bulk-set tier on 3 contacts, bulk-set status
    dormant on 2 (third untouched), partial fan-out lands bad ids
    in errors while good ones still save
  - 3 notifications: bulk reassign fires per-contact notifications
    with correct link contact_id and "Bulk-reassigned from..."
    body, already-owned skips re-notify, non-owner update fires
    no notifications

### Why a prompt-based picker for the action bar

Considered a proper dropdown modal. Held back: dropdown options
already live in the enum settings, the AE knows them, and a prompt
keeps the action bar lightweight. The trade-off is the picker UX
isn't as polished as a custom modal, but the speed (open prompt,
type a number, done) beats a multi-step picker for the common
case. If usage shows this matters, swap the prompt for a dropdown
in a follow-up.

## [1.0.0aw] — 2026-05-23 — Engagement leaderboard on Dashboard

The engagement score closed the loop for the individual AE (at → av).
This version closes it for the manager: a per-MR-owner leaderboard
on the Dashboard ranking AEs by how well they're working their book.

### Added

- **`engagement.aggregate_by_owner(entries)`** — pure-function
  rollup. Takes per-lead `{owner, score, band}` entries, returns
  per-owner `{owner, n_leads, avg_score, strong/warm/weak/cold,
  needs_attention}` sorted by `avg_score` descending, alphabetical
  tiebreak. Missing owner buckets as "Unassigned". Unknown bands
  count toward n_leads but no band column (forward-compat).
- **`GET /api/dashboard/engagement-leaderboard?per_owner_cap=N`** —
  pulls pipeline, groups active leads by owner (excluding
  Disqualified/On Hold/Closed Lost), caps per-owner scan at N
  (default 30) sorted by recency to bound I/O, computes engagement
  for each, runs the aggregator. Returns rows + totals + generated_at.
  Notion outage → empty list, never 500.
- **"Engagement leaderboard" card** on the Dashboard view, between
  the "By partner" table and Coverage. Fetched in parallel with the
  main dashboard load so the touch counts paint first and the
  leaderboard backfills. Each row shows: owner, coloured avg score,
  distribution chips (X strong / Y warm / Z weak / W cold),
  needs-attention count (red if >0), leads-scored. Click a row to
  scope the rest of the Dashboard to that owner.

### Tests

- **`tests/test_engagement_score.py`** grew 20 → 31 tests (+11):
  - 7 aggregator unit tests: empty input, single-owner single-lead,
    band counting (strong/warm/weak/cold/needs_attention), multi-owner
    descending sort, alphabetical tiebreak, missing-owner →
    Unassigned bucket, unknown-band forward-compat
  - 4 endpoint tests with NotionSync patched: empty pipeline,
    grouping by owner, Disqualified/On Hold/Closed Lost excluded,
    per_owner_cap respected

### Why a separate card, not folded into "By owner"

The existing "By owner" table is about *activity counts* (touches +
calls). The leaderboard is about *engagement quality* (the score the
v1.0.0at module synthesises from coverage + recency + activity +
overdue + key-touch). High activity with low engagement is a real
pattern worth surfacing — an AE making lots of touches but
hitting the wrong contacts shows up clearly. Folding them
together would hide that.

## [1.0.0av] — 2026-05-23 — Engagement-driven workflow: "Needs attention" + pipeline filter

v1.0.0at made the score; v1.0.0au showed it everywhere; v1.0.0av
makes it drive decisions. The AE opens Home and sees the leads that
are slipping. They open Pipeline and can filter to just the cold
ones.

### Added

- **`at_risk_leads` field on `/api/home`** — computes the engagement
  score for each of the user's owned active leads (cap 40 scanned
  for cost), filters to those scoring <50, sorts ascending
  (coldest first), returns top 5. Each entry carries
  `engagement_score`, `engagement_band`, `icp_normalised`,
  `days_since_touch`, `overdue_count` so the UI renders without a
  second fetch.
- **"Needs attention" card on Home** — shows the at-risk leads
  inline with ENG + ICP chips, days-since-touch, overdue-contact
  count. Click any row to open the drawer; "+ todo" pre-fills
  "Rescue {company} — engagement slipping" and creates a linked
  todo. Hidden when nothing is at risk (empty state would be noise).
- **Engagement-band dropdown in Pipeline filters** — "Any
  engagement / Strong only (75+) / Warm+ (50+) / Needs attention
  (<50) / Cold only (<25)". Reads from the in-state cache populated
  by the v1.0.0au batch hydrator; doesn't re-fetch, just hides
  non-matching rows. Re-fires after the hydrator lands so the
  filter applies as soon as scores arrive.

### Tests

- **`tests/test_home_at_risk.py`** — 7 tests with NotionSync patched
  so we can feed any pipeline shape: no owned leads → empty,
  lead-with-no-engagement appears (score=0 < 50), high-engagement
  lead excluded, multi-lead ordering (coldest first), cap-at-5,
  disqualified leads excluded, other-owners' leads excluded.

### Why a separate "Needs attention" card, not a filter on Active Leads

The Active Leads card answers "what have I touched recently"
(sorted by `last_edited`). Needs Attention answers "what should I
touch next" (sorted by engagement ascending). Different questions,
different ordering, side-by-side serves both. Folding them into
one filterable list would force the AE to switch between the two
modes — a tax on the most common action.

## [1.0.0au] — 2026-05-23 — Engagement score in Pipeline + Home rows

v1.0.0at gave every account an engagement score and surfaced it in
the lead drawer. v1.0.0au pushes it into the surfaces AEs scan most:
the Pipeline table and the Home "Active leads" card. One glance,
spot the stale accounts.

### Added

- **`GET /api/engagement-scores?lead_ids=a,b,c`** — batch endpoint.
  Returns `{scores: {lead_id: {score, band}, ...}}`. Score + band
  only (no signals — the drawer tooltip pulls the full breakdown via
  the single-lead endpoint). Capped at 200 ids per call. Per-lead
  failures land as `{score: null, error: "..."}` rather than
  500ing the whole batch — one bad lead can't blank the pipeline.
- **`_compute_engagement_for_lead` shared helper** in server.py.
  Single-lead and batch endpoints both delegate to it; no risk of
  the two endpoints drifting apart.
- **ENG column in the Pipeline table** between ICP and Status.
  Header tooltip: "Engagement score 0–100 — how well we're working
  this account". Each cell paints green/yellow/orange/red based on
  band. Filled post-render via `_hydratePipelineEngagementScores`
  so the table paints without blocking on the batch fetch.
- **ENG chip in Home → "Your active leads"** rows. Inline next to
  the ICP score, same colour scheme. Hover for "Engagement 75/100
  (strong)".

### Tests

- **`tests/test_engagement_score.py`** — 4 new endpoint tests:
  - empty query returns empty map (no 400)
  - returns `score + band` per lead, no signals (contract check)
  - unknown lead id returns `{score: 0, band: "cold"}` (UI gets a
    rendered chip, not a missing key)
  - 250 ids → server clamps to 200

### Why the chips, not just the column

I considered just the Pipeline column. Decided to add Home too
because the active-leads card is where AEs spend the most
attention — that's where engagement-state matters most. The
Pipeline column is for the cross-account scan; the Home chip is
for the "what should I do next" decision.

## [1.0.0at] — 2026-05-23 — Account engagement score

ICP score tells you how good a lead is intrinsically (revenue, employees,
tech stack fit). Engagement score tells you how well we're actually
working it. Same 0–100 scale so AEs read both at a glance, side by
side in the drawer header.

### Added

- **`engagement.py`** — pure-function scoring module. Single entry
  point: `compute_engagement_score(contacts, recent_event_isos,
  today_iso)`. Returns `{score, band, signals}`. No I/O — caller
  handles the data pull. The formula breakdown lives in the module
  docstring so a future weight tweak forces a deliberate update.

### Scoring formula

Five signals sum to 100, clamped [0, 100]:

| Signal | Max | Notes |
|---|---|---|
| **Coverage** | 30 | % of *active* contacts touched at all (left/dormant excluded) |
| **Recency** | 30 | days since most recent touch: 0d=30, 7d=25, 14d=20, 30d=15, 60d=8, 90d+=0 |
| **Activity** | 25 | notes+calls in last 30d (linear, caps at 10 events) |
| **Overdue penalty** | -15 | -5 per overdue contact, capped |
| **Key bonus** | 10 | +10 if any `is_primary` contact has been touched in last 30d |

Bands (give the UI a colour without re-deciding):
- ≥75 **strong** (green) · ≥50 **warm** (yellow) · ≥25 **weak** (orange) · <25 **cold** (red)

### Added (server + UI)

- **`GET /api/lead/<id>/engagement-score`** — pulls contacts + every
  per-contact note + every lead call, runs through the scorer,
  returns score + band + signals. Cheap (typical account: <100ms
  including the I/O fan-out).
- **Engagement chip in the lead drawer header**, sibling of the
  ICP pill. Renders as `ENG 75/100` with the same `qualify_in /
  borderline / qualify_out` colour classes the ICP pill uses (no
  new CSS). Multi-line `title=` tooltip explains the breakdown:
  *"Coverage: 80% of active contacts touched (24 pts) · Recency: 5d
  ago (25 pts) · Activity: 7 events in last 30d (18 pts) · Key
  contact touched recently (+10 pts)"*. Fires after the first paint
  so it doesn't block the drawer.

### Tests

- **`tests/test_engagement_score.py`** — 16 tests:
  - 14 scorer unit tests: empty inputs, no-engagement zero, full
    coverage + recency, recency band cliffs (0/7/14/30/60/90/180d
    spot-checks), activity volume ramp + cap, old events ignored,
    overdue penalty cap, key-contact bonus fires + skipped-when-old,
    dormant/left contacts excluded from coverage, score clamping
    both ways (never >100, never <0), band boundary at 75
  - 2 endpoint tests: empty account returns the well-formed shape,
    real seeded data (contact + note + call) lands a reasonable
    score end-to-end

### Why a separate score (not roll it into ICP)

ICP and engagement answer different questions and rotate at
different speeds. ICP is "should this deal be in our pipeline at
all" — barely moves once captured. Engagement is "are we earning
this deal" — shifts week-to-week as the AE works it. Mixing them
loses both signals. Two chips, two purposes.

## [1.0.0as] — 2026-05-23 — Account engagement timeline + filter chips

v1.0.0ar gave the Account view a structure (org chart) and a
summary; v1.0.0as gives it a history (timeline) and a focus
(filter chips). The Table shows who; the Org chart shows where they
fit; the Timeline shows what's actually happened.

### Added

- **`GET /api/lead/<id>/engagement-timeline?limit=N`** — unified
  reverse-chronological feed merging three sources:
  - per-contact stakeholder notes (`lead_contact_notes_store`)
  - lead-level calls (`calls_store`)
  - last-touched timestamps from `contacts_store` (one per contact,
    de-duped against same-second note events)
  Each row carries `ts`, `kind` ("note" | "call" | "touch"),
  `title`, `actor`, `contact_id`/`contact_name` (best-effort match
  by attendee name for calls), `preview` (first 240 chars + ellipsis),
  `raw_id`. Plus a stats block: total + per-kind counts + how many
  contacts have any engagement at all.
- **Timeline view-mode** in the Account toolbar (third button after
  Table / Org chart). Renders the feed with per-row kind icon,
  contact-name button (click → open stakeholder notes for that
  contact), preview text, time-ago. Top-of-list summary: "12 events
  · 5 notes · 3 calls · 4 of 7 contacts engaged".
- **Filter chips** in the toolbar: All / Engaged / Overdue / Key.
  Apply to the Table and Org chart; greyed out + non-interactive on
  Timeline (which is account-wide by nature). Filter to "engaged"
  shows only contacts with `last_touched_at`; "overdue" uses the
  existing touch-state annotation; "key" filters to `is_primary`.
- **`phone` icon** added to the icon set for call rows in the
  timeline.

### Tests

- **`tests/test_engagement_timeline.py`** — 12 tests:
  - empty account (zero contacts) returns empty items + stats
  - contacts-without-engagement reports 0 engaged / N total
  - mixed sources sorted newest first (note/call/note interleaved
    with 1.1s sleeps for deterministic timestamps)
  - long content truncated to 240 chars + ellipsis
  - contact attribution: notes carry contact_id + name
  - calls with matching attendee attribute to the contact
  - calls with no matching attendee land as account-level (no contact)
  - touch-event dedup: note-add fires an auto-touch; the touch
    shouldn't appear separately (second-level timestamp compare
    because notes use microseconds, contacts use seconds)
  - limit clamping (default 100, explicit 5, bad value falls back)
  - stats count contacts-with-engagement correctly

### Implementation notes

- **Per-second timestamp dedup**: `lead_contact_notes` writes
  microsecond precision; `contacts_store` writes second precision.
  The naïve `n["ts"] in touch_iso_set` never matched. Fixed by
  truncating at `"."` for the comparison key — production already
  produces this exact pattern, the test confirms it.
- **Call → contact match via attendee**: cheap heuristic. If the
  first attendee on a call matches a contact's name (case-
  insensitive), the call clusters under that contact in the
  timeline. Misses are fine — they just render as account-level.

## [1.0.0ar] — 2026-05-23 — Account view: engagement summary + org chart + stakeholder notes

Ben asked: "There also needs to be an account view in which you can
see the contacts that you have engaged maybe the ability to add
stakeholder notes as well as an org chart to map the account
appropriately."

Stakeholder notes per contact already existed via
`lead_contact_notes_store` (the note icon on each contact row). The
two missing pieces: an engagement summary so you can see at a glance
how the account is being worked, and an org chart so you can map
the buying group.

### Added

- **`reports_to_id`** on lead-side contacts (mirrors the
  partner_contacts_store pattern). Empty/whitespace normalises to
  None so the chart treats unanchored contacts as roots.
- **Account view toolbar** in the lead drawer's Contacts section:
  one-line engagement summary (`5 contacts · 3 engaged · 1 overdue
  · 1 key`) + Table/Org chart toggle. Hidden when there are no
  contacts so the empty state isn't cluttered.
- **`_renderLeadOrgChart`** — vertical tree built from `reports_to_id`
  chains. Each node card shows name + title + key/dormant/left
  chips + last-touch state + note + edit buttons. Click any node to
  open its stakeholder notes. Cycle guard caps recursion at 8
  levels so a corrupted FK can't blow the stack.
- **"Reports to" picker** added to both the manual-add form and the
  edit form. The edit form lists every other contact on the lead;
  the add form's options refresh whenever `loadLeadContacts` fires.

### Tests

- **`tests/test_lead_contact_reports_to.py`** — 6 tests: default is
  None, persists and round-trips, empty string + whitespace
  normalise to None (form-field hygiene), update clears the field,
  list/save cycle preserves the FK across multiple contacts.

### Why a toolbar inside the existing section, not a separate view

Considered a new top-level "Account" view in the nav. Held back:
the lead drawer is already the natural context for everything
account-scoped (calls, scope, pricing, contacts), splitting it
across two surfaces would force the AE to context-switch. The
toolbar gives the new org-chart view first-class status without
breaking the existing flow.

## [1.0.0aq] — 2026-05-23 — Fix: Notion 400 when DB lacks a property we wrote

Ben hit "Save failed: Notion POST /pages 400: ... For is not a property
that exists." (truncated in toast — full message: "Sourced For is not
a property…"). His DB pre-dated v1.0.0z, which added the "Sourced For"
multi_select. Without a recovery path, ONE missing column 400s the
WHOLE save and the AE loses every edit in the batch.

### Fixed

- **Defensive retry in `NotionSync.update_page`**: new
  `_patch_page_with_missing_property_recovery` wraps the PATCH. If
  the first call 400s with "X is not a property that exists", the
  helper parses X from the error, strips it from the payload, and
  retries once. The user's other edits land; only the missing-prop
  field is dropped. Logs the dropped name so the operator sees it.
- **Boot self-heal extended** to create "Partner Source" and
  "Sourced For" on app start. Same fix in the lazy retry path so a
  Notion-unreachable-at-boot scenario also gets healed when the
  first mirror call runs.

### Tests

- **`tests/test_notion_missing_property_recovery.py`** — 6 tests
  with `_request` patched: recovery on the standard error, multi-
  word property names, unrelated 400s aren't swallowed, second-
  attempt failure propagates (no infinite loop), parser miss
  propagates original error (no silent partial save), strip-leaves-
  empty → no-op response (no empty PATCH).

### Why narrow recovery, not a broad pre-check

I considered fetching the DB schema before every PATCH to pre-filter
unknown props. Rejected: that's a round-trip per write, and the
boot self-heal already covers the common case. The recovery path is
the safety net for DBs that haven't received the latest self-heal
list (e.g. user has the app deployed but a separate DB they switched
to mid-session). Cost is only paid on the rare miss.

## [1.0.0ap] — 2026-05-23 — Team activity feed on Home

Notifications are "what's for you"; activity is "what's happening".
This adds a Home card that surfaces recent changes across leads,
partners, and contacts so you can see what teammates have been doing
without digging through each surface.

### Added

- **`activity.py`** — pure formatter that converts raw audit events
  into display rows. Curated `INTERESTING_EVENT_TYPES` allowlist (27
  kinds covering lead/scope/SOW/partner/contact lifecycle) drops the
  noisy internals (`pricing_preview`, `state_backup_mirrored`,
  `notion_sync_started`, etc.). Per-type summary branches in
  `_summary_for` turn `{type:"lead_updated", fields:["company"]}`
  into "renamed lead → Acme Corp". Entity ids resolve to display
  names via injectable `partner_names` / `lead_names` lookups.
- **`GET /api/activity?limit=N`** — pulls the last `limit*4` raw
  events (to give the filter headroom), builds the partner-id →
  name map from `partners_store.list_partners()`, fetches the
  pipeline once for lead-id → company names, then returns the
  formatted rows. `limit` clamped to 1–100 (default 20). Notion
  failure → fall back to short page-ids inside the formatter, never
  500.
- **Home "Team activity" card** — fetched separately from
  `/api/home` so the personal payload stays fast. Renders up to 10
  rows with actor + verb + entity link + time-ago. Click any row
  with a link routes to the entity (re-uses the v1.0.0an
  `_openTodoLink` helper). Refresh button for an on-demand pull.
  Hidden when the activity log is empty.

### Tests

- **`tests/test_activity.py`** — 19 tests:
  - 13 formatter unit tests (empty input, uninteresting-types
    dropped, per-event-kind summary shape, owner-change reads as
    reassignment, name-rename detection, link routing for each
    entity kind, actor default, lead-name fallback chain
    (lookup → company field → short id), input-order preservation,
    forward-compat fallback for allowlisted-but-unhandled types)
  - 6 endpoint tests (empty log, allowlist filter, limit clamping,
    default limit = 20, bad limit falls back, partner-name
    enrichment confirmed end-to-end)

### Why a separate fetch, not folded into /api/home

`/api/home` already calls Notion + dashboard rollup + multiple
stores. Adding the activity scan + name enrichment inflated its p50
in early prototypes. The activity feed lives outside the critical
path so the greeting/KPIs paint immediately and activity backfills
when ready.

## [1.0.0ao] — 2026-05-23 — Overdue todo notifications + lead-PATCH test coverage

Closing the loop on todos + notifications: a todo with a `due_date`
that slips past today now fires a bell notification the next time
the user opens Home. Plus fills in the missing test coverage for
the lead-PATCH notification path that v1.0.0al added without tests.

### Added

- **`todos_store.sweep_overdue_and_mark(owner, today_iso=None)`** —
  finds open todos with `due_date < today` that haven't been
  overdue-notified yet, marks them with `overdue_notified_at`, and
  returns the list so the caller can fire bell notifications.
  Idempotent: the second sweep with the same date returns `[]`.
  `today_iso` is injectable so tests can drive the calendar.
- **`overdue_notified_at` field** on every todo, normalised to `None`
  by default. Cleared automatically when the user changes the
  `due_date` (so pushing a date forward then back re-arms the
  notification); preserved on unrelated edits.
- **Home endpoint integration** — `/api/home` calls the sweep on
  every load and fires a `todo_overdue` bell notification for each
  newly-marked todo. The notification's link mirrors the todo's
  link (so clicking goes to the underlying lead/contact if there
  was one), or is null (so clicking just marks-read). Wrapped in
  try/except — sweep failures never block the Home payload.

### Fixed (test coverage gap)

- **Lead-PATCH notification path** — v1.0.0al added the trigger
  but the test class (`NotificationsEndpointTests`) only covered
  the partner-contact path because the lead path needs `NotionSync`,
  which we can't reach in-test. Two new tests use `unittest.mock`
  to patch `server.NotionSync` and confirm:
  - reassigning a lead's owner fires `assigned_lead` with the
    correct title, body, and link
  - PATCHing without changing the owner doesn't fire

### Tests

- **`tests/test_todos.py`** grew 34 → 42 (+8 sweep tests):
  empty-when-no-overdue, picks-up-overdue + persists notified_at,
  idempotent (second sweep returns nothing), skips done, skips
  no-due-date, today != overdue (strict `<` comparison), changing
  due_date clears notified_at, same due_date update preserves it.
- **`tests/test_notifications.py`** grew 18 → 20 (+2 lead-PATCH
  tests as above).

### Implementation notes

- **No background scheduler** — Railway's web tier is stateless,
  and a per-user worker would be overkill for what's essentially
  a "check on app open" check. The sweep is cheap (single file
  scan + per-row date string compare), runs on every Home load
  (typically 1–4× per user per day), and the `overdue_notified_at`
  flag means each todo notifies at most once per due-date cycle.
- **Strict `<` not `<=`** — a todo due today is "due today" in
  the UI badge, not overdue. Only past dates fire the sweep.

## [1.0.0an] — 2026-05-23 — Todo↔entity linking + quick-add buttons

The v1.0.0am todo list is a scratch list. This makes it operational:
todos can now point at a lead, partner, or partner contact, and you
can spawn linked todos from the overdue / active-leads cards on
Home + every row in the partner contacts table.

### Added

- **`link` field on todos** — optional object with `kind` (one of
  `lead`, `partner`, `partner_contact`) + the entity-id keys
  required by that kind + an optional `label` for display. Allowlist
  validation rejects unknown kinds and missing required ids;
  forward-compat extra keys are silently dropped. `_validate_link`
  in `todos_store.py` is the single source of truth.
- **API support**: `POST /api/todos` and `PATCH /api/todos/<id>`
  both accept `link`. Setting `link: null` clears it.
- **UI — "→ <label>" chip** on every linked todo in the Home panel.
  Click navigates to the entity (lead drawer / partner detail) and
  uses the same routing helper as notification clicks for
  consistency.
- **Quick-add buttons** on Home:
  - "+ todo" on every row of the overdue-contacts card — pre-fills
    "Reach out to <name> (<partner>)" and creates a `partner_contact`
    link.
  - "+ todo" on every row of the active-leads card — pre-fills
    "Move <company> forward" and creates a `lead` link.
- **Quick-add button in the partner contacts table** — small `+`
  button between the touch-check and edit icons. Same pre-fill
  pattern, scoped to the row's contact.

### Tests

- **`tests/test_todos.py`** grew from 23 → 34 tests with 11 link
  cases: create-with-each-kind, unknown-kind rejection, missing
  required-keys rejection, not-a-dict rejection, clear-via-update,
  extra-fields-dropped (forward-compat), label optionality, plus
  3 endpoint tests (create with link, bad link rejected, PATCH link).

### Why this and not "make todos available everywhere"

I considered surfacing todos in the nav too. Held back: the Home
view already pulls them into the first paint, the bell is right
next to it, and adding a third badge to the header crowds the bar.
The link chips give todos a path back into the entity surfaces
without inverting which is "primary" — the entities lead, the
todos follow.

## [1.0.0am] — 2026-05-23 — Custom todo list on Home

Ben asked: "They should also be able to create a custom to do list on
their home page." Done — a personal scratch list under the existing
KPIs that persists across sessions.

### Added

- **`todos_store.py`** — JSON-file-per-owner store with `list_for`,
  `create`, `update`, `toggle_done`, `delete`, `clear_completed`.
  Each todo: text + done flag + optional priority (high/medium/low)
  + optional due_date (YYYY-MM-DD) + created/completed timestamps.
  Validates priority against an allowlist; rejects empty / overlong
  text; rejects unknown fields on update.
- **API**:
  - `GET /api/todos?owner=&include_done=` — list (defaults to all)
  - `POST /api/todos` — create with `{owner, text, priority?, due_date?}`
  - `PATCH /api/todos/<id>` — partial update (text, done, priority, due_date)
  - `POST /api/todos/<id>/toggle` — flip done in one call
  - `DELETE /api/todos/<id>?owner=` — hard-delete
  - `POST /api/todos/clear-completed` — bulk-remove done items
- **Home payload** now includes `todos: { items, open_count, total }`
  so the panel renders with the first Home fetch.
- **UI — "Your todos" card on Home**: inline add form (text + priority
  dropdown + date picker + Add button, Enter submits); list with
  checkbox + line-through-on-done + priority chip + due-date badge
  (red if overdue, amber if within 3 days, muted otherwise) + delete
  button; "Clear completed" button appears when there's anything to
  clear. Sort: open before done; within bucket, priority high > med
  > low > none, then due ascending, then newest first as tiebreak.

### Tests

- **`tests/test_todos.py`** — 23 tests covering store (CRUD, text
  validation with strip + length cap, priority allowlist, due-date
  shape, done sets/clears completed_at on transitions only, toggle,
  delete, clear_completed, sort order with all four sort keys exercised,
  include_done filter, per-owner isolation, owner_required) + endpoints
  (list, create, update, toggle, delete, clear-completed, full CRUD
  cycle, include_done query param, allowlist rejection).

### Implementation notes

- **`toggle_done` lock discipline**: initially called `update()` from
  inside the `_LOCK`, which deadlocked because `threading.Lock` is
  non-reentrant. Now reads the current `done` value under the lock,
  then exits and delegates to `update()` (which acquires the lock once
  for the write). Tiny TOCTOU window between read and write is fine
  for a single-user scratch list.
- **Sort order via composite key**: priority + due ascending + created
  descending in one `.sort(key=...)` call by inverting created_at
  codepoints (so newer ISO timestamps sort earlier in an ascending
  sort). Avoids the cost of a second pass.
- **No ring buffer**: notifications are auto-generated and capped;
  todos are user-curated, so we trust the user to clean up. The
  `clear-completed` endpoint exists for bulk cleanup.

## [1.0.0al] — 2026-05-23 — Notifications system (bell + Home panel)

Ben asked: "Should be notifications as well. When contacts or accounts
are being assigned to a person."

This adds a first-class notification surface for ownership changes —
when someone reassigns a partner contact or lead to you, you find
out without having to refresh the table.

### Added

- **`notifications_store.py`** — JSON-file-per-recipient store with
  `notify_assignment()`, `list_for()`, `unread_count()`, `mark_read()`,
  `mark_all_read()`. Ring-buffer cap of 200 per recipient so files
  stay small. Thread-safe via module-level lock. Empty recipient is
  a no-op (avoids crashing the trigger path when an unowned entity
  gets touched).
- **Trigger points** in `server.py`:
  - Partner contact PATCH detects `mr_owner` change and fires
    `assigned_partner_contact`. First-time assignment doesn't fire
    (only changes do); self-assignment doesn't fire.
  - Lead PATCH peeks the previous `owner` via `NotionSync.get_page`
    before the update, then fires `assigned_lead` if it changed.
  - Both wrapped in try/except — a notifications glitch never
    blocks the underlying save.
- **API**:
  - `GET /api/notifications?recipient=&unread=&limit=` — list +
    unread count
  - `GET /api/notifications/unread-count?recipient=` — lightweight
    badge poll (60s interval from the UI)
  - `POST /api/notifications/<id>/read` — single mark-read
  - `POST /api/notifications/read-all` — bulk mark-read
- **UI — bell in the nav**: red badge with unread count; click for
  a dropdown panel showing the last 20 with status dots, time-ago,
  and click-through navigation that marks-read + opens the entity
  (partner detail or lead drawer). "Mark all read" wipes the badge.
  Hidden until a profile is set.
- **UI — Home "Recent assignments" panel**: rendered from
  `home.notifications.recent` (top 5). Hidden when there's nothing.
  Click any row to open and mark-read; "See all →" opens the bell
  dropdown for the full list.

### Tests

- **`tests/test_notifications.py`** — 18 tests covering: normalised
  shape, empty-recipient no-op, sort order (newest first with
  same-second tiebreak), unread filtering, unread_count, mark_read
  idempotency, mark_all_read, ring-buffer cap (210 written → 200
  retained, newest preserved), per-recipient isolation, wrong-recipient
  mark_read silent fail, and 6 endpoint tests including the
  partner-contact reassignment fires-notification path + the
  no-change-no-notification path.

### Implementation notes

- **Polling, not WebSockets**: 60s `setInterval` on
  `unread-count` is cheap (single file read + integer count) and
  side-steps the operational complexity of a long-lived connection
  on Railway's stateless web tier. Open the dropdown for an
  immediate full refresh.
- **Sort stability**: file order is append-on-write (oldest first),
  but multiple notifications can land in the same second. The list
  reverses BEFORE the descending sort so same-second ties fall
  newest-first naturally; otherwise stable sort would keep them
  oldest-first inside the tied group.

## [1.0.0ak] — 2026-05-23 — Inline rename for partners + project name clarity

Ben asked to "edit company names" — v1.0.0aa fixed the lead drawer,
but partners and projects still had stuck names. This rounds out
the other two surfaces.

### Added

- **Inline partner rename** in the partner detail header. Pencil
  button next to the partner name swaps the title for an
  `<input>` + Save/Cancel. Save PATCHes `/api/partners/<id>` (the
  endpoint already accepted arbitrary field merges), then re-opens
  the detail so contacts + filters re-bind cleanly against the
  renamed partner. Refreshes `refreshPartners()` so the side list +
  global picker pick up the new name without a page reload.
  Keyboard: Enter saves, Escape cancels.

### Fixed

- **Project name label** in the Project Build view. Previously
  read "Or new lead — company name", which felt broken when an
  AE was loading an existing project to rename it. Now reads
  "Company name" with a `<small>` hint: "Edit to rename this
  project; saves with the next Save scope." The save flow itself
  was already correct (`pbSave` passes `company_name`, the server
  upserts via `project.company_name = company_name`); only the
  label was misleading.

### Notes

- Project name editing has been functional since first-cut, but
  was discoverable only by knowing the input was bi-modal. The
  label clarification makes it usable without prior knowledge.
- Lead rename remains as v1.0.0aa: edit Company in the drawer
  field, hit Save; the drawer title + meta refresh from the
  server-confirmed PATCH response.

## [1.0.0aj] — 2026-05-23 — "My contacts" filter + partner table formatting

Ben flagged the partner-contacts table from the screenshot: owner
names truncating ("Ben Ojuolape" → "Ben C") and the Last touch
column wrapping into three lines. Plus he wanted a "My contacts"
filter so AEs can scope the table to just their book.

### Added

- **"My contacts" filter chip** in the partner-contacts toolbar.
  Reads the localStorage profile (set in the v1.0.0ah Home view)
  and scopes the table to contacts where `mr_owner` matches the
  current user. Prompts the user to pick a profile if none is set.
  Works in both Table and Org-chart sub-views.

### Fixed

- **Owner cell truncation**: the inline `<select.inline-owner-cell>`
  used `max-width:100%` with no `min-width`, so on narrow columns
  the browser shrink-fit the control to "Ben C" or similar. Added
  `min-width:130px` + `text-overflow:ellipsis` so names render in
  full (or ellipsize at the longest sensible width, not the first
  three characters).
- **Last touch column wrapping**: the formatter stacked two `<div>`s
  (label over status) which on narrower columns wrapped each div
  onto two more lines — 4 rows in a single cell. Rewritten as a
  single inline `<span>` with `white-space:nowrap`, joining label
  and status with a middle-dot separator. Both the owner column and
  the touch column now opt into `white-space:nowrap` at the `<td>`.
- **Partner contacts table overflow**: with 12 columns (after
  v1.0.0ac added Tier/Sentiment/Seniority) the table no longer fits
  in narrower drawers. The `#ptn-contacts-table` container now has
  `overflow-x:auto`, so wide rows scroll horizontally instead of
  forcing cells to wrap.

### Test stability

- **`SKIP_COMMAND_CENTRE_SEED=1`** added to
  `test_contacts_search.py` + `test_partner_touch_cadence.py`
  setUpClass. Without the flag, the boot-time auto-seed of
  Braze + Hightouch (181 contacts, many owned by "Ben") landed in
  the test temp dir and broke owner-filter assertions — the seeded
  data was alphabetically before the fixtures, so seeded contacts
  consumed the 50-result limit. The flag has existed since v1.0.0j;
  these two test classes had simply never set it.

## [1.0.0ai] — 2026-05-23 — SOW generator rewritten to MR Training Brief

Ben shared the MR SOW Training Brief (May 2026) and asked the SOW
draft to demonstrate a preview. The brief is comprehensive: master
structure with 13 required body sections, specific clauses with
required verbatim text, naming convention, and a Section 5 pre-export
checklist. The previous generator was missing most of it.

### Now produced in every SOW snapshot

**Required body sections** (brief Section 2.3):
1. Document Status table (Draft / Next steps Company / Next steps MR)
   — visible in preview, hidden on print, includes a "remove before
   export" reminder
2. Opening Clause — references MSA date + names both legal entities
   (Massive Rocket Limited + Company). Flags placeholder if MSA
   date isn't supplied.
3. Timing & Fees — currency (GBP/EUR/USD), commencement date, duration
4. Executive Summary — client-specific, includes Project Timeline table
5. Engagement Overview — industry, region, revenue, employees, streams
6. Services In Scope — by stream, with qualifying-vs-confirmed pills
7. Services Out of Scope — includes brief-required items (Platform
   Training, Creative Services, Engineering, External Documentation)
8. Commercial Summary — totals + monthly schedule + 3 verbatim clauses:
   - **80% consumption notification** (with 100% pause right)
   - **10% contingency buffer** (with Annex 1 reference)
   - **Blended rate statement** (£150/€175/$200 — by currency)
9. Project Management — agile cadence, weekly reviews, Jira sign-offs
10. Monitoring Progress — risk + delay notification obligations
11. Company's Participation — platform access SLAs, project owner,
    sign-off windows
12. Variations & Change in Scope — references Annex 1, rules out
    verbal/Slack agreements
13. Changes of Date — Company-caused delay handling
14. General Notes & Assumptions — LinkedIn case-study clause,
    software licence exclusion, 10% annual fee increase clause
15. Signatures — Thierry Sequeira (Director) for MR + Company block
16. **Annex 1: Change Order template** — 11-field template, always
    included, even if unused

**Non-binding appendices** (when present): Roadmap, Beyond Year 1
extended engagement, Team & Phases. Banner explicitly labels them
non-binding, per brief Section 2.4.

### Naming convention (brief Section 2.1)

Every SOW's title is now `Appendix A — [Client] — Statement of
Work — DD MMM YYYY` (current date). Matches the regex the brief
mandates.

### Brief-compliance side panel

Every SOW preview now ships with a side panel (right of the page,
hidden on print) showing:
- **Warning list** with severity tags — TBC in scope values, missing
  MSA date, missing currency, empty start date, empty out-of-scope,
  no commercial totals, missing Project Timeline
- **Pre-export checklist** — 23 items from brief Section 5, each
  marked passed (✓ green) or failed (✗ red)
- **Compliance score** — "Brief compliance · 21/23" at the top

This is the user's "preview demonstrate" — the AE sees both the SOW
content AND the brief-compliance audit in one view, before deciding
to draft a version.

### Dry-run Preview button

New **"Preview SOW"** button next to "Draft SOW" in Project Build.
Hits the new `GET/POST /api/sow/<id>/preview` endpoint which renders
the SOW from current state **without saving a version**. Lets the AE
iterate (fix scope, add MSA date, change currency) and see the
compliance panel live before committing.

Also new `GET /api/sow/<id>/compliance` JSON endpoint for any
caller that wants the warnings + checklist without rendering HTML.

### Configurable inputs

`build_snapshot` now takes optional kwargs:
- `msa_date` — pass the MSA date to populate the Opening Clause
- `start_date` — pass commencement date to populate Timing & Fees
- `currency` — GBP / EUR / USD (drives blended-rate clause)
- `company_legal_name` — override the project's company_name with
  the full registered legal entity

All four are passed through from the Preview body so the AE can
A/B different inputs without committing.

### Brief failure patterns surfaced as warnings

Cross-referenced from brief Section 3:
- **TBC in commercials / scope** (Section 3.1) → high-severity warning,
  cites the brief
- **Missing MSA date** → high-severity, with `[MSA DATE PENDING]`
  placeholder visible in the rendered SOW so it's impossible to miss
- **Empty Services In Scope** → high-severity (Section 3.1 fallback)
- **Empty currency / start date** → high-severity (Section 4.1)

### Files touched
- `sow.py` — full rewrite (~750 lines). New constants for all required
  boilerplate clauses (verbatim per brief), `compliance_check()`
  function, restructured `build_snapshot` + `render_html`. Side panel
  + Document Status table CSS added to the print stylesheet.
- `server.py` — `/api/sow/<id>/preview` (dry-run, GET+POST) +
  `/api/sow/<id>/compliance` (JSON-only) endpoints
- `qualify.html` — new "Preview SOW" button + `previewSowDryRun()`
  handler; wired into Project Build view
- `tests/test_sow_brief.py` (new, 32 tests) — locks in brief
  structure, required clauses, naming convention, blended rate by
  currency, signatory block, compliance check behaviour, dry-run
  preview semantics

### Tests
- 612 total (+32). Existing 16 SOW tests still pass — the new
  structure adds fields without removing any.

### What you'll see
- Click **Preview SOW** in Project Build → modal opens with the full
  brief-compliant SOW + a side panel showing compliance score (e.g.
  "21/23 passed") + a checklist of every section, with warnings
  highlighted in red for things like missing MSA date.
- Click **Draft SOW** as before → commits a version. The preview
  modal auto-opens after the draft, same as today.

## [1.0.0ah] — 2026-05-23 — Personalised Home view as the default landing

Ben asked: "Personalised Dashboard based on their role should be the
first page the user sees when opening up the [app]."

### The Home view

New default landing surface (Home nav tab, leftmost). Shows:
- **Time-of-day greeting** ("Good morning, Ben") + role + region
- **5 personal KPIs** (last 30 days): touches you logged, partner
  contacts you own, your overdue contacts (red-tinted if >0), your
  active leads, team-wide cadence compliance %
- **Your overdue contacts**: top 5 partner contacts on your book that
  have slipped past cadence. Each row links to the partner detail.
- **Your active leads**: top 5 leads you own (sorted by recent
  activity). Each row opens the lead drawer.
- **Team snapshot card**: 4 team-wide stats so a single number
  comparison (your touches vs team touches) is one glance away. Link
  to the full Dashboard view.
- **Role-aware extra card**:
  - CEO / Director of Growth → Executive view (team touches /
    active leads / team overdue)
  - Marketing roles → Marketing view (new leads / qualified count /
    in-pipeline)
  - All other roles → no extra card (the personal stats are the view)

### Profile picker

No per-user auth in the platform today, so we identify the user via
a localStorage profile picker:
- **First load** → modal lists all 12 MR owners (from
  `mr_owners.list_owners`) with role + region. Pick yours → saved
  to `localStorage.mr-profile` → Home renders.
- **Subsequent loads** → reads the saved profile and skips the
  picker. Home loads directly.
- **"Switch profile"** button in the Home greeting card re-opens
  the picker so you can switch (or shadow another role for testing).
- Picker uses the same modal infrastructure as the global search
  (`.doc-preview-overlay` + `.doc-preview-modal`).

### New endpoint

`GET /api/home?owner=<name>` — wraps the existing dashboard
aggregator with owner-scoped KPIs + computed lists. Returns:
```
{
  owner: { name, role, region, email },
  kpis: { touches_30d, partner_contacts_owned,
          partner_contacts_overdue, leads_owned, leads_active },
  overdue_contacts: [ top 5, sorted by most overdue ],
  active_leads:     [ top 5, sorted by recent activity ],
  team_snapshot:    { touches, active_contacts, overdue, compliance_pct },
  role_extras:      { exec?, marketing? }
}
```

400 if `owner` query param missing; 404 if owner name doesn't
resolve to a known MR person; 200 with empty leads if Notion is
down (partner-side stats still come through).

### Role detection

`role_extras` is keyword-matched against the owner's `role` string
so a label rename ("AE → AM") doesn't break this:
- `"ceo"` or `"director of growth"` in role → `exec` block
- `"marketing"` in role → `marketing` block
- Otherwise → no extras (sales-side default applies)

### Files touched
- `server.py` — new `/api/home` endpoint
- `qualify.html` — Home view markup, profile-picker modal, all the
  Home JS (`ensureProfileSelected`, `loadHome`, `_renderHome`,
  `reopenProfilePicker`), nav button + init wiring
- `tests/test_home.py` (new, 12 tests)

### Tests
- 580 total (+12). Covers: 400/404 errors, full shape, per-owner
  KPI scoping, top-overdue ordering, lead filter excludes
  disqualified, role-extras gating (CEO + Director both get exec;
  Jamie + Lea both get marketing; AM gets neither), graceful
  degradation when Notion is unreachable.

### What you'll see

Open the app:
1. **First time ever**: modal appears — "Who are you?" — pick from
   the 12 names with role + region tooltips. Saved to localStorage.
2. **Every subsequent visit**: Home loads instantly with your
   personal book — greeting at the top, your KPIs across the row,
   your overdue contacts on the left, your active leads on the
   right, team-wide snapshot at the bottom for comparison.
3. **Switch profile** in the greeting card if you ever want to see
   the platform through a teammate's lens (or for testing).

## [1.0.0ag] — 2026-05-23 — Settings panel: chip-list editor, not textareas

Ben pointed out that the v1.0.0ac settings panel — seven monospace
textareas in a grid — was bad for editing. He was right: you had to
scroll inside each textarea to see the full list, no visual feedback
on what was added/removed, no "what's a default vs custom" cue, and
the monospace font felt like editing a config file.

### Redesign

Each enum is now a proper **tag editor**:
- Every value is a visible **chip** in a soft-bordered list area
- × button on each chip removes it (and immediately saves)
- **Add input** at the bottom: type a value, press Enter (or click
  Add). Duplicate detection is case-insensitive — pasting a value
  that's already there toasts "already in the list" instead of
  silently deduping
- The Add input **re-focuses after a successful add** so power users
  can type-Enter-type-Enter through a list without reaching for the
  mouse
- **Per-card immediate save** — no batch Save button. Each add /
  remove fires a PATCH and re-renders. Reset still confirms before
  acting since it's destructive.
- Each card carries a **hint subtitle** ("Importance to MR", etc.)
  + a value count ("13 values"). Less guessing about what each enum
  means in practice.

### Visual
- Bigger card padding (12px / 18px panel padding) — breathes
- Cards lift out from the panel surface via background contrast
  (`--surface-2` panel → `--surface` cards)
- Chip rows have their own inset background so the list reads as a
  distinct element
- Chip × buttons hover-tint red so destructive intent is signalled
- Subtle panel drop-shadow so it visually elevates above the
  Partners list
- Light + dark mode both first-class (uses `var(--surface)` /
  `var(--input-bg)` etc.)

### Files touched
- `qualify.html` — new CSS for `.enum-card` / `.enum-chip` etc.,
  rewritten `_renderEnumSettings` + new `_enumCardHtml` /
  `_wireEnumCards` / `_commitAdd` / `_saveEnumKey` helpers

### Tests
- 568 still passing. UI-only change.

## [1.0.0af] — 2026-05-23 — Retire the last orange hues — MR Red is the only warm

v1.0.0ae replaced the old soft orange (`#ff4d2a`) with MR Red but
left two distinct pure-orange uses in place: the **CRM Execute**
workstream colour and the **Cool sentiment** chip. Both sat next to
MR Red surfaces and read as competing brand colours.

### Replaced
- **CRM Execute** workstream: `#f97316` (orange) → `#14b8a6` (teal).
  CRM Build keeps MR Red; CRM Execute now distinct + non-competing.
  Other workstream swatches (Strategy blue, Data green, Engineering
  purple, Cross-cutting grey) unchanged.
- **Cool sentiment chip**: `#f97316` (orange) → `#64748b` (slate).
  Bonus: a literal "cool" sentiment reads more naturally in a slate-
  grey-blue than in warm orange.

### Updated
- Forecast distribution-bar legend comment "orange=pipeline" updated
  to "red=pipeline" since the bars are now MR Red (v1.0.0ae change).

### Net effect
No orange anywhere on the platform. MR Red is the only warm colour
in the brand palette — anywhere you see something "warm", it's the
brand.

### Tests
- 568 still passing. Pure colour change.

### Files touched
- `qualify.html` — 3 colour swaps + 1 comment update

## [1.0.0ae] — 2026-05-23 — Adopt the Massive Rocket brand palette

Ben shared the official MR brand theme. Platform's design tokens now
map to it directly.

### Two-layer design system

**Layer 1 — brand swatches** (single source of truth, in `:root`):
```css
--mr-red:        #e82b23;   /* MR RED  */
--mr-red-light:  #ffdad8;   /* LIGHT MR RED */
--mr-dark-gray:  #212227;   /* DARK GRAY */
--mr-light-gray: #f6f6f6;   /* LIGHT GREY */
--mr-yellow:     #fbbc04;   /* YELLOW */
--mr-green:      #34a853;   /* GREEN */
--mr-blue:       #355881;   /* NEW HOME DARK BLUE */
--mr-postit:     #fff2cc;   /* POST-IT */
```

**Layer 2 — functional tokens** map to the brand layer:
- `--accent` → `var(--mr-red)` everywhere (was `#ff4d2a`)
- `--green` → `var(--mr-green)` in dark mode; AA-darker variant on
  light (`#1f7a3f`) for text contrast — MR Green fails AA on white
- `--yellow` → `var(--mr-yellow)` in dark mode; AA-darker amber
  (`#8b6914`) on light — MR Yellow fails AA badly on white at 1.6:1
- `--blue` → `var(--mr-blue)` on light (~6.8:1 contrast on white);
  lighter shade (`#6e94c5`) in dark mode for legibility
- `--surface` (dark mode) → `var(--mr-dark-gray)` — was `#13131a`
- `--bg` (light mode) → `var(--mr-light-gray)` — was `#f7f7f2`
- `--text` (light mode) → `var(--mr-dark-gray)` — was `#1a1a24`
- All radial gradients, focus rings, drop shadows recoloured to MR
  Red + MR Blue tints

### Mass-changed everywhere

Every hardcoded `rgba(255,77,42,...)` (43 sites) and bare `#ff4d2a`
(across `qualify.html`, `project_preview.py`, `sow.py`) replaced
with the MR Red equivalent in one sweep — the brand-orange platform
becomes brand-MR-red without component-level edits.

### Why two layers?
- Component CSS keeps using semantic tokens (`var(--accent)`) — no
  component knows or cares about brand colour values
- If MR's brand evolves (or for a future fork / white-label), edit
  the `--mr-*` block once and every surface inherits
- The brand swatches stay exposed for any future need that
  references them by name (e.g. an export to a brand-coloured PDF
  in pricing.py)

### Notes
- **Brand red doubles as accent**, not as error. `--red` stays as
  the standard alert red (`#ef4444` dark / `#b91c1c` light) so error
  states keep semantic separation from brand surfaces.
- **Brand green + yellow fail AA on white**. For backgrounds + tints
  we still use the MR brand hex with translucency (rgba); for TEXT
  contrast on white we swap to darker variants in light mode.
- **MR Blue is too dark for dark-mode legibility** as a foreground
  colour, so dark mode uses a derived lighter shade (`#6e94c5`).
- The 13 Chart.js fills + the per-criterion chart colours (revenue
  blue, employees purple, etc.) intentionally stay as-is — they're
  functional differentiators, not brand colours.

### Files touched
- `qualify.html` — token reorganisation + 43 rgba replacements
- `project_preview.py` + `sow.py` — accent hex replacement

### Tests
- 568 still passing. Change is colour-only; no logic touched.

### What you'll see
Refresh the app — every brand surface (Save button, accent links,
hover glow, focus rings, ICP pill, the "Part of: ..." chip, the
incumbent agency tint, the source chip, etc.) now uses MR Red
`#e82b23` instead of the old soft orange `#ff4d2a`. Light mode
background is the brand's Light Grey. Dark-mode card surface uses
MR Dark Gray. The whole platform looks like it was built for MR,
not adapted to MR.

## [1.0.0ad] — 2026-05-23 — Tier defaults reframed around importance to MR

Ben pointed out that "Active" and "Dormant" describe engagement
frequency, not strategic importance. Tier should answer "how much does
losing this relationship hurt us?" — cadence + last-touched already
cover the activity dimension.

### Default tiers now read

| Old | New |
|---|---|
| T1 — Strategic | **T1 — Critical** |
| T2 — Active | **T2 — Important** |
| T3 — Light | **T3 — Nurture** |
| T4 — Dormant | **T4 — Awareness** |

Meaning:
- **T1 — Critical**: relationships we cannot afford to lose
- **T2 — Important**: meaningful pipeline + regular co-sell value
- **T3 — Nurture**: developing — could become Important
- **T4 — Awareness**: they know us; low priority for now

Form helper text updated: *"Tier — importance to MR (not how active)"*
to make the meaning explicit at the point of entry.

### Existing data unchanged
Any partner contact currently saved with "T1 — Strategic" etc. keeps
its label — the store accepts any string. The label just displays in
the table as a free-text tag and won't appear in the new dropdown.
If you want to migrate, edit the contact + pick a new value from the
dropdown.

### Customisable anyway
The Settings panel still lets you replace these defaults with whatever
labels match your team's vocabulary — they're just the starting point.

### Tests
- 568 still passing. Test fixtures referencing the old tier label
  updated.

### Files touched
- `partner_contacts_store.py` — TIERS constant
- `qualify.html` — form helper text
- `tests/test_enum_config.py` — fixture labels

## [1.0.0ac] — 2026-05-23 — Industries + sentiment/tier/seniority + Settings panel

Three requests bundled:
1. Add Entertainment / Gaming / Sports to the industries list
2. Add new partner-contact dimensions: Partner Sentiment, Tier, Seniority
3. Make all of these customisable via a Settings panel

### 1 · New industries (one-line change)
`partner_contacts_store.INDUSTRIES` now includes **Entertainment**,
**Gaming**, **Sports** alongside the existing 10. They flow into every
industry-multi-select chip group automatically via `/api/partners/enums`.

### 2 · Three new partner-contact dimensions
Every partner contact now carries:
- **`partner_sentiment`** — how they feel about MR right now.
  Defaults: Champion / Warm / Neutral / Cool / Blocker. Tinted chip
  in the table (green / yellow / grey / orange / red).
- **`tier`** — strategic importance to the partnership.
  Defaults: T1 — Strategic / T2 — Active / T3 — Light / T4 — Dormant.
- **`seniority`** — escalation path shorthand.
  Defaults: C-Suite / VP / Director / Manager / Individual Contributor.

All three are:
- Saved + restored via `partner_contacts_store._normalise` (None-safe;
  blank strings collapse to None)
- Editable in the contact form (three-column row, below Status)
- Surfaced as columns in the partner contacts table (Tier, Sentiment,
  Seniority) — sentiment column is colour-coded by value
- Filterable from the partners filter row (three new dropdowns)
- Included in `partner_contacts_store.list_contacts` returns + the
  state-backup mirror (no schema changes needed — gather pulls full
  contact dicts)

### 3 · Settings panel — `enum_config_store`

New module `enum_config_store.py` overlays user customisations on
top of the in-code defaults:
- Storage: `cache/enum_config.json` (durable via the volume mount,
  mirrored via nothing — it's small + cosmetic, restore from defaults
  is one click)
- Defaults are pulled from `partner_contacts_store` constants at
  load time, so editing the code constants remains a valid escape
  hatch
- Dedupe + whitespace-strip on save; empty list = "reset to default"
- `reset_key(name)` for explicit single-key reset

### Endpoints
- `GET  /api/settings/enums` — full effective config
- `PATCH /api/settings/enums` — body keyed by enum name, value = list
- `POST /api/settings/enums/<key>/reset` — single-key reset to default

### UI — Settings panel (Partners view header)

New Settings button in the Partners view header. Click → in-page
panel slides in with one textarea per enum (industries, territories,
regions, statuses, sentiments, tiers, seniorities). Each textarea
is one-value-per-line. Save → toast + dropdowns repopulate across
the platform on next refresh. Per-section Reset button restores
that specific enum to platform defaults.

### Plumbing
- `/api/partners/enums` now reads from `enum_config_store` instead
  of hardcoded constants — so user edits surface immediately in
  every dropdown that consumes it (contact form, filter row,
  Partners view, lead-drawer assignment picker, etc.)
- `partnersState.filter` extended with `sentiment`, `tier`,
  `seniority` keys (default empty)
- `_sentimentPalette()` JS helper maps sentiment label keywords to
  consistent colour tokens (green for Champion / yellow for Warm /
  orange for Cool / red for Blocker / grey neutral)

### Tests
- 568 total (+18). `tests/test_enum_config.py` covers:
  - Defaults loaded when no override file exists
  - Save overrides specific keys, leaves others as defaults
  - Dedupe + whitespace strip on save
  - Empty list resets to default
  - Unknown keys + non-list values ignored
  - Single-key reset + unknown-key reset = 400
  - Corrupt JSON falls back to defaults silently
  - New `partner_sentiment` / `tier` / `seniority` fields round-trip
    on partner contacts; blank/None inputs collapse correctly
  - `/api/partners/enums` reflects user overrides immediately

### Files touched
- `partner_contacts_store.py` — 3 new constants, 3 new fields in `_normalise`
- `enum_config_store.py` (new) — overlay-on-defaults store
- `server.py` — `/api/partners/enums` reads dynamic config; 3 new
  `/api/settings/enums*` endpoints
- `qualify.html` — contact form (3 new dropdowns), table (3 new
  columns + sentiment tinting), filter row (3 new dropdowns),
  partnersState.filter, settings panel + button
- `tests/test_enum_config.py` (new, 18 tests)

### What you'll see

**On any partner contact edit form**: three new dropdowns under
Status — Partner sentiment / Tier / Seniority. Defaults populated;
you can pick `—` for unset.

**In the partner contacts table**: three new columns. The Sentiment
chip is colour-coded (Champion green / Blocker red / etc.).

**Filter row**: three new dropdowns (Any sentiment / Any tier /
Any seniority).

**Top of Partners view**: a new Settings button. Click → editable
textareas for every enum. Add a row to industries ("Esports"),
remove a tier, reorder seniorities, hit Save → next refresh, every
dropdown across the platform has your changes.

## [1.0.0ab] — 2026-05-23 — Design system: emojis out, monochrome SVG icons in

Ben asked: "Remove emojis. Come up with a better design than that.
Need to support mass changes."

Full sweep of `qualify.html` — every decorative emoji replaced with a
purpose-built design system. The UI now reads as a professional sales
tool, not a chat app.

### Design system foundation

- **`.icon` CSS class** — inline SVG icons inherit `currentColor` so
  they always match the surrounding text colour (works in both light
  and dark mode automatically). Default 14px with `.lg` (18px) and
  `.sm` (12px) modifiers. Stroke-width 1.75 for a refined feel.
- **`.rag-dot` CSS class** — red/amber/green status dots replace
  the coloured-circle emojis (🔴🟡🟢) in MEDDICC. Theme-aware.
- **`ICON_PATHS` JS dictionary** — 25 Lucide-style monochrome
  icons (Apache-licensed shapes): refresh, edit, trash, plus, x,
  check, copy, save, search, bell, eye, alert, info, note, link,
  folder, building, package, printer, chart-line, chart-bar,
  settings, sparkles, sun, moon, arrow-right.
- **`icon(name, opts)`** helper — returns inline SVG ready to drop
  into template literals: `${icon('edit', { size: 12 })}`.
- **`hydrateIcons(root)`** helper — replaces `<span data-icon="...">`
  placeholders with their SVG. Used for static HTML where template
  literals don't run.

### What was replaced

| Old | New | Sites |
|---|---|---|
| `📈` `📊` in nav | Inline SVG chart-line / chart-bar icons | 2 |
| `📈 Pipeline Forecast`, `📊 Team Activity Dashboard`, `🔍 Search contacts`, `🔔 Overdue contacts` page headers | Plain text (the section IS the chart/list) | 4 |
| `✎` edit buttons | `icon('edit')` | 10 |
| `✨` sparkle on AI buttons / indicators | `icon('sparkles')` (kept only where it earns its keep — buttons that trigger AI; stripped from toast strings + help text where redundant) | 21 |
| `📝` note buttons | `icon('note')` | 6 |
| `📋` copy buttons | `icon('copy')` | 3 |
| `🔍` search buttons + LinkedIn fallback link | `icon('search')` | 8 |
| `⚙` settings | `icon('settings')` | 2 |
| `⚠` warnings | `icon('alert')` where useful; stripped from red-banner headlines (background already signals) | 7 |
| `🔗` source chip | `icon('link')` | 1 |
| `🌙` `☀️` theme toggle | `icon('moon')` / `icon('sun')` swapped on theme change | 3 |
| `🔴` `🟡` `🟢` MEDDICC RAG | `<span class="rag-dot red/amber/green">` | 3 |
| `👁` preview | `icon('eye')` | 2 |
| `🖨` print | `icon('printer')` | 1 |
| `🗂` org chart | Plain text label | 1 |
| `📦` package | `icon('package')` | 1 |
| `✗` reject | `icon('x')` | 1 |
| `⌁` empty-state placeholder | `icon('info')` | 1 |
| `✦` decorative | `·` (typographic middle dot) | 1 |

### What was kept

Typographic glyphs that read as text in every font, not emojis:
- `⌘` — Mac command key (universal keyboard symbol)
- `×` — multiplication sign (for close buttons, not the emoji ✕)
- `→` `←` — navigation arrows
- `·` — middle-dot separator
- `▸` `▾` — disclosure carets
- `✓` `✕` — minimal Unicode check/cross (only where they're
  inside coloured buttons that already signal action)

### Toasts + help text

Stripped redundant emoji prefixes from toast strings (e.g.
`"✨ AI pre-filled N project criteria"` → `"AI pre-filled N project
criteria"`) — toasts have their own coloured borders for type, so
the icon was visual noise. Same for inline help text that
referenced button labels.

### Files touched
- `qualify.html` — ~80 surgical edits across CSS, HTML, and JS
  templates. Net: 0 decorative emojis remaining.

### Tests
- 550 passing — change is JS/CSS only, no Python contracts touched.

### What you'll see
Open the app. The nav reads "Forecast" + "Dashboard" with small
chart icons rendered in the same colour as the text. Hit any partner
contact's edit pencil — it's now an SVG pencil that scales cleanly
and adopts whatever colour the parent button uses. The dashboard's
"Cache wipe detected" banner no longer starts with `⚠` (the red
background already signals warning). MEDDICC's three RAG buttons are
now solid coloured dots, not emoji circles. The whole UI reads as
one coherent design language rather than a mix of fonts and emoji
sets that render differently on every OS.

## [1.0.0aa] — 2026-05-23 — Editable company name actually reflects after save

Ben reported the company name couldn't be edited. Investigation: the
input field exists (`data-ld="company"`), the change is collected by
`collectLeadEdits`, and the PATCH endpoint writes
`props["Company"] = {"title": ...}` to Notion correctly. End-to-end
the data DOES save.

### Real bug
`#ld-title` was set once on load and never refreshed after save.
Editing "Shell UK" → "Shell EMEA" → Save = silently succeeds; title
at the top of the drawer keeps showing "Shell UK", which reads as
"my edit was ignored." Same pattern as the status-chip bug from
v1.0.0h.

### Fix
Mirror the v1.0.0h status-chip refresh pattern. After every successful
PATCH, refresh:
- `#ld-title` from `data.lead.company` (or `(no name)` if cleared)
- `#ld-meta` from `data.lead.last_edited`

No data model changes — purely a UI sync. Subsequent pipeline refresh
already updates the row name in the table; that path was unchanged
and worked already.

### Verified safe
- The Notion page_id is immutable; renaming a lead doesn't break
  the cache files (they're keyed by Notion UUID, not company slug)
- `drawerState.original = data.lead` was already happening; downstream
  code reading `drawerState.original.company` (LinkedIn search helper,
  call POST `company_name` field) now sees the new value
- 550 tests still pass — JS-only change, no Python contract touched

### Files touched
- `qualify.html` — 8 lines in saveLead's success path

## [1.0.0z] — 2026-05-23 — Partner-sourced notes + initial qualification notes

Ben asked: "record notes from a partner (select which partner) — roll
them up under the account, and support adding notes during initial
qualification."

### Data model
`calls_store` records now carry an optional `partner_source`:
```json
{
  "partner_id": "braze",                  // required
  "contact_id": "braze-marina-klusas",    // optional — "Braze generic" without it
  "partner_name": "Braze",                // display, captured at save time
  "contact_name": "Marina Klusas"         // display
}
```
Stored on every new call. Editable post-hoc via `update_call`.
`_normalise_partner_source` handles None / empty / partial inputs
defensively.

### Lead drawer note composer
New **Source** dropdown above the content textarea:
- Default: `Internal — MR-side observation` (no attribution)
- Per partner: `Braze — generic` (no specific contact)
- Per partner-contact: optgroup of all active contacts under each
  partner (`Marina Klusas · Strategic Enterprise AE — CPG`)

The source is captured both on the "Save note now" path (immediate
save) and the "Save changes" combined-save path (buffered note flushed
on save). Resets to Internal after each successful save so the next
note doesn't accidentally inherit the previous attribution.

### Call card chip
Every saved note that has a partner_source renders a blue-tinted
`🔗 Marina Klusas · Braze` chip in the card header (CSS class
`.source-chip` — theme-aware, same blue palette as the country pill).
Internal notes have no chip.

### Initial qualification notes
New section in the Qualify form, below the sourced-for partners
field, above Save lead. AE buffers initial intel notes pre-save:
- Type (call / note / transcript / email)
- Content
- Source (Internal or any partner / partner contact)
- "+ Buffer note" stages it; "× remove" pulls it back

On Save lead success, every buffered note is posted to the new lead's
`calls_store` with its partner_source attached, then the buffer
clears. Toast surfaces the commit count
(`Committed 3/3 initial notes`).

### AI synthesis update
`_LEAD_SUMMARY_SYSTEM_PROMPT` extended with a CALL ATTRIBUTION
section:
- When a call has `partner_source.contact_name + partner_name`, the
  prompt is told to attribute inline: *"Marina (Braze) flagged
  Popeyes Q3 is moving"* instead of *"we heard…"*
- When only `partner_name` is set, attribute to the partner
  generically: *"Braze partnerships team confirmed…"*
- Partner-sourced facts are weighted as stronger signals than internal
  speculation
- `_gather_lead_context` passes `partner_source` on each call so the
  prompt has the data

### Rollup endpoint
`GET /api/partners/<pid>/contacts/<cid>/sourced-calls` returns every
lead-side call across the whole pipeline whose `partner_source`
matches that contact. Powers a future "everything Marina has
contributed" rollup view on her partner contact card (UI surface
deferred — endpoint ready when we build it).

### Tests
- 550 total (+16). `tests/test_calls_partner_source.py` covers:
  - `_normalise_partner_source`: None / empty / missing-key / whitespace
    / non-dict all → None or clean dict appropriately
  - `add_call` round-trips partner_source; defaults to None when omitted
  - `update_call` can set partner_source after-the-fact + can clear it
  - `list_calls_sourced_from`: by contact_id, by partner_id (catches
    partner-generic too), combined filter, no-match, empty filter

### Files touched
- `calls_store.py` — `partner_source` field + `_normalise` helper
  + `list_calls_sourced_from()`
- `server.py` — `_gather_lead_context` includes partner_source;
  new `GET /api/partners/<pid>/contacts/<cid>/sourced-calls` endpoint
- `ai_summary.py` — CALL ATTRIBUTION section in lead-summary prompt
- `qualify.html` — note-composer source dropdown, source chip on
  call cards, initial qualification notes section + buffer flow,
  `populatePartnerSourceSelect` + `_readPartnerSourceSelect` helpers
- `tests/test_calls_partner_source.py` (new, 16 tests)

### What you'll see
**Existing lead drawer**: open the Calls section. Above the content
textarea there's a new "Source" dropdown. Pick "Marina Klusas ·
Strategic Enterprise AE — CPG" before saving. The saved note shows
🔗 Marina Klusas · Braze in the card header. Next time you refresh
the AI summary, it'll attribute the intel to Marina by name.

**New qualification flow**: in the Qualify view, fill in the company,
score it, then before Save lead — type any initial notes (intro-call
recaps, partner-shared context) with the right source attribution,
hit + Buffer. As many as you need. Click Save lead → every buffered
note commits to the new lead as a call, with its attribution intact.

## [1.0.0y] — 2026-05-23 — LinkedIn cell — direct link, or pre-filled search

Apollo doesn't always return a `linkedin_url` for the people it finds.
Previously the LinkedIn column on every contact surface just showed
"—" when the URL was missing, leaving the AE to copy the name + go
to LinkedIn manually.

### Fix
New JS helper `linkedinCell(linkedinUrl, name, company, opts)`:
- **URL present** → renders the existing direct profile link
  ("view" in the Stakeholders table, "LinkedIn ↗" elsewhere)
- **URL missing** → renders a `🔍 LinkedIn search` link that opens
  `linkedin.com/search/results/people/?keywords=<name>+<company>` in
  a new tab. Pre-fills the name + company so the AE clicks once and
  lands on a sensible search page.
- **Name also missing** → fallback `—` (truly nothing to render).

The search-link variant is rendered in `class="muted"` with a
tooltip ("No profile URL on file — opens LinkedIn search pre-filled
with name + company") so it's visually distinct from a direct
profile link.

### Applied to all 5 LinkedIn render sites
1. Stakeholder Targets table (Qualify view)
2. Lead drawer — partner contacts assigned to this lead
3. Lead drawer — lead-side contacts list
4. Apollo contact-search results (in the lead drawer)
5. Partner contacts table (Partners view)

Each call site passes the relevant "company" string:
- Stakeholder + lead-side contacts → `result.company.name` /
  `drawerState.original.company`
- Partner contact lookup → `r.partner_name` (e.g. "Braze")
- Partner contacts table → `partner.name`

### Files touched
- `qualify.html` — `linkedinCell` helper + 5 render-site upgrades

### What you'll see
Open any lead with stakeholders — the "—" in the LinkedIn column
becomes "🔍 LinkedIn search". Click → LinkedIn opens with the name
+ company already in the search box. One click to a real profile
instead of three.

## [1.0.0x] — 2026-05-23 — Stakeholder names: first + last, not first only

Ben reported the Stakeholder Targets table showed only first names
("Chrissina", "Rodica", "Kate", "Kelsey") instead of full names.

### Root cause
`apollo._normalise_person` did `p.get("name") or "{first} {last}"`.
Apollo's `name` field is unreliable — for some records it contains
just the first name. The OR short-circuited at the truthy first
name, never reaching the full-name fallback.

### Fix
New `_resolve_person_name()` helper inverts the preference:
1. **first_name + last_name** when both are present → wins
2. Apollo's `name` field if it looks like a full name (has a space)
3. Whatever first / last we do have
4. Empty string as a last resort

`_normalise_person` also now surfaces `first_name` and `last_name`
separately on every stakeholder dict — useful if anything downstream
wants to render them differently later.

### What you need to do
- **Going forward**: every new lead you qualify will get full names
  in the stakeholder table.
- **For leads already qualified**: the saved stakeholder names are
  stuck with just the first name. To refresh them, re-qualify the
  lead (top of the Qualify view → enter the company name + URL →
  Save lead again). Or edit each contact's name in the lead drawer.

### Tests
- 534 total (+6). `tests/test_apollo_name_resolution.py` covers:
  - The exact failing case (Apollo `name="Chrissina"` +
    first/last set → resolves to "Chrissina Rocha")
  - `name` wins when first or last is missing AND `name` looks full
  - Falls back to first-only when nothing else
  - Empty input → empty string
  - Whitespace stripped from components
  - `_normalise_person` exposes first_name + last_name + name

### Files touched
- `apollo.py` — `_resolve_person_name` + updated `_normalise_person`
- `tests/test_apollo_name_resolution.py` (new, 6 tests)

## [1.0.0w] — 2026-05-23 — Light-mode contrast audit (7 more sites)

Systematic audit of every hardcoded colour in `qualify.html` that
could break in light mode. Fixed seven occurrences of "dark-mode
tint" patterns where `rgba(255,255,255,.06–.08)` was used as a subtle
recessed background or border — invisible in light mode.

### Status badges (4 sites)
"ALREADY ASSIGNED", "LEFT" (×2 different surfaces), "UNCLEAR",
"SAVED" pill badges were all using `rgba(255,255,255,.06–.08)` as
the background. Replaced with `var(--surface-2)` + `border:1px solid
var(--border)` so they render as a subtle recessed chip in both
modes (cream-on-cream in light, dark-on-dark in dark).

### Row tinting (2 sites)
- Apollo contact-search "already saved" row tint
  (`rgba(255,255,255,.04)`) → `var(--surface-2)`
- Apollo contact-search "saved" border ternary → unified to
  `var(--border)` for both branches (the visual "saved" state comes
  from the row opacity already)

### Country pill text colour
`.org-node .n-pill.country` had `color: #93c5fd` (pastel blue) which
read fine on dark surfaces but failed contrast on light. Now defaults
to `#1e40af` (darker blue, ~7:1 on the rgba(59,130,246,.10) light
tint) with a `:root:not([data-theme="light"])` override restoring
the pastel for dark mode.

### Gantt cell separator
The roadmap-gantt empty-cell separator was `1px solid
rgba(255,255,255,.02)` — invisible in light mode. Switched to
`var(--border)` with opacity .4 so the separator reads softly in
both modes.

### Audit notes
The remaining `rgba(255,255,255,...)` references are all intentional:
- CSS variable definitions in the `:root` block (theme-flipped)
- Drawer overlay backdrops (`rgba(0,0,0,.55-.7)` — always-dim by
  design)
- The chart-colour helper (already theme-aware)
- A red banner's white text (legible on red regardless of theme)

The remaining `color:#fff` references are all on accent-orange or
error-red surfaces where white-on-coloured is correct in both modes.

### Files touched
- `qualify.html` — 7 inline-style fixes + 1 CSS rule for the
  country pill

## [1.0.0v] — 2026-05-23 — ICP + pricing chart: light-mode contrast

Both Chart.js bar charts (ICP Score on Qualify view, pricing on
Project Build view) had hardcoded dark-mode colours for tick labels,
grid lines, and the "remaining" / "discount" bar fills. In light mode
the criterion labels and grid were near-invisible.

### Fix
New helper `_chartThemeColors()` reads `--text`, `--text-dim` from
the current theme's CSS variables and returns appropriate grid +
"remaining bar" tints (rgba black for light, rgba white for dark).
Both Chart.js call sites use it:
- ICP Score chart (`#score-chart`) — y-axis criterion labels were
  `#e8e8f0`; now `var(--text)` flips to readable dark in light mode
- Pricing chart (`#pb-pricing-chart`) — same x/y tick colours +
  legend label colour

### Caveat
Charts don't auto-redraw when the theme toggle flips mid-session.
Next data refresh (or page reload) picks up the new colours.
Acceptable for v1 — adding a redraw-on-theme-change listener is
deferred until anyone hits it in practice.

### Files touched
- `qualify.html` — added `_chartThemeColors()` helper + applied to
  both chart sites; ~20 lines

## [1.0.0u] — 2026-05-23 — Search modal: light-mode contrast fix

Ben reported the global search modal (⌘K) had near-invisible header
text in light mode. Root cause: `.doc-preview-header` had a hardcoded
`background: rgba(19,19,26,.95)` (dark) while the title text used
`var(--text)` which flips to dark in light mode → dark text on dark
band, unreadable.

### Fix
- `.doc-preview-header` background → `var(--surface-2)` (theme-aware:
  cream in light mode, dark in dark mode; subtly recessed against the
  modal surface in both)
- `.doc-preview-body` background → `var(--surface)` instead of
  hardcoded `#fff` (also fixed a parallel dark-mode bug where doc
  iframes were forced white inside an otherwise-dark modal — the
  iframe itself still renders the document on white via its own
  inline background, so doc rendering is unchanged)

### Audit
Other hardcoded color values verified intentional:
- `--bg-drawer-glass: rgba(19,19,26,.85)` — translucent backdrop only
- `color: #fff` on accent (orange) buttons — brand-on-accent always
- `#dc2626 / #fff` on error banners — universally legible
- `background: #fff` on doc iframes — keeps doc rendering consistent

### Files touched
- `qualify.html` — 2 CSS rules + comments documenting the why

## [1.0.0t] — 2026-05-21 — 📊 Team Activity Dashboard

Ben asked for a manager surface — "looking over the team, see number
of touches/calls etc from a partnership perspective." New Dashboard
nav tab aggregating activity by MR owner + by partner over a sliding
window.

### What it shows

A new **📊 Dashboard** tab between Forecast and Project Build:

**KPI row** (5 cards):
- Total touches in window (partner notes + lead calls combined)
- Partner notes (touches logged on partner contacts)
- Lead calls (touches logged on prospect leads)
- New leads (proxy: last_edited inside the window)
- Cadence compliance % (active contacts within cadence ÷ total)

**Touch-type breakdown**: chip row showing how many call / email /
intro / touch / other entries hit each owner this window.

**By MR Owner table** (the manager view):
| Owner | Touches | Partner contacts | Overdue | Leads owned | Active leads |
- Sorted by touches descending; goose-eggs included so you can see
  who's NOT active
- Role + region in the subtitle ("Daniel Ergueta · Account Manager · AMER")
- Overdue column red-highlighted when > 0

**By Partner table**:
| Partner | Touches | Contacts | Overdue | Never touched | Leads sourced |
- Same shape; pivots the activity to the partner side
- Never-touched column yellow-highlighted

**Coverage health card** at the bottom — single big % with breakdown
(active / within cadence / overdue / never touched).

### Window + filter
- Top toggle: **7 days** / **30 days** (default) / **90 days**
- Owner dropdown: filter to a single MR owner (uses the v1.0.0o
  central roster); empty = "All owners"

### Attribution model
We attribute activity by the **current `mr_owner` on each contact**
(or `owner` on each lead), not by who actually typed the note. This
is the right semantic for a manager: "how much work has Daniel done"
means "touches on Daniel's book". If you reassign a contact to a new
owner, the activity follows. Note `author` field is unreliable today
because the UI doesn't set `X-Actor` (defaults to "anon"); fixing
that is a future iteration if needed.

### Endpoint
- `GET /api/dashboard?window=<int>&owner=<name>` — returns the full
  payload. Pipeline rows fetched best-effort; if Notion is down the
  dashboard still loads with partner-side stats.

### Tests
- 528 total (+13). `tests/test_dashboard.py` covers:
  - Window filtering (in vs out)
  - Per-owner attribution via mr_owner
  - Per-owner table includes inactive owners (zero rows for managers
    looking for gaps)
  - Owner-filter param scopes both totals + the per-owner list
  - Per-partner rollup
  - Coverage compliance math (3/4 = 75%)
  - Never-touched flag for old contacts that have never been logged
  - Inactive (status=left/dormant) contacts excluded from coverage
  - Empty roster: 0 KPIs + 12 zero owner rows (no crash)
  - Endpoint: shape, window clamping (1..365), graceful degradation
    when Notion is unavailable

### Files touched
- `dashboard.py` (new) — pure-logic aggregator
- `server.py` — `/api/dashboard` endpoint
- `qualify.html` — new view markup, KPI cards, two tables, coverage
  health card, window + owner filter wiring
- `tests/test_dashboard.py` (new, 13 tests)

### What's next (if useful)
- Trends — weekly touches as a line chart (requires a tiny SVG
  renderer; not in MVP)
- Pipeline value per owner — already in the Forecast view's "By
  Owner" slice, surface a link
- Manager comments / kudos — surface a "🎉 most touches this week"
  card automatically
- "Stale leads" surface — leads with no calls in 14+ days (the
  inverse of the new-leads metric)
- Activity heatmap (day-of-week × hour) — power-user visualisation

## [1.0.0s] — 2026-05-21 — Code review fixes (H1, H3, M1, M3, M4)

Five issues from the code-review pass on v1.0.0h..r. Each one is small
on its own; together they tighten the platform meaningfully before
more features land.

### H1 · Drop dead code in agency PATCH merge + lock the semantic
**File**: `server.py:455` (`api_lead_agencies_update`)

The line was:
```python
merged.update({k: v for k, v in body.items() if v is not None or k in body})
```
`k in body` is always True when iterating `body.items()`, so the filter
was a no-op. Replaced with plain `merged.update(body)` and documented
the real PATCH semantic in the docstring: omitted keys preserve, present
keys (including `null` / `""`) overwrite.

Two new tests in `tests/test_lead_agencies.py`:
- `test_patch_explicit_null_clears_optional_field` — locks the contract
  that `PATCH {"notes": null}` and `PATCH {"notes": ""}` both clear the
  field.
- `test_patch_omitted_keys_preserved` — locks that omitting `name`
  doesn't accidentally wipe it.

### H3 · Lazy retry on `ensure_properties` + banner condition
**Files**: `server.py:2475+` (lazy retry), `qualify.html:6191+` (banner)

If Notion was unreachable at app import time, `_BACKUP_PROPERTY_READY`
errored and every subsequent state-backup mirror silently failed. Two
changes:

1. **`_maybe_lazy_retry_ensure_properties()`** — called at the top of
   `_mirror_state_to_notion`. If the boot self-heal errored, retries
   the schema check exactly once (gated by `_BACKUP_LAZY_RETRY_DONE`).
   If Notion is back up by the time of the first real save, the
   property gets created and mirrors succeed from then on.
2. **Cache-wipe banner** now also fires on `notion_backup_property.error`
   — separate red banner that reads "Notion backup is offline — schema
   check failed", with the actual error string so Ben can fix it
   without having to remember the diagnostics URL.

### M1 · Harden the deal-value parser against hostile input
**File**: `forecast.py:43+`

Three new guards on `parse_deal_value_from_text`:
- **Doubt markers** — bail out when text contains "no idea", "not sure",
  "maybe", "perhaps", "guess", "tbh", "could be", "no clue", "wild
  guess". Better to land in the missing-value bucket than silently
  inflate the forecast with a guessed number.
- **Negative numbers** — reject any number preceded by `-` or `−`. The
  regex didn't consume the minus, so `-40k` used to parse as `40000`.
- **Upper cap** — `_MAX_MONTHLY_GBP = 10_000_000`. Anything above is
  almost certainly a typo and would skew the forecast badly. MR's
  largest realistic deal is ~£200k/month; £10M is generous headroom.

Four new tests in `tests/test_forecast.py`:
- `test_rejects_doubt_markers`
- `test_rejects_negative_numbers`
- `test_caps_unrealistic_values`
- `test_ignores_embedded_script_garbage` — soft test (either None or
  £1 acceptable; the cap protects us either way).

### M3 · "Intro Call" stage probability was dead config
**Files**: `forecast_config_store.py:32+`, `qualify.html:6843+`

`DEFAULT_STAGE_PROBABILITIES` had `"Intro Call": 0.05` but
`PIPELINE_STAGES` excluded it — so the 5% knob did nothing. An AE
who tweaked it would think the system was broken.

Removed Intro Call from the defaults map AND from the settings panel's
stage list. Added a one-line note in the settings panel's help text:
*"Intro Call is excluded by design — leads only enter the forecast at
Discovery."* The forecast view itself was already correct; only the
config + UI changed.

### M4 · Ring buffer cap test
**File**: `tests/test_state_backup.py`

Three new tests verifying `_BACKUP_HEALTH` actually evicts at 20:
- `test_ring_buffer_caps_at_20` — append 25, assert deque holds only
  the latest 20 (leads 0..4 evicted)
- `test_diagnostics_surfaces_latest_attempts` — endpoint returns the
  5 most-recent attempts, not the 5 oldest
- `test_failure_count_accurate_under_cap` — tally reflects only
  in-buffer state, not historical total

### Deferred from the review (low-cost, low-urgency)
- **H2** (multi-store write race) — only matters under concurrent
  writes. Single-user MR usage today; deferred until team usage lands.
- **M2** (boot side-effects on every gunicorn worker) — Notion's
  PATCH is idempotent so it's wasteful not destructive; not worth
  the worker-zero gating complexity yet.
- **M5** (JS test coverage gaps) — would need a Selenium / Playwright
  setup we don't have.
- **L1..L7** — style / cosmetic / nits.

### Tests
- 515 total (+9). All passing.

### Files touched
- `server.py` — H1 merge simplification, H3 lazy retry
- `qualify.html` — H3 banner condition, M3 settings panel
- `forecast.py` — M1 parser guards
- `forecast_config_store.py` — M3 default map
- `tests/test_lead_agencies.py` — 2 new tests for H1
- `tests/test_forecast.py` — 4 new tests for M1
- `tests/test_state_backup.py` — 3 new tests for M4

## [1.0.0r] — 2026-05-21 — Inline-editable MR owner dropdowns in list tables

Ben asked: "need to be able to use dropdowns for MR owner even in the
lists." Previously the dropdowns lived only in modal forms — re-assigning
an owner in any list view meant opening the drawer/edit modal, picking
the new owner, saving. This collapses that into a one-click change in
the row.

### Three list surfaces now have inline dropdowns
- **Pipeline table** — Owner column on every lead row (both grouped
  parent rows + flat rows)
- **Partners table** — MR owner column on every partner row
- **Partner contacts table** — MR owner column on every contact row
  (under any partner's drilldown)

### How it looks
The cell reads as plain text by default (no chrome). Hover → background
tint + border outline appear, signalling it's clickable. Click → native
`<select>` opens with all 12 MR owners. Change → instant PATCH +
success toast ("Owner updated → Daniel Ergueta"); failure reverts the
selection + surfaces the error.

### Plumbing
- **`renderInlineOwnerCell(currentValue, entityType, ids, field)`** —
  helper that returns a `<select class="inline-owner-cell">` with
  `data-mr-owner-select` (so `hydrateOwnerSelects` populates it from
  `/api/owners`) plus `data-inline-endpoint` + `data-inline-field`
  encoding the PATCH target.
  - Entity types: `lead` → `/api/lead/<id>` field=`owner`;
    `partner` → `/api/partners/<id>` field=`owner`;
    `partner_contact` → `/api/partners/<pid>/contacts/<cid>`
    field=`mr_owner`.
- **`wireInlineOwnerCells(root)`** — binds change handlers. Stops
  event propagation so a pipeline-row click doesn't open the drawer
  when the user is interacting with the select.
- **CSS** `select.inline-owner-cell` — transparent until hover/focus,
  appearance reset, disabled state during the PATCH round-trip.

Every table render call site now does:
```js
tbody.innerHTML = rowsHtml;
// ... wire other handlers ...
hydrateOwnerSelects(tbody);
wireInlineOwnerCells(tbody);
```

### Optimistic UX
- On change, the select disables for the duration of the PATCH (subtle
  opacity dim — no spinner needed; round-trip is <200ms).
- Success → toast + the `data-original` value updates so a second
  change is detected correctly.
- Failure → select reverts to the previous owner; toast surfaces the
  server error.

### Skipped on purpose
- **Overdue contacts card** — the mr_owner is shown inline in a
  cramped meta line (last touched · Xd overdue · cadence · owner).
  Adding a dropdown there would feel claustrophobic. The card is a
  transient touch-or-dismiss surface, not a roster.
- **Org chart node text** — same reason: it's a card meta line, not
  a table.

### Files touched
- `qualify.html` — helpers (`renderInlineOwnerCell` + `wireInlineOwnerCells`),
  CSS for `.inline-owner-cell`, 3 cell replacements, 3 wiring hooks.

### What you'll see
Open the Pipeline view, hover any row's Owner cell — it lights up.
Click → pick a new owner from the dropdown → done. Same in the
Partners table, same in any partner's contacts table.

## [1.0.0q] — 2026-05-21 — "Last call · <date>" on synthesised summaries

Ben pointed out: the AI synthesis panels describe "the most recent
conversation" but the footer only said when Claude was run, not when
the conversation actually happened. Easy to lose track of freshness.

### Fix

When the server saves a synthesis, it now attaches metadata about
the most-recent input note/call:
- `most_recent_note_at` / `most_recent_call_at` — ISO timestamp
- `most_recent_note_type` / `most_recent_call_type` — e.g. "call",
  "email", "intro"
- `notes_count` / `calls_count`

Both surfaces now render a prominent line at the top of the summary
panel:

```
Last call · 21 May 2026
```

Date format is locale-aware ("21 May 2026" / "May 21, 2026" depending
on the user's browser). Type is whatever the AE picked when saving
the note ("call" / "email" / "intro" / "touch" / "other").

### Where it applies
- **Partner contact summary** (the panel inside the 📝 notes modal —
  the one Ben flagged)
- **Lead-side AI lead summary** (same gap; same fix)

### Backward compat
- Cached summaries without the new metadata still render fine —
  the "Last call" line just doesn't appear until the next refresh.
- Lead-side summary also falls back to the most-recent `calls[0]`
  in the JS render if the server hasn't attached the metadata yet.

### Tests
- 506 total (+1). Extended `test_partner_contact_summary.py` with
  `test_summary_attaches_most_recent_note_metadata` — verifies the
  server attaches the right fields with the right values when
  multiple notes exist.

### Files touched
- `server.py` — `_refresh_partner_contact_summary` + the two lead
  synthesis call sites (manual refresh + auto-after-call-add) all
  attach the metadata before saving
- `qualify.html` — `renderPartnerContactSummary` + `renderAiLeadSummary`
  both render the "Last call · <date>" line at the top
- `tests/test_partner_contact_summary.py` — new test

## [1.0.0p] — 2026-05-21 — Incumbent + previous agencies per lead

Ben asked for the ability to track competitive context: who's running
their Braze/CDP/data work TODAY (incumbent) and who they've used in
the PAST (previous). Two entry points: at qualification time (capture
the incumbent up-front so the AI summary frames the displacement
angle from call 1), and after the fact in the lead drawer (add
previous agencies as they surface in calls).

### Data model

Per-lead JSON file at `cache/lead_agencies/<lead_id>.json` —
same pattern as `contacts_store` / `lead_contact_notes_store`. Each
entry:
```json
{
  "id": "12char-uuid",
  "lead_id": "lead-slug",
  "name": "VML",
  "type": "incumbent" | "previous",
  "scope": "Braze ops",
  "since": "2023-04-01",
  "until": null,
  "notes": "Mediocre execution — replace narrative needs migration story",
  "added_at": "2026-05-21T22:30:00Z",
  "updated_at": "..."
}
```

### Endpoints
- `GET    /api/leads/<lead_id>/agencies`
- `POST   /api/leads/<lead_id>/agencies` — create or upsert by id
- `PATCH  /api/leads/<lead_id>/agencies/<agency_id>` — partial update
  (only sends fields you want to change; name + type preserved)
- `DELETE /api/leads/<lead_id>/agencies/<agency_id>`

Every write mirrors to the Notion State Backup so agencies survive
Railway cache wipes alongside calls + contacts + project.

### AI synthesis updates
- `_gather_lead_context` now includes `agencies` in the Claude
  payload
- `_LEAD_SUMMARY_SYSTEM_PROMPT` extended with an **AGENCY CONTEXT**
  section that tells Claude how to use it:
  - Incumbent → surface displacement angle in state_of_play or risks
  - "in-house" incumbent → flag the build-vs-buy lens
  - Previous churn → pattern-match retention risk ("they fire
    agencies every 18mo")
  - Specific predecessor MR has a case study against → lead with it

### UI

**Qualify form** — two new fields below sourced-for:
- **Incumbent agency** text input ("VML / Razorfish / in-house")
- **Incumbent scope** text input ("Braze ops / loyalty / campaign exec")

When the AE clicks Save lead, the standard Notion upsert runs first;
if either field has content, a POST follows to
`/api/leads/<page_id>/agencies` to record the incumbent. The capture
fields clear on success.

**Lead drawer** — new collapsible "Agencies" section between
Qualification and Contacts. Shows:
- Inline add/edit form: name + type dropdown + scope + since/until
  dates + notes textarea
- List below, **incumbents-first** then alpha. Each row:
  - Coloured panel (orange-tinted for incumbents, neutral for
    previous)
  - INCUMBENT / PREVIOUS badge
  - Scope · since→until window
  - Notes block
  - ✎ Edit (loads back into the form) / × Delete buttons
- Section count chip shows e.g. "(1 incumbent, 2 previous)"

### state_backup integration
- `gather()` includes `agencies` field
- `apply_backup()` restores agencies via the store's `_write_raw`
- Auto-mirrored after every agency create/update/delete (same path
  call-saves already use)

### Tests
- 505 total (+15). `tests/test_lead_agencies.py` covers:
  - Store: requires name, rejects unknown type, upsert by id,
    incumbents-first sort, delete idempotency
  - `summarise_for_ai()` includes type + scope + window
  - All 4 endpoints (GET / POST / PATCH partial / DELETE)
  - 400 on missing name, 404 on unknown id
  - state_backup gather + restore round-trip preserves agencies

### Files touched
- `lead_agencies_store.py` (new)
- `server.py` — 4 endpoints + import + context-gather extension
- `state_backup.py` — gather + apply integration
- `ai_summary.py` — prompt extended with AGENCY CONTEXT section
- `qualify.html` — qualify form fields, drawer section, JS handlers
- `tests/test_lead_agencies.py` (new, 15 tests)

### What you'll see
- **New lead from Qualify form**: optional Incumbent agency + scope
  fields. Filled in → recorded automatically as `type: incumbent`.
- **Existing lead drawer**: scroll past Qualification, the
  **Agencies** section is right there. Add incumbents + previous,
  edit/delete via the row buttons.
- **AI lead summary** (when you refresh it): displacement-angle
  framing automatically — e.g. "VML runs their Braze today, mediocre
  exec — lead with the migration playbook MR ran for [similar
  account]" instead of the generic "engage stakeholders" line.

## [1.0.0o] — 2026-05-21 — MR owners roster (single source of truth)

Ben supplied the full Massive Rocket team — 12 people across CEO,
Growth, Account Management (current + AE-transition), Marketing, and
Partner Management. Previously the lead drawer + qualify form
hardcoded "Ben Ojuolape" + "Unassigned"; partner contact forms had
free-text mr_owner inputs. This release centralises that into one
data module + one endpoint.

### The roster
| Name | Role | Region |
|---|---|---|
| Thierry Sequeira | CEO UK | Global |
| Daniel Craig | Director of Growth | Global |
| Ben Ojuolape | Growth Lead (Partnerships + GTM) | UK → US |
| Daniel Ergueta | Account Manager | AMER |
| Tsveti Grncarova | Account Manager | EMEA |
| Jorge Arrechea | AMER AM, transitioning to AE | AMER |
| Marija Veljanova | AMER AM, transitioning to AE | EMEA |
| Darren Addy | EMEA AM, transitioning to AE | EMEA |
| Claudia Lima | Partner Manager, AMER | AMER |
| Sonal Dalia | Partner Manager | EMEA |
| Jamie MacDow | Marketing — co-owns New Accounts OKR | Global |
| Lea | Marketing | Global |

Notes:
- Sonal Dalia's email is intentionally blank (not supplied) — placeholder
  in the module, fill in when confirmed.
- Lea is single-name pending surname confirmation; email assumed
  `lea@massiverocket.com`.

### Plumbing

- **`mr_owners.py`** (new) — module-level `OWNERS` list of dicts with
  `{name, role, region, email, active}`. Helpers: `list_owners()`,
  `names()`, `get_owner(name)`. To add/remove: append/edit in code,
  one place.
- **`GET /api/owners`** — returns `{owners: [...]}` for the UI.
- **`hydrateOwnerSelects(root=document)`** — JS helper that finds
  every `[data-mr-owner-select]` element and populates its options
  from the cached endpoint response. Preserves the current/existing
  value via `data-preserve-value` (so editing a contact whose owner
  is set keeps that selection after re-render).

### Surfaces updated
- **Qualify form** owner dropdown (`#sel-owner`)
- **Lead drawer** owner dropdown (`data-ld="owner"`)
- **Partners view** new-partner form mr_owner — converted from free-text
  input to dropdown
- **Partner contact form** mr_owner — converted from free-text input
  to dropdown (preserves the current value on edit)

### Tests
- 490 total (+10). New `tests/test_mr_owners.py` covers:
  - Module shape (required fields, unique names, email format)
  - Every name Ben supplied is present
  - Active/inactive filtering
  - Case-insensitive `get_owner()` lookup
  - Endpoint returns the full roster

### Files touched
- `mr_owners.py` (new)
- `server.py` — `GET /api/owners` endpoint
- `qualify.html` — 4 owner-surface conversions + `hydrateOwnerSelects` helper
- `tests/test_mr_owners.py` (new)

### What you'll see
Open any lead drawer or the Qualify form — the Owner dropdown now
lists all 12 MR team members. Hover any option to see role + region
in the tooltip. Add a new partner → same dropdown. Edit any partner
contact → MR owner becomes a dropdown instead of free-text.

To add someone (e.g. a new AE): one-line edit in `mr_owners.py`.
Every dropdown picks it up on next page load.

## [1.0.0n] — 2026-05-21 — Pipeline forecast (quarterly bookings + slices)

Ben asked for forecasting. Scoped to weighted quarterly pipeline as
the primary view, with editable stage probabilities + slices across
Quarter / Owner / Partner / Vertical / Region.

### What it shows

A new **📈 Forecast** nav surface with:
- **4 KPI cards** at the top: Commit / Best case / Pipeline (all
  annualised £) + Coverage ratio vs the quarterly target
- **Slice breakdown table**: click chips to switch between Quarter
  (the default — uses the 4-quarter horizon), Owner, Partner source,
  Vertical, Region. Each row shows commit/best/pipeline + a stacked
  distribution bar (green=commit, yellow=best, orange=pipeline).
- **"Needs close date" list**: leads excluded because deal value
  isn't parseable — click each to open its drawer and fix it.
- **⚙ Settings panel**: inline editor for the 8 stage probabilities
  + quarterly target. Saved to `cache/forecast_config.json`, applies
  immediately on save.

### Definitions
- **Commit** = stages ≥ Verbal Commit (95%+ default probability) —
  the deals you'd actually bet on
- **Best case** = stages ≥ Negotiation (70%+) — what could close
  this quarter if things go well
- **Pipeline** = stages ≥ Discovery (20%+) — total weighted
  opportunity in flight
- **Coverage** = (3-month pipeline) / quarterly target. 3x is the
  SaaS rule-of-thumb for healthy coverage; UI colour-codes green ≥3x,
  yellow ≥2x, red below 2x.
- **Disqualified / On Hold / Closed Lost / Intro Call** excluded
  from all aggregations.

### Deal value resolution (the right answer, not the only one)
1. **Explicit `deal_value_monthly_gbp`** — new structured numeric
   field. Always wins.
2. **Parsed `deal_size`** — extracts numbers + units from the
   existing free-text field. Handles `£40k/month`, `£500k ARR`,
   `$2m ARR`, commas, k/M/B units. Annual → monthly conversion
   automatic when the text says ARR/annual/year/TCV.
3. **`pricing_store` total** — falls back to the per-lead pricing
   config when set.
4. **"Missing value" bucket** — surfaces in the UI so Ben can clean
   them up rather than silently dropping them.

### Stage probabilities (sensible defaults)
| Stage | Default |
|---|---|
| Intro Call | 5% (excluded from pipeline sum — too early) |
| Discovery | 20% |
| Technical Fit | 35% |
| Proposal | 50% |
| Negotiation | 70% |
| Legal/Procurement | 85% |
| Verbal Commit | 95% |
| Signature | 100% |

All user-editable via the ⚙ Settings panel.

### Close date bucketing
- Reads new `expected_close_date` field. Buckets into year-quarter
  (`2026-Q3`).
- Missing date → bucketed into the current quarter so the deal still
  shows up. UI flags the "needs close date" follow-ups separately.
- Outside the 4-quarter horizon → lumps into the last horizon
  bucket (Q+3 currently).

### Plumbing
- **`forecast.py`** — pure logic module. `parse_deal_value_from_text`,
  `resolve_deal_value`, `parse_close_date`, `resolve_close_quarter`,
  `build_forecast`. No Flask, no Notion — easy to test.
- **`forecast_config_store.py`** — JSON-on-disk store mirroring
  `lead_summary_store`. Defaults applied on load; user overrides
  clamped to [0, 1] for probabilities, ≥0 for the target.
- **Notion property auto-create** — `ensure_state_backup_property`
  generalised into `ensure_properties(spec)`, batched. Boot self-heal
  now ensures `State Backup` + `Expected Close Date` + `Deal Value
  (Monthly GBP)` all in one PATCH.
- **`_page_to_detail` + `_row_from_page`** extended to surface the
  two new fields (plus `region` on rows so the slice has data).
- **`update_page`** wired to write both fields back to Notion.

### Endpoints
- `GET  /api/forecast?horizon=4` — full payload with all slices,
  totals, missing-value list, coverage ratio. Pulls 500 pipeline
  rows from Notion + aggregates in pure Python (cheap).
- `GET  /api/forecast/config` — stage probabilities + target.
- `PATCH /api/forecast/config` — save overrides. Clamps invalid
  values; ignores unrecognised keys.

### Lead drawer
Two new fields in the Qualification → Quant section:
- **Deal value (monthly GBP)** — numeric input (£), explicit override
  for the forecast
- **Expected close date** — `<input type="date">`; buckets the deal

### Tests
- 480 total (+32). `tests/test_forecast.py` covers:
  - Deal value parsing: £/$/€ symbols, k/M units, commas, annual→monthly
    conversion, unparseable input (TBD/n/a/empty) → None
  - Resolve order: explicit > parsed > pricing_store > unknown
  - Eligibility: disqualified/on-hold/closed-lost/intro-call excluded
  - Weighted pipeline math + commit/best/pipeline bucketing
  - Close date bucketing (explicit ISO + inferred fallback to current Q)
  - All 4 slices (owner / partner / vertical / region) with the
    partner slice correctly handling multi-tag sourced_for_partners
  - Coverage ratio math
  - Config store: defaults, overrides, invalid values clamped, target update
  - Endpoint integration: 200 with mocked pipeline, 502 on Notion error

### Files touched
- `forecast.py` (new) · `forecast_config_store.py` (new)
- `notion_sync.py` — new property surface, ensure_properties helper,
  write paths for the two new fields
- `server.py` — 3 new endpoints + boot self-heal extended
- `qualify.html` — Forecast view + JS + lead drawer fields + nav item
- `tests/test_forecast.py` (new, 32 tests)

### What you do
1. Once the redeploy lands, open the **📈 Forecast** tab.
2. The "needs close date" list shows every lead missing the new
   fields — click through and fill in the structured Deal Value +
   Expected Close Date for each.
3. Hit ⚙ Settings to tune stage probabilities against MR's actual
   conversion history if the defaults don't match.

## [1.0.0m] — 2026-05-21 — AI synthesis for partner-contact notes

Ben asked for partner-contact notes to have the same kind of AI
synthesis that lead-side calls already have, but with a contact-centric
schema. The synthesis answers "what do I need to remember before my
next call with this person."

### Synthesis schema (7 fields)

```json
{
  "summary":                    "2-3 sentences on the most recent conversation",
  "accounts_discussed":         ["account + 1-line context they mentioned"],
  "updates_on_prior_accounts":  ["account + what's changed since"],
  "territory_info":             ["geography / segment / book / managers"],
  "challenges":                 ["frictions they surfaced"],
  "opportunities":              ["openings they see"],
  "additional_info":            "free text — comp, manager prefs, siblings"
}
```

Arrays cap at 6 entries each. None values are dropped (we don't let
the literal string "None" leak through). Plain English; no marketing
tone — same writing rules as lead-side synthesis.

### Plumbing

- **`ai_summary.synthesise_partner_contact_conversation(payload)`** —
  new function paralleling `synthesise_lead`. Same model, same
  best-effort failure behaviour (returns None on missing API key or
  errors; never raises).
- **`partner_contact_summary_store`** — new tiny store mirroring
  `lead_summary_store`. JSON file per contact at
  `cache/partner_contact_summaries/<partner_slug>/<contact_id>.json`.
- **`_refresh_partner_contact_summary(partner_id, contact_id)`** —
  server-side helper that gathers (contact + partner + full note
  history with the most-recent flagged), calls the AI, caches the
  result. Shared by the add-note path + the explicit refresh endpoint.

### Endpoints

- `POST /api/partners/<pid>/contacts/<cid>/notes` — now returns
  `{ note, notes, contact, summary }`. The summary key is the freshly
  re-synthesised payload (or null if AI is off).
- `GET  /api/partners/<pid>/contacts/<cid>/summary` — returns the
  cached payload without re-running Claude. Used to populate the
  modal on open.
- `POST /api/partners/<pid>/contacts/<cid>/summary` — forces a refresh
  (the ✨ Refresh summary button in the modal).

### UI

`openContactNotes` modal grew a synthesis panel at the top:
- Orange-tinted card matching the lead drawer's summary style
- Each of the 7 fields rendered with its own colour-coded section
  header (green for accounts_discussed, yellow for updates_on_prior,
  blue for territory, red for challenges, orange for opportunities)
- ✨ Refresh button in the modal header to re-synthesise on demand
- Auto-loads cached summary on modal open
- Auto-refreshes after every Add-note save (server returns the new
  summary in the same response, no extra round-trip)
- When AI is off, surfaces a friendly hint to set
  `ANTHROPIC_API_KEY` rather than silently skipping

### Tests
- 448 total (+9). New `tests/test_partner_contact_summary.py` covers:
  - Store round-trips (save/load/delete)
  - Synthesis normalisation (arrays cap at 6, None entries dropped,
    missing fields defaulted)
  - Endpoint integration: add-note returns summary key, GET returns
    cached payload, POST refreshes, friendly message when AI is off
  - Caching: mocked synthesis persists across GET

### Test isolation regression caught + fixed
While adding the new test class, found that the existing
`test_partner_touch_cadence` started failing when run after the new
file. Root cause: my test's tearDown was unconditionally popping
`SKIP_COMMAND_CENTRE_SEED` from os.environ, which unset a flag set
by the test runner on the command line. The next test class's
`importlib.import_module("server")` then triggered the auto-seed,
polluting its temp dir with 137 contacts. Fix: snapshot the original
env value in setUp and restore it in tearDown.

### Files touched
- `ai_summary.py` — new prompt + `synthesise_partner_contact_conversation`
- `partner_contact_summary_store.py` — new module
- `server.py` — import + helper + 2 new endpoints + updated notes-add
- `qualify.html` — `openContactNotes` modal grew the summary panel
- `tests/test_partner_contact_summary.py` — new file (9 tests)

## [1.0.0l] — 2026-05-21 — Country + Region as separate columns

Ben pointed out the partner contacts table jammed "Region · Country"
into one column, even though they're separate fields in the data model
(`regions: list[str]` multi-tag vs `country: str | None` free text).

### Fixes
- **Table view**: split "Region · Country" into two columns — "Region"
  (multi-tag chips) and "Country" (single value).
- **Org chart**: country was previously invisible on the node; now
  rendered as its own blue-tinted pill alongside the region pills, so
  the distinction is visually obvious.

### Routing audit (all already correct, just verified)
- `partner_contacts_store._normalise` stores `regions` (list) and
  `country` (string) as independent fields
- Form save handler collects them via independent inputs (`#ptn-c-regions`
  chip group vs `#ptn-c-country` text input) and PATCHes them as
  separate keys
- Filters (`partnersState.filter.region` vs `.country`) match them
  independently — region by exact-list-inclusion, country by
  case-insensitive contains
- CSV export already had separate columns
- The only places they were combined were two read-only display
  surfaces (the table column header and the org-chart node), both
  fixed in this release

### Files touched
- `qualify.html` — table column split + country pill in org chart +
  `.n-pill.country` CSS variant.

## [1.0.0k] — 2026-05-21 — Partner contact edit "broken" — actually invisible

Ben reported "edit button isn't working" in the Partners view. It WAS
working — but with 137 Braze contacts in the table, the edit form
rendered hundreds of pixels below the fold and looked like nothing
happened. Compounding it: the click handler silently no-op'd if the
contact lookup ever failed, so any real failure was indistinguishable
from "the form is off-screen".

### Fixes
- **Scroll-into-view + flash highlight** in `openContactForm` and
  `openContactNotes`. The form pulses an accent border and scrolls
  itself into view smoothly when it opens, so it's obvious the click
  registered.
- **Stop swallowing failures** in the click handlers for `[data-contact-edit]`,
  `[data-org-contact]` (org chart click), and `openContactNotes`.
  When the contact lookup misses, log to console + toast to the user
  with the offending id, instead of silently doing nothing.

### Files touched
- `qualify.html` — three click handlers + `openContactForm` + `openContactNotes`.

## [1.0.0j] — 2026-05-21 — Auto-seed Command Centre on boot

Ben reported Braze + Hightouch weren't visible on the deployed app
after v1.0.0h shipped. Root cause: the seed file *exists* in the
codebase and the tests run it against temp dirs, but it had never
been executed against the production instance's `cache/` directory.

### Boot-time auto-seed (idempotent)

`_boot_auto_seed_command_centre` runs at app startup:
- Checks if the Braze partner record exists in `partners_store`
- If absent → runs `seed_command_centre_partners.seed()` (181 contacts
  across Braze + Hightouch)
- If present → skips, on the assumption the seed has already run AND
  any user-deletions since should stay deleted (we don't want
  re-deploys magically recreating contacts the user has removed)

Captured into `_COMMAND_CENTRE_SEED_STATUS` so `/api/diagnostics/health`
shows exactly what happened on the most recent boot.

### Manual re-seed endpoint

`POST /api/admin/seed/command-centre` — for the rare case where the
user wants to force a re-seed (e.g. after a recovery scenario, or to
add new contacts that were appended to the seed file). Idempotent via
stable IDs so it never duplicates.

Returns:
```json
{
  "ok": true,
  "partners": ["Braze", "Hightouch"],
  "contacts_created": 181,
  "contacts_skipped": []
}
```

### Test environment

Tests opt out of the auto-seed via the new `SKIP_COMMAND_CENTRE_SEED`
env var (set in the test runner) so they don't accidentally hit the
real `cache/` directory.

### What Ben sees on next deploy

Once Railway redeploys with v1.0.0j:
1. Boot self-heal ensures the Notion "State Backup" property exists
2. Boot auto-seed creates Braze + Hightouch + 181 contacts in the now-persistent cache
3. `/api/diagnostics/health` reports `command_centre_seed.ran: true`
4. Open the **Partners** view in the app — Braze + Hightouch are there
   with the full hierarchy + cadence + email-inferred tags

If the boot seed somehow doesn't run (env var, edge case), Ben can
trigger it manually:
```bash
curl -X POST -H "Authorization: Bearer $APP_AUTH_TOKEN" \
  https://web-production-b7cb5.up.railway.app/api/admin/seed/command-centre
```

## [1.0.0i] — 2026-05-21 — Bulletproof the backup mirror + cache-wipe banner

Ben reported notes are still missing after v1.0.0g. Triage showed:
- The Railway persistent volume isn't mounted yet (the permanent fix).
- The missing notes were added BEFORE v1.0.0g shipped — no Notion
  backup ever existed for them.

So this release does two things: (1) make sure post-v1.0.0g writes
CAN'T silently fail to mirror, and (2) surface the situation loudly so
we don't end up in this position again.

### Backup mirror — zero silent failures

The v1.0.0g mirror depends on a "State Backup" rich-text property
existing on the Notion database. If it doesn't (e.g. database swap,
fresh workspace), every mirror call 400s and we just log a warning.

- **`notion_sync.ensure_state_backup_property()`** — idempotent
  self-heal. GETs the data source / database schema; if "State Backup"
  isn't present, PATCHes it in as a rich_text property.
- **Boot hook in `server.py`** — calls the ensure on app import (gated
  on `NOTION_API_KEY` being set + a `SKIP_NOTION_BOOT` escape hatch
  for tests). Status of the check (existed / created / error) is
  captured into `_BACKUP_PROPERTY_READY` so diagnostics can read it.
- **`_BACKUP_HEALTH` ring buffer** — last 20 mirror attempts tracked
  in-memory with success/failure + error string + byte count. Surfaced
  via the new diagnostics endpoint.

### `/api/diagnostics/health` — see what's actually happening

New read-only endpoint. Returns:
- Cache directory existence, file count, lead-with-calls count
- Whether a cache wipe is suspected (heuristic: empty cache + no
  successful mirrors yet)
- Whether the Railway volume is mounted on /app/cache (via `st_dev`
  comparison vs the container root)
- Whether the "State Backup" Notion property exists / was just created
  / errored on boot
- Last 5 mirror attempts with full detail, plus success/failure tally

This is the single source of truth when "did my backups actually
work?" comes up.

### UI — cache-wipe banner

Init-time fetch of `/api/diagnostics/health` from `qualify.html`.
- If cache wipe suspected + volume not mounted → loud red persistent
  banner across the top of the app driving Ben to mount the volume,
  with a direct link to `RAILWAY_VOLUME_MOUNT.md`.
- If a recent mirror attempt failed → softer warning with the actual
  error string + link to the diagnostics endpoint.
- Banner is dismissible per session (sessionStorage flag).

No more "everything looks fine, then on next deploy data is gone".

### `/api/lead/<id>/notion-history` — last-ditch recovery surface

For pre-v1.0.0g data loss where no backup exists, the only remaining
trace is whatever the AI synthesised into Notion-side fields (Fit
Summary, Next Steps, Positive Signals, Lead Summary, MEDDICC Notes).
Those properties live in Notion and survive cache wipes.

New endpoint pulls the lead's current Notion property text + points
the AE at Notion's built-in **Page history** (⋯ → Page history in the
Notion UI) where prior revisions are visible on Plus+ plans. Won't
bring back the original call note text, but may recover important
AI-distilled context.

### Tests
- 439 still passing. New endpoints exercised via the test client:
  `/api/diagnostics/health` returns the expected schema even with no
  Notion creds (boot self-heal gated behind `NOTION_API_KEY`).

### Files touched
- `notion_sync.py` — `ensure_state_backup_property` + `get_page_history`.
- `server.py` — boot self-heal, `_BACKUP_HEALTH` ring buffer, two new
  diagnostic endpoints, `_is_path_on_volume` helper, mirror call now
  tracks attempts.
- `qualify.html` — `_checkCacheHealth` + `_showCacheWipeBanner` wired
  into init.

### What Ben needs to do (5 minutes)
1. Open Railway → web-production-b7cb5 service → Volumes / Storage tab.
2. Click + New Volume. Mount path: `/app/cache`. Size: 1 GB.
3. Save. Railway restarts the service. Done — no more cache wipes.

After the volume is mounted, the diagnostics banner stops appearing
and the auto-mirror becomes a belt-and-braces safety net rather than
a sole line of defence.

## [1.0.0h] — 2026-05-21 — Status-chip live refresh + full Braze/Hightouch roster

Two threads in this release: a small but high-friction UI bug fix Ben
hit on Shell UK, plus the comprehensive Command Centre partner seed.

### Bug fix: Shell UK status chip stuck on "DISQUALIFIED" after save

Ben flipped Shell UK's Status dropdown to "Qualified", clicked Save, but
the header chip kept showing "DISQUALIFIED" (rendered uppercase via CSS).
Root cause: `#ld-status-chip` was set once from the load-time
`lead.status` value and never refreshed — neither when the user changed
the dropdown nor when the PATCH came back with the new server-confirmed
value.

Fix:
- New `refreshHeaderStatusChip(status)` helper in qualify.html — single
  source of truth for the chip text.
- `loadLead` calls it with the server value.
- `saveLead` calls it with `data.lead.status` from the PATCH response
  after every successful save.
- The `change` listener on `[data-ld="status"]` calls it live as the
  user picks a new status — chip flips before save, so the AE gets
  immediate visual confirmation that their pick registered.

### Comprehensive Braze + Hightouch seed (Command Centre roster)

Expanded `seed_command_centre_partners.py` from the 2-contact priority
stub (Glenn Bonforte + Marina Klusas only) to the full 181-contact
Command Centre roster Ben provided:

- **Braze AMER** — Eric Sanders' tree (Jason Swetnam, Scott Gibson,
  Stephanie Chang Retail, Emmanouela Androulaki GenBiz, Tim Taggart
  Commercial, all their SDs + AEs), FINS pod (Josh Marder, Nader
  Taghavi, etc.), Lindsey Swanson / Ava Lillian Strategic team.
- **Braze EMEA** — Marc Suchland → Marlon Hills → Zarpana Kabir +
  George Goodger, all London-based scale + enterprise AEs, plus Katie
  Cornwell (Shell EMEA contact) and the legacy "confirm against new
  org" folks (Imi de Daranyi, Rod Aimes, Abigail Tucker, Jase Buckley)
  tagged `confirm_org`.
- **Braze Partner org** — Glenn Bonforte + James Dobson, Sam Oresanya,
  Haatim Ahmed, Renata Minami, Harry Fellows, Wenzel Hilpert.
- **Braze GSA / CSM bench** — Nish Patel, Heather (TBD), Georgia
  Harrison, Ashley Wilkinson, Orlando Beakbane.
- **Hightouch NA Sales** — Vinod Venkatasubramaniam (Enterprise West),
  John Knudsen (Mid-Market North), Joseph Spath / Jessica Doyle /
  Trevor Sutley / Alex Matthews / Kyla Gundersen / Blake Ballardo /
  Aidan Lynch managers + all their AEs.

Engineering choices:
- **Stable contact IDs** (`braze-eric-sanders`, `ht-joseph-spath`) so
  re-runs upsert by id, never duplicate.
- **`reports_to_id`** preserved for every line the source material made
  explicit. 11 root contacts (Eric Sanders at the top of AMER, Glenn
  for partner-org, the 5 confirm-org legacy folks, the 3-person CSM
  bench, the 2-person GSA bench); zero dangling references.
- **Email handling**: every Braze contact gets `firstname.lastname@
  braze.com` by default, with verbatim overrides for the 9 exceptions
  Ben flagged (`e.androulaki@braze.com`, `nader@braze.com`,
  `kiley@braze.com`, `eleanor.carman@braze.com`, `aileen.cole@braze.com`,
  `julia.shaffer@braze.com`, `hannah.slowey@braze.com`,
  `elizabeth.dicarlo@braze.com`, `Marina.Klusas@braze.com`). All
  Hightouch contacts get inferred Hightouch emails (no overrides
  supplied). **Inferred emails are tagged `email_inferred`** so they're
  auditable later — 67 of 181 contacts are flagged this way.
- **MR-priority cadence**: 8 contacts on Ben's top-of-mind list (Marina,
  Bill Thomas, Eric Sanders, Stephanie Chang, Eleanor Wolf, Marlon
  Hills, Katie Cornwell, Glenn Bonforte) get `mr_priority` tag +
  `cadence_days=14` so they surface first in the overdue queue.
  SVPs/VPs/AVPs get 21d; everyone else 30d.
- **Industry tagging** propagates down org branches (Retail under
  Stephanie Chang, FINS under Scott Gibson direct, QSR under William
  Thomas, etc.) so the UI's industry filter actually scopes correctly.

### `partner_contacts_store.py` — territory enum

`TERRITORIES` extended with **"Emerging Enterprise"** and **"Scale"** —
distinct segments in Braze's hierarchy that don't squeeze into
Strategic/Enterprise/Mid-Market/SMB. The seed lands without distortion.

### Tests
- 439 total (+1). `tests/test_contact_extraction.py::SeedScriptTests`
  rewrites to match the comprehensive seed:
  - Spot-checks the original 2 priority contacts still present + a
    sampling of the newly-added leadership.
  - Asserts every contact carries `command_centre_seed`.
  - Asserts MR-priority contacts have `mr_priority` + cadence=14.
  - Asserts email overrides are applied verbatim (Emmanouela, Marina).
  - Asserts the full Hightouch roster lands + every Hightouch email
    is flagged `email_inferred`.
  - **New**: `test_seed_hierarchy_intact` — every `reports_to_id`
    resolves to a real contact in the same partner. Catches typos
    before they ship.

### Files touched
- `qualify.html` — `refreshHeaderStatusChip` helper + 3 call sites.
- `seed_command_centre_partners.py` — comprehensive rewrite (~500 lines).
- `partner_contacts_store.py` — `TERRITORIES` enum extension.
- `tests/test_contact_extraction.py` — seed assertions rewritten + 1 new test.

## [1.0.0g] — 2026-05-21 — Durable state backup + ⟲ Restore (cache-loss defence)

Critical fix for Ben's report that notes + project builds disappeared.
Root cause: Railway's filesystem is ephemeral — every redeploy wipes
`cache/`. We'd been warning about this; this release ships the defence.

### What you do (once)
Mount a 1 GB Railway volume on `/app/cache` — instructions in the new
`RAILWAY_VOLUME_MOUNT.md`. 5 minutes via the Railway dashboard. After
this, nothing wipes ever again.

### What the platform does (every save, automatically)
- Every call save, project save → server compresses the lead's full
  local state (calls + contacts + contact-notes + project + pricing +
  roadmap + AI summary) into gzip+base64 JSON, chunks it into
  ~1900-char rich-text entries, writes them to a new **"State Backup"**
  property on the lead's Notion page.
- Best-effort: if Notion is down, the user-visible save still succeeds;
  the mirror just logs a warning.

### What you do (after a wipe)
- Open any lead drawer. If the local cache is empty AND Notion has a
  backup for this lead, a red **⟲ Restore** button appears in the
  drawer header next to ↻ Rescore.
- Click → confirms with the AE → server pulls the chunked blob from
  Notion → decodes → writes back to every store (calls, contacts,
  contact-notes, project, pricing, roadmap, summary).
- Toast: *"Restored 7 calls + 3 contacts + project (backup from
  21 May 22:30)"*.

### New backend
- **`state_backup.py`** module:
  - `gather(lead_id)` → full state dict
  - `encode(payload)` → JSON → gzip → base64 string
  - `decode(blob)` → reverse, raises ValueError on malformed input
  - `chunk_for_notion(blob, chunk_size=1900)` → list of safe rich-text
    chunks (Notion's per-entry cap is 2000 chars)
  - `apply_backup(lead_id, payload)` → idempotent restore
  - `is_empty_cache_for(lead_id)` → True when calls + contacts +
    project are all absent
- **New writable Notion property**: `"State Backup"` (chunked
  rich-text). `notion_sync.update_page` accepts
  `{"state_backup_chunks": [...]}` and writes each chunk as a separate
  rich_text entry under a single property.
- **`_extract_text`** already concatenates all rich_text entries in
  read order — no extra work to join chunks on the read side.
- **`_page_to_detail`** now includes `state_backup` (the joined
  chunks) so `GET /api/lead/<id>` exposes it.

### New endpoints
- `GET  /api/lead/<id>/backup` — full state as a JSON download
  (payload + encoded blob). Use as a pre-deploy safety net.
- `POST /api/lead/<id>/backup/mirror` — explicit "save backup to
  Notion now". Same logic as the auto-mirror; useful for paranoia.
- `POST /api/lead/<id>/restore` — pull from Notion and re-hydrate
  the local cache. 404 with a hint if no backup exists.

### UI
- **⟲ Restore button** in the drawer header (between ↻ Rescore and
  Save). Red tinted to signal recovery action. Only visible when
  local cache for this lead is empty AND a Notion backup exists.
- **Confirm dialog** before restoring (any local data gets
  overwritten).
- **Detailed success toast** lists what was restored + the
  backup's capture timestamp.

### Auto-mirror integrations
- `POST /api/calls/<id>` — mirrors after every call save (most painful
  loss case).
- `POST /api/scope/<id>` — mirrors after every project save.
- Other writes (contacts, pricing, roadmap) get mirrored via the next
  call or project save; or via manual `POST /backup/mirror`.

### Tests
- 438 total (+13). New `test_state_backup.py`:
  - Encode/chunk/decode round-trips (small + large payloads)
  - Decode rejects malformed / empty input
  - Gather assembles every store's slice correctly
  - Restore re-hydrates from a backup after a simulated cache wipe
  - Restore is idempotent (twice = same end state)
  - `is_empty_cache_for` returns True iff calls + contacts + project
    are all absent
  - Endpoint: backup returns payload + encoded blob
  - Endpoint: restore returns 404 + hint when no Notion backup
  - Endpoint: restore from a mocked Notion State Backup property
    actually re-hydrates the local stores

### Docs
- **`RAILWAY_VOLUME_MOUNT.md`** — step-by-step Railway dashboard
  instructions + verification path. Mount the volume, redeploy,
  verify with a test note. Also clarifies what's recoverable
  (post-v1.0.0g) vs gone (pre-feature data).

## [1.0.0f] — 2026-05-21 — Tier 3c + Command Centre seed (Braze + Hightouch)

Closes Tier 3 of the contact-management plan + seeds the Partners CRM
with the Braze + Hightouch records referenced in Ben's Command Centre
working memory.

### Added — Tier 3c: AI contact extraction from notes
- **`contacts_mentioned`** field added to the `extract_from_notes`
  Claude prompt schema. Each entry: `{name, title?, email?, role}`
  where role ∈ `prospect-side` / `mr-side` / `partner-side` / `unknown`.
- Normaliser filters entries down to ones with a real name + clamps
  role to the valid enum + drops fabricated emails/titles.
- **`/api/calls/<id>` POST returns `contact_suggestions`** —
  AI-extracted prospect-side names that aren't already in the lead's
  contacts. Case-insensitive dedupe on name OR email. MR-side and
  partner-side roles are stripped (they belong elsewhere).
- **"✨ AI spotted N new contacts" panel** in the lead drawer's
  Calls & Notes section after a save. Checkboxes pre-checked, role
  badges (PROSPECT / UNCLEAR), one-click bulk-add to lead contacts
  via the existing array-shape POST. Dismiss to hide.

### Added — Command Centre seed script
- **`seed_command_centre_partners.py`** — idempotent seed for the
  Partners CRM. Adds:
  - **Braze** partner record + 2 contacts:
    - **Glenn Bonforte** — Partner Success, US, multi-region (East
      Coast + West Coast + Central), multi-territory (Strategic +
      Enterprise), QSR + Retail + Travel & Hospitality, 30-day cadence
    - **Marina Klusas** — Strategic Enterprise AE on Popeyes US, East
      Coast, Strategic Enterprise, QSR, 21-day cadence
  - **Hightouch** partner record (no contacts seeded — the AE
    populates via UI when known; we don't fabricate names)
- Run with: `python3 seed_command_centre_partners.py` (Apollo
  fixtures recommended for safety: `APOLLO_USE_FIXTURES=1 python3 ...`).
- Hierarchy: Glenn (Partner Success) and Marina (Sales) are
  intentionally not linked via `reports_to_id` — they're in different
  functions. AE adjusts the org chart in the UI as needed.
- `tags: ["command_centre_seed"]` on every seeded contact so they're
  filterable later (e.g. for cleanup or re-seeds).

### Tests
- 425 total (+11). New `test_contact_extraction.py`:
  - Prompt schema documents contacts_mentioned + the role enum
  - Server returns suggestions for new prospect contacts
  - MR-side names filtered out
  - Partner-side names filtered out
  - Existing contacts deduped by name (case-insensitive)
  - Seed creates both partners + Braze contacts with the right
    multi-tag metadata
  - Seed is idempotent (re-run doesn't duplicate)
  - Hightouch partner created without fabricated contacts

### Contact-management plan — DONE
- ✅ Tier 1a · Partner cadence + overdue (v0.10.0z)
- ✅ Tier 1b · Partner ↔ lead assignments (v0.11.0)
- ✅ Tier 1c · Lead-side cadence + status parity (v1.0.0a)
- ✅ Tier 1d · Engagement timeline per contact (v1.0.0b)
- ✅ Tier 2a · Cross-surface search (v1.0.0c)
- ✅ Tier 2b · "My contacts" view (v1.0.0c)
- ✅ Tier 3a · Partner org chart (v1.0.0d)
- ✅ Tier 3b · Multi-tag territory + region (v1.0.0e)
- ✅ **Tier 3c · AI contact extraction from notes (this release)**

All 9 tiers shipped. The contact-management surface is feature-complete
against the plan agreed in v0.10.0z.

## [1.0.0e] — 2026-05-21 — Tier 3b: multi-tag territory + region

A partner contact can now own multiple territories AND multiple regions
simultaneously — same pattern as industries already had. Marina at
Braze can cover Strategic Enterprise + Enterprise, East Coast +
Central, and QSR + Retail all on one record.

### Schema (`partner_contacts_store`)
- **`territories: list[str]`** — primary tag list.
- **`regions: list[str]`** — primary tag list.
- **`territory: str | None`** — backward-compat shim, exposed as the
  first item in `territories`. Same for `region` ↔ `regions`. Any
  reader that hasn't moved to the plural still works.
- New `_coerce_tag_list()` helper handles all input shapes uniformly:
  - List → kept as-is (deduped, trimmed)
  - Comma-separated string ("A, B, C") → split on commas
  - Single string ("A") → single-item list
  - None / empty → empty list
- **Plural wins when both shapes are in the payload** — the new UI
  always sends the plural; the singular is only consulted for legacy /
  CSV / API consumers.

### Server (`/api/contacts/search`)
- Territory / region filters now match the new tag list OR fall back
  to the legacy singular field. A search for `territory=Enterprise`
  surfaces contacts tagged Strategic Enterprise + Enterprise + anyone
  with the legacy single value.

### UI (contact form + everywhere it's displayed)
- **Contact form**: territory and region dropdowns replaced with chip
  multi-select (same pattern as industries) — *"Territories
  (multi-select) — a contact can own multiple, e.g. Strategic
  Enterprise + Enterprise"*. Chips toggle active on click; payload
  sends `territories: [...]` + `regions: [...]`.
- **Contacts table** in partner detail: territory + region now render
  as chip stacks rather than single cells.
- **Org chart node cards**: every territory + region tag becomes its
  own pill (territory pills accent-coloured for hierarchy).
- **Lead drawer "Partner contacts on this account"** + **global
  search modal**: tag lists joined with `", "` in the metadata row.
- **Assignment picker** in the lead drawer: same — tag lists join
  cleanly in the candidate row metadata.
- **All filter logic** (partner detail panel + lead-side picker)
  routed through a new `_tagListIncludes(c, plural, singular, value)`
  helper so the back-compat path is uniform.

### Helpers (qualify.html)
- `_tagList(c, plural, singular)` → list (always)
- `_tagText(c, plural, singular, sep=', ')` → joined string
- `_tagListIncludes(c, plural, singular, value)` → bool

### Tests
- 414 total (+9). New `test_partner_contact_multitag.py`:
  - List input kept as list + dedupe
  - Legacy singular input lifted to single-item list
  - Comma-separated string parsed correctly
  - Empty input → empty list + None singular
  - Plural shape wins when both keys present
  - Round-trip (load → save) doesn't drift
  - Search matches secondary territory (not just primary)
  - Search matches secondary region
  - Legacy-singular contacts still surface in search

### Contact-management plan — progress
- ✅ Tier 1 (a-d): cadence + assignments + timeline
- ✅ Tier 2 (a-b): search + my contacts
- ✅ Tier 3a · Partner org chart (v1.0.0d)
- ✅ **Tier 3b · Multi-tag territory + region (this release)**
- Next: Tier 3c · AI-extract contacts from call transcripts.

## [1.0.0d] — 2026-05-21 — Tier 3a: partner org chart visualisation

The `reports_to_id` field has been quietly collecting data on partner
contacts since v0.10.0y (the contact form has the "Reports to" picker
populated from sibling contacts). This release adds the visualisation.

### Added — UI
- **📋 Table / 🗂 Org chart view toggle** on the partner detail header
  (next to ✕ Close). Persists in `partnersState.viewMode` for the
  current session.
- **Org chart renderer** (`renderPartnerOrgChart`) builds a vertical
  tree from the contacts' `reports_to_id` chain:
  - Each node is a card with name + title + last-touched + cadence +
    MR owner
  - Coloured pills below: **territory** (accent), region, industries
    (max 2), **overdue** (red) when past cadence
  - Click any card → opens the existing edit form (same UX as table)
- **Pure-CSS connecting lines** — vertical guide on the left of each
  sibling group + horizontal connector from the guide to each node
  card. No SVG, no library. Scales to any depth.
- **Roots-first sort** — managers (with reports) appear before
  individual contributors inside any sibling group; then alpha.
- **Orphan recovery** — a contact whose `reports_to_id` points to a
  deleted contact is rendered as a root (rather than disappearing).
- **Cycle guard** — recursion bounded to 12 levels in case a corrupt
  `reports_to_id` chain forms a loop.
- **Filter integration** — the partner detail's Territory / Region /
  Country / Industry / Status filters apply to the chart by
  **highlighting matched nodes** while dimming the rest. Managers
  always stay visible so the tree stays anchored (otherwise filtering
  to e.g. "Strategic Enterprise" would hide their reports' bosses).
- **Status badges in-line** — `(left)` / `(dormant)` appended to the
  name; non-active nodes get reduced opacity on the whole card.

### CSS additions
- `.org-tree`, `.org-tree ul`, `.org-tree li` — recursive list
  structure with `::before` pseudo-elements drawing the connectors
- `.org-node` — card style with hover transform + overdue / left /
  dormant variants
- `.org-node .n-pill` — base pill style for territory / region /
  industry / overdue tags

### Tests
- 405 total (no new tests). The data model (`reports_to_id` field,
  sibling picker validation, etc.) is already covered by the
  `test_partners.py` suite. The renderer is pure UI / JS — sanity
  verified via the inline parse check.

### Contact-management plan — progress
- ✅ Tier 1a · Partner cadence + overdue (v0.10.0z)
- ✅ Tier 1b · Partner ↔ lead assignments (v0.11.0)
- ✅ Tier 1c · Lead-side cadence + status parity (v1.0.0a)
- ✅ Tier 1d · Engagement timeline per contact (v1.0.0b)
- ✅ Tier 2a · Cross-surface search (v1.0.0c)
- ✅ Tier 2b · "My contacts" view (v1.0.0c)
- ✅ **Tier 3a · Partner org chart (this release)**
- Next: Tier 3b (multi-tag — multiple territories/regions per contact),
  Tier 3c (AI-extract contacts from call transcripts).

## [1.0.0c] — 2026-05-21 — Tier 2a + 2b: cross-surface contact search + "My contacts"

Single global search that finds any contact across both surfaces
(leads + partners) with the same filter vocabulary you'd use inside
either tab. Opens via 🔍 button or ⌘K from any view.

### Added — backend
- **`GET /api/contacts/search`** unifies both contact stores. Query
  params (all optional):
  - `q` — free-text matched against name + email + title + country,
    case-insensitive
  - `surface` — `lead` / `partner` / omit for both
  - `status` — active / dormant / left
  - `territory`, `region`, `industry` — partner-only fields; when
    set, lead-side scan is skipped (lead contacts don't have these
    fields, so they'd all fail the filter)
  - `owner` — case-insensitive `contains` match on `mr_owner`. Powers
    the "My contacts" workflow.
  - `limit` — int, default 50, clamped 1–200 per surface
- Returns `{lead: [...], partner: [...], total: int}` with each
  result tagged with `surface` + `parent_id` + `parent_name`
  (display name resolved from Notion pipeline for leads, partner
  registry for partners).
- Touch state annotated on lead-side results so overdue chips
  surface in the picker.
- Sort: overdue-first within each surface, then alpha by name.

### Added — UI
- **🔍 Global search button** in the top nav header (between
  Partners and the theme toggle). Shows ⌘K hint.
- **⌘K / Ctrl+K** shortcut from anywhere — opens the search modal,
  or closes it if already open. Esc to close. Priority: search →
  doc preview → drawer (most recently opened wins).
- **Search modal** (same overlay CSS as doc preview, 720px tall):
  - Large search input at top
  - Filter row: Surface · Status · Territory · Region · Industry ·
    Owner text · **My contacts** quick-button · Clear filters
  - **My contacts** button drops the AE's name into the Owner filter
    in one click (currently hard-coded to "Ben" — easy to make
    configurable)
  - Debounced search (180ms) — types feel instant, no API thrash
  - Results in two sections (Lead contacts · Partner contacts) with
    coloured count badges
  - Each row is a clickable card showing name + surface tag + parent
    + title/territory/region/country + industries + email + overdue/
    status badges
  - Click a row → closes search and opens the right drawer (lead
    drawer for lead contacts, partner detail for partner contacts)

### Tests
- 405 total (+12). New `test_contacts_search.py`:
  - Empty query returns both surfaces with surface-tag enrichment
  - Free-text matching on name / email / country
  - Surface filter scopes results correctly
  - Territory / region / industry filters skip lead-side as designed
  - Owner filter ("My contacts") matches mr_owner contains
  - Combined filters compose correctly
  - No matches returns empty lists with total=0

### Contact-management plan — progress
- ✅ Tier 1a · Partner cadence + overdue (v0.10.0z)
- ✅ Tier 1b · Partner ↔ lead assignments (v0.11.0)
- ✅ Tier 1c · Lead-side cadence + status parity (v1.0.0a)
- ✅ Tier 1d · Engagement timeline per contact (v1.0.0b)
- ✅ **Tier 2a · Cross-surface search (this release)**
- ✅ **Tier 2b · "My contacts" view via owner filter (this release)**
- Next: Tier 3 — org chart visualisation, multi-tag, AI-extract
  contacts from transcripts.

## [1.0.0b] — 2026-05-21 — Tier 1d: engagement timeline per lead contact

Per-contact notes finally land for the lead side, mirroring the
partner-side notes shape. Every lead contact now has a chronological
engagement timeline — calls, intros, emails, follow-ups, generic
touches — all dated, all attributable, all queried in one place.

### Added — backend
- **`lead_contact_notes_store.py`** — per-(lead, contact) notes at
  `cache/lead_contact_notes/<lead_slug>__<contact_id>.json`.
  - Types: `call` / `email` / `intro` / `touch` / `follow_up` / `other`.
    Unknown types fall back to `other`.
  - Newest-first ordering with microsecond precision (multiple-per-
    second adds don't collide).
  - `delete_all_for_contact()` for cascade cleanup.
- **`POST /api/contacts/<lead_id>/<contact_id>/notes`** auto-bumps
  the contact's `last_touched_at` — a note IS a touch, no separate
  ✓ click needed. Returns the new note + fresh notes list + the
  bumped contact with annotated touch state.
- **`GET /api/contacts/<lead_id>/<contact_id>/notes`** — list.
- **`DELETE /api/contacts/<lead_id>/<contact_id>/notes/<note_id>`** —
  single-note delete.
- **Contact delete now cascades notes** so removing a contact never
  leaks orphan notes.

### Added — UI
- **📝 button per lead contact row** (next to ✓ touch, ✎ edit, ★ key,
  × delete). Opens an inline engagement-timeline panel ABOVE the
  contact list.
- **Timeline panel** mirrors the partner-side design:
  - Type dropdown + textarea for adding a new entry
  - **"Add note · log touch"** primary button (makes the implicit
    touch-on-note behaviour explicit)
  - Newest-first list below with type pill (accent-coloured) +
    timestamp + author + × delete per entry
- **Toast on add**: *"Note added · touch logged"*
- **Auto-refresh**: contact list reloads after a note add so the
  last-touch column updates inline (overdue chip disappears, cadence
  clock resets).

### Tests
- 393 total (+11). New `test_lead_contact_notes.py`:
  - Store: content required, newest-first listing, type fallback,
    scoping per (lead, contact), cascade delete, single-note delete
  - Endpoints: list empty, add-bumps-touch, delete, cascade on
    contact delete, 400 on missing content

### Contact-management plan — progress
- ✅ Tier 1a · Partner cadence + overdue (v0.10.0z)
- ✅ Tier 1b · Partner ↔ lead assignments (v0.11.0)
- ✅ Tier 1c · Lead-side cadence + status parity (v1.0.0a)
- ✅ **Tier 1d · Per-lead-contact engagement timeline (this release)**
- Next: Tier 2 — cross-surface contact search + "My contacts" view.

### Symmetry achieved
Lead contacts and partner contacts now share:
- `name / title / email / linkedin_url / phone`
- `cadence_days / last_touched_at / status` (lifecycle)
- Per-contact notes (engagement timeline)
- Auto-touch on note add
- Explicit ✓ touch endpoint
- Cross-surface overdue roster endpoint

The data models stay distinct (per the design decision) but the
behaviour is now uniform — AE muscle memory carries across both.

## [1.0.0a] — 2026-05-21 — Tier 1c: touch cadence + status lifecycle on lead contacts

Parity with partner contacts. Every lead-side contact now carries the
same touch-cadence + status fields, the same overdue surfacing, and
the same ✓ touch button — so the AE manages "who at the prospect have
I gone cold on?" with the same muscle memory as the partner side.

### Schema additions (`contacts_store`)
- **`cadence_days`** — default 30, clamped 1–365.
- **`last_touched_at`** — ISO timestamp, set by the touch endpoint.
- **`status`** — `active` / `dormant` / `left` (default active;
  unknown values fall back to active).
- **`updated_at`** — bumped on every save.

### New helpers
- **`annotate_touch_state(contact)`** — same derived fields as the
  partner side (`overdue`, `days_since_touch`, `days_until_due`,
  `is_due_soon`, `next_touch_due`). Called inline by `list_contacts`.
- **`touch_contact(lead_id, contact_id)`** — explicit "I just talked
  to them" bump.
- **`overdue_contacts(lead_id=None)`** — scoped or cross-lead roster.
  Cross-lead variant annotates each row with `lead_id` for routing.

### New endpoints
- `POST /api/contacts/<lead_id>/<contact_id>/touch` — log an explicit
  touch. Mirror of the partner-side equivalent.
- `GET  /api/contacts/overdue` — cross-lead overdue roster, sorted
  most-overdue first.

### UI changes (lead drawer Contacts section)
- **Last-touch line** under every contact row:
  *"Touched 12d ago · cadence 30d"* / *"Touched 45d ago · 15d overdue"*
  in red / *"Never touched · cadence 30d"* on never-touched.
- **Overdue tint** on contact card backgrounds (red gradient).
- **STATUS badge** (`DORMANT` / `LEFT`) next to the name when not
  active. Dimmed rows for non-active.
- **✓ Touch button** per row, paired with the existing ✎ edit, ★ key,
  × delete actions.
- **✎ Edit form** (new) — inline editable panel that opens above the
  contact list, pre-populated with name / title / email / LinkedIn /
  status / cadence. Save round-trips through the existing
  `POST /api/contacts/<lead_id>` upsert.
- **Manual-add form** extended with cadence + status pickers
  (sensible defaults — 30 days / active).

### Tests
- 382 total (+11). New `test_lead_contact_cadence.py`:
  - Default 30-day cadence + active status on save
  - Cadence clamping to 1–365
  - Unknown status falls back to active
  - Annotate / overdue / touch behaviour
  - Cross-lead overdue scan annotates `lead_id`
  - Endpoints: 404 on missing, touch bumps, overdue cross-lead
    surfacing

### Contact-management plan — progress
- ✅ Tier 1a · Partner touch cadence + overdue (v0.10.0z)
- ✅ Tier 1b · Lead ↔ partner-contact assignments (v0.11.0)
- ✅ **Tier 1c · Lead-side cadence + status parity (this release)**
- Next: Tier 1d (engagement timeline per contact), then Tier 2
  (cross-surface search + "My contacts" view).

## [0.11.0] — 2026-05-21 — Partner contacts ↔ leads (assignment + bidirectional view)

When an AE opens a lead, they need to know *"who's the right Braze
person for this deal?"*. Now you can assign one or many partner
contacts to a lead, and the assignment is visible from both
directions.

### Added — backend
- **`lead_partner_assignments.py`** — many-to-many store at
  `cache/lead_partner_assignments/<lead_slug>.json`. Rows:
  `{partner_id, contact_id, assigned_at, assigned_by, note}`.
  - `assign(lead, partner, contact)` — idempotent; re-assigning
    updates `note` + `assigned_by`, preserves `assigned_at`
  - `unassign(...)` — removes the link
  - `list_for_lead(lead_id)` — all partner contacts on this lead
  - `list_for_contact(partner_id, contact_id)` — reverse lookup:
    every lead this partner contact is assigned to (across-lead scan)
  - Validates raw inputs before slugify so empty strings can't
    silently corrupt the store with the "unknown" fallback

### Added — server endpoints
- `GET  /api/lead/<id>/partner-contacts` — enriched assignments
  (partner name + full contact record + touch state inlined)
- `POST /api/lead/<id>/partner-contacts` — assign single
  (`{partner_id, contact_id, note?}`) OR bulk
  (`{assignments: [...]}`)
- `DELETE /api/lead/<id>/partner-contacts/<partner_id>/<contact_id>`
- `GET  /api/partners/<id>/contacts/<cid>/assigned-leads` — reverse
  lookup with `lead_name` enrichment from the pipeline

### Added — UI
**Lead drawer → Contacts section** now has a **"Partner contacts on
this account"** subsection ABOVE the lead-side contacts (which is
the natural order: AE wants to know "who's the partner side rep
here" first):
- Compact cards showing partner name (accent-coloured) + contact
  name + title + territory + region + email + LinkedIn + industry
  chips + optional note
- Overdue pill propagates from the partner contact's touch state
- **× Remove** per card
- **+ Assign partner contact** button opens an inline picker:
  1. Pick partner from dropdown
  2. Multi-select contacts under that partner (already-assigned
     contacts greyed out with `ALREADY ASSIGNED` badge)
  3. Save → bulk POST

### Why this design
- **Many-to-many naturally** — Marina Klusas at Braze covers Yum,
  RBI, and IHG; Yum has assignments to Braze AE + Snowflake SE +
  Hightouch lead simultaneously
- **Two-stage picker** keeps the UI lean — no flat list of every
  partner contact across every partner
- **Already-assigned suppression** in the picker prevents
  accidental duplicates
- **Reverse lookup endpoint** lets the Partners tab show
  *"assigned to N leads"* per contact (UI for this is on the
  backlog but the data is there)

### Tests
- 371 total (+12). New `test_lead_partner_assignments.py`:
  - Store: empty lead returns empty, assign creates row, idempotent
    update preserves assigned_at, validation rejects empty ids,
    unassign idempotent, list_for_contact finds cross-lead,
    multiple partners per lead
  - Endpoints: single + bulk assign, list with enrichment,
    unassign, 400 on missing ids, reverse-lookup endpoint

### Contact-management plan — updated
- ✅ Tier 1a: Partner touch cadence + overdue (v0.10.0z)
- ✅ **Tier 1b new**: Lead ↔ partner-contact assignments (this release)
- Next priorities (unchanged):
  - Status lifecycle + touch cadence on **lead** contacts (parity)
  - Engagement timeline per contact
  - Cross-surface contact search

## [0.10.0z] — 2026-05-21 — Partner contact touch cadence + overdue surfacing

Phase 1 of the contact-management plan: every partner contact gets a
**touch cadence** (default 30 days) + **last_touched_at**. Adding a
note auto-counts as a touch. Overdue contacts surface in a top-of-page
panel so the AE never forgets who's gone cold.

### Added — backend
- **`cadence_days`** field on partner contacts (default 30, clamped
  1–365). Editable per contact via the form.
- **`last_touched_at`** timestamp. Set automatically by:
  - `add_note(...)` — server bumps it after saving any note
  - `POST /api/partners/<id>/contacts/<cid>/touch` — explicit
    "mark touched" without a note (for off-platform interactions)
- **`annotate_touch_state(contact)`** — pure helper that adds
  `next_touch_due`, `days_since_touch`, `days_until_due`, `overdue`,
  `is_due_soon` to a contact dict. Called by `list_contacts` so the
  UI doesn't recompute.
- **`overdue_contacts(partner_id?)`** — returns active contacts
  past their cadence. Across-all-partners when `partner_id=None`.
  Baseline-from-added_at rule: never-touched contacts go overdue
  once the cadence elapses since the contact was added.

### Added — server endpoints
- `GET  /api/partners/overdue?owner=X` — cross-partner overdue
  roster, enriched with `partner_name` for the UI. Owner filter is
  case-insensitive. Sorted most-overdue first.
- `POST /api/partners/<id>/contacts/<cid>/touch` — log a touch
  without adding a note.

### Added — UI
- **🔔 Overdue contacts panel** at the top of the Partners view
  (red-bordered). Grouped by partner, shows name + title + last
  touched + days overdue + cadence + MR owner. Two actions per row:
  - **✓ Mark touched** (one-click reset)
  - **Open partner →** (jumps to the partner detail)
  - Collapse / Expand toggle on the panel header.
- **Last touch column** in the contacts table. Shows friendly
  relative date (*"today" / "12d ago" / "3mo ago"*) + a subtitle:
  - **Overdue Nd** in red when past cadence
  - **Due in Nd** in yellow when within 7 days
  - **cadence Nd** in muted text otherwise
- **Overdue rows tinted red** in the contacts table so they pop
  even before you check the column.
- **✓ Mark touched button** per row.
- **Cadence picker in the contact form** — dropdown with 7/14/21/30/
  45/60/90/120/180 day options.
- **Last touched display** in the contact form so you can see the
  exact timestamp when reviewing.
- **Note add toast** updated to *"Note added · touch logged"* and
  the overdue panel refreshes inline.

### Tests
- 359 total (+11). New `test_partner_touch_cadence.py`:
  - Default cadence 30, clamped 1–365
  - Recently-added contact not yet overdue
  - 90-day-old never-touched contact IS overdue
  - `touch_contact` bumps `last_touched_at`
  - Touching a stale contact clears its overdue state
  - `overdue_contacts` excludes non-active statuses
  - Endpoint: overdue list with partner_name enrichment,
    owner filter, touch endpoint, note-add bumps touch

### Contact-management plan (for the record)
Decided in this conversation:
- **Distinct stores** kept for lead vs partner contacts (no
  unification refactor).
- **Tier 1 priority**: touch cadence → ✓ shipped this release.
- **Tier 1 backlog**: status lifecycle on lead contacts, engagement
  timeline per contact, owner assignment with bulk reassign.
- **Tier 2 backlog**: cross-surface contact search, "My contacts"
  view, stale-contacts report (now partly addressed by overdue
  panel, but lead-side is still missing).
- **Tier 3 backlog**: org chart visualisation, multi-tag
  territory/region, AI-extracted contacts from call transcripts.

## [0.10.0y] — 2026-05-21 — Partners CRM view (Phase 1)

New top-level surface for the Partnerships team to manage partner orgs
+ their contacts. Distinct from leads (orgs we sell TO). Phase 1 ships
the full data model + CRUD UI + notes; Phase 2 will add the org chart
visualisation (`reports_to_id` field is already in the schema).

### Added — backend
- **`partners_store.py`** — single-file JSON registry of partner orgs
  at `cache/partners/index.json`. Fields: name, type, url, owner,
  description, status, timestamps. `PARTNER_TYPES` enum:
  Technology partner / Sourcing partner / Reseller / Agency partner /
  Other.
- **`partner_contacts_store.py`** — JSON-per-partner contact list at
  `cache/partner_contacts/<partner_slug>.json`. Per-contact fields:
  name, title, email, linkedin_url, phone, **territory**, **region**,
  **country**, **industries** (multi), mr_owner, **reports_to_id**
  (for org chart Phase 2), status, tags. Tolerant input: industries
  accept either a list or a comma-separated string.
  - `TERRITORIES`: Strategic Enterprise / Enterprise / Mid-Market / SMB
  - `REGIONS`: UK / West Coast / East Coast / Central / EMEA / APAC /
    LATAM / ANZ / Global
  - `INDUSTRIES`: QSR / C-Store · Gas / Retail / Financial Services /
    Travel & Hospitality / Healthcare / Media / Telecom / SaaS / Other
- **`partner_notes_store.py`** — per-(partner, contact) touch-point
  notes at `cache/partner_notes/<partner_slug>__<contact_id>.json`.
  Types: call / email / intro / touch / other. Cascade-deletes when
  the parent contact is removed.

### Added — server endpoints
- `GET  /api/partners/enums` — all dropdown lists in one round-trip
- `GET  /api/partners` — list (annotated with contacts_count)
- `POST /api/partners` — create
- `GET  /api/partners/<id>` — partner + nested contacts
- `PATCH /api/partners/<id>` — update
- `DELETE /api/partners/<id>` — refuses with 409 if contacts exist
- `GET  /api/partners/<id>/contacts` — list
- `POST /api/partners/<id>/contacts` — create / update (bulk via `{contacts:[...]}`)
- `PATCH /api/partners/<id>/contacts/<contact_id>` — update single contact
- `DELETE /api/partners/<id>/contacts/<contact_id>` — delete (cascades notes)
- `GET  /api/partners/<id>/contacts/<contact_id>/notes` — list
- `POST /api/partners/<id>/contacts/<contact_id>/notes` — add
- `DELETE /api/partners/<id>/contacts/<contact_id>/notes/<note_id>` — delete

### Added — UI
New **Partners** nav entry (4th tab after Qualify Lead / Pipeline /
Project Build).

**Partners list**:
- Table: name + URL · type · contacts count · status · MR owner
- **+ Add partner** button: name (required), type dropdown, URL,
  MR owner, description
- Click **Open →** on any row → partner detail expands inline

**Partner detail** (inline below the list):
- Header: name, type, URL, description
- **Filter contacts** row: Territory · Region · Country (contains
  search) · Industry · Status · **+ Add contact** (right-aligned)
- **Contacts table**: name + email + LinkedIn · title · territory ·
  region+country · industries (signal-green chips) · MR owner ·
  ✎ edit · 📝 notes · × delete
- **Contact form** (inline panel): full metadata including
  multi-select industries (chip toggles) + reports-to dropdown
  populated from sibling contacts (sets up org chart for Phase 2)
- **Notes panel** (📝 button per row): inline list of dated touch
  points with type pill (call / email / intro / touch / other) +
  per-note delete; new note input above the list

### Tests
- 348 total (+20). New `test_partners.py` covers:
  - Stores: CRUD, name-required validation, alpha sort,
    industries-as-string parsing, status sort active-first,
    cross-partner isolation, cascade delete of notes
  - Endpoints: enums shape, create → list → get partner flow,
    contact save with full metadata, note add + list, 409 when
    trying to delete a partner with contacts

### Out of scope (Phase 2)
- Org chart visualisation (`reports_to_id` field is ready; renderer
  comes next)
- Cross-partner contact search ("find every CMO across all partners")
- Linking partner contacts back to lead `sourced_for_partners` /
  `opportunity_source` (currently those are free-text tags)
- Bulk CSV import for migration from existing partner spreadsheets

## [0.10.0x] — 2026-05-21 — Light-mode contrast pass + AI scope prefill from notes

Three asks bundled.

### Fixed — Light mode contrast (WCAG AA pass)

Token audit found three families failing AA on white surfaces:

| Token | Was | Now | Ratio on white |
|---|---|---|---|
| `--text-muted` | `#8a8a92` | `#5a5a62` | 3.5:1 → 7.0:1 ✓ |
| `--text-dim` | `#56565f` | `#4a4a52` | 7:1 → 8:1 ✓ |
| `--green` (text) | `#16a34a` | `#15803d` | 4.0:1 → 5.4:1 ✓ |
| `--yellow` (text) | `#d97706` | `#a16207` | 4.0:1 → 5.7:1 ✓ |
| `--red` (text) | `#dc2626` | `#b91c1c` | 5.0:1 → 6.0:1 ✓ |
| `--blue` (text) | `#2563eb` | `#1d4ed8` | 4.5:1 → 6.4:1 ✓ |

New `--accent-text` token (defaults to `--accent` in dark; darker
`#c8391f` in light, ~5.4:1) replaces `color: var(--accent)` everywhere
the accent is used as TEXT. Brand orange `--accent` stays for buttons,
borders, the dot accent — all the places it's a background or
decorative colour with white text on top.

Replaced `color: var(--accent);` with `color: var(--accent-text);` via
replace_all — 7 lines updated, all foreground text usages.

Dark mode is unchanged — the `:root { --accent-text: var(--accent); }`
fallback makes that token transparent for the dark path.

### Added — AI scope prefill from notes

When the AE pastes a transcript or note, the extraction now also
pulls **scope criteria values per project type** and writes them
into `project_store` for the lead. No more retyping numbers Claude
already extracted from the call.

Examples of what it captures from a transcript:
- *"30 campaigns to migrate, 8 templates"* → `crm_build`:
  `migrating_campaigns: 30, templates_count: 8`
- *"Need SDK on website + 2 iOS apps + Android, using Braze"* →
  `engineering`: `sdk_websites_count: 1, sdk_ios_apps_count: 2,
  sdk_android_apps_count: 1, sdk_platform: Braze`
- *"6-month CDP build"* → `crm_strategy`: `engagement_length: 6`

**Safety rules** (encoded in `_apply_scope_prefill`):
1. **Never overwrites AE-confirmed values** — only fills criteria
   where `value` is currently empty.
2. **Only writes to existing streams** — if AI extracted a project
   type that's not on the project, we skip it. AE decides which
   streams to add.
3. **Unknown criterion keys ignored** — AI hallucinations are
   silently dropped.
4. **Audit logged** as `scope_prefilled_from_notes` with source call id.

**Toast feedback**: after note save, *"✨ AI pre-filled 5 project
criteria (3 in crm build, 2 in engineering)"*. Same path for both
the inline "Save note now" button and the header Save's pending-note
path.

### Prompt changes
`_EXTRACT_SYSTEM_PROMPT` extended with a `scope_criteria` schema
section listing the expected keys per project type. Conservative
rubric — *"Only fill values that are EXPLICITLY supported by the
notes"* and *"Numbers and counts should appear verbatim"*. Encourages
null/omit when uncertain.

### Tests
- 328 total (+7). New `test_scope_prefill.py`:
  - Normaliser keeps the scope_criteria schema in the prompt
  - `_apply_scope_prefill` fills empty criteria
  - Never overwrites AE-filled values
  - Skips project types not on the project
  - Returns empty list when no project / no extraction
  - Unknown criterion keys silently dropped

### Plumbing — also fixed
`_actor()` now tolerates being called outside a Flask request
context (try/except RuntimeError → "anon"). Enables tests to
exercise server-internal helpers directly.

## [0.10.0w] — 2026-05-21 — ↻ Rescore button in the lead drawer

Re-scoring previously required *editing* a scoring-relevant field
and clicking Save — the v0.10.0p side-effect rescore. Useful when
you were already editing, less useful when you just wanted a fresh
score (e.g. after tweaking values in Notion directly, or after a
scoring-weight change). This adds an explicit Rescore action.

### Added
- **`POST /api/lead/<id>/rescore`** — recomputes ICP score from the
  lead's current Notion state, writes the new `icp_normalised` +
  `opportunity_type` back, returns the full score breakdown in the
  response. No edit body required.
- **`_rescore_lead_from_notion(sync, page_id)`** — new server helper
  that consolidates the rescore logic (lead fetch → score → write
  back → return). Used by the new endpoint; the existing PATCH
  side-effect rescore keeps its inline copy for now to avoid
  refactor risk on a working flow.
- **`↻ Rescore` button in the drawer header**, next to Save. Shows
  a spinner while in flight, flashes the new score in the toast
  (*"Rescored → 7.3/10 (Qualified)"*), refreshes the ICP pill in
  place, kicks a pipeline refresh so the row score behind the
  drawer also updates.

### Where it fits
- **Account view from pipeline** = the lead drawer that opens on a
  row click.
- **↻ Rescore** sits in the sticky drawer header between the
  primary Save button and ✕ Close.
- Tooltip: *"Recompute ICP score from current Notion values"*.

### Audit log
- New `lead_rescored` event with `trigger: "manual"` to distinguish
  from auto-rescore on edit (`trigger: omitted`).

### Tests
- 321 total (+2). New `test_rescore_endpoint.py`:
  - returns 502 cleanly when Notion is unavailable
  - mocked happy path calls `calculate_icp_score` and writes
    `icp_normalised` back via update_page

### Use cases
- Lead's revenue/employees got updated in Notion directly (e.g.
  after a public earnings announcement) — hit Rescore to refresh.
- Scoring weights got tuned — bulk rescore key accounts one click
  each.
- ICP pill looks stale or out-of-sync with Notion — hit Rescore to
  rebuild from scratch.

## [0.10.0v] — 2026-05-21 — Project briefing preview (the SOW-style preview, but for the project)

The SOW is a versioned formal document. Ben asked for the same
preview pattern but on the **project** itself — a one-pager that
rolls up the current state without drafting a new SOW each time.
Same modal, different content.

### Added
- **`project_preview.py`** — renders the live project as a single
  printable HTML document:
  - **Header**: company, URL, region, vertical, ICP pill, status,
    sales stage, opportunity type, owner
  - **Hero**: AI Lead Summary state-of-play + next action
  - **BANT-S Health strip**: 5 tiles with RAG colour
  - **Key facts / Open questions / Risks** (from AI summary)
  - **Scope**: per-stream criteria table with values + health pills
  - **Pricing snapshot**: currency + rate card + grand total + by-phase + by-role
  - **Roadmap**: milestones table + extended-engagement opportunities
  - All sections gracefully omit themselves when data is missing —
    a half-built project still renders cleanly.
- **`GET /api/project/<lead_id>/preview.html`** — assembles the
  snapshot from Notion lead + lead_summary_store + calls aggregate
  + project_store + pricing_store + roadmap, renders via
  `project_preview.render_html`. Same Content-Type as SOW.
- **`_gather_project_preview_snapshot(lead_id)`** — server helper that
  pulls everything in one pass. Best-effort: pricing/roadmap render
  errors don't break the whole preview.
- **Project Build → Documents card** (renamed from "Draft SOW"):
  - **👁 Preview project briefing** (ghost) — opens the modal with
    the current state
  - **📝 Draft SOW** (primary) — unchanged, creates a versioned
    snapshot

### Same modal as SOW
The preview reuses the v0.10.0u doc preview modal — Print / Download
HTML / Open-in-new-tab / Esc-to-close all work identically. No new
modal infrastructure.

### Why this matters
- AE shares a project briefing with delivery without committing to a
  formal SOW snapshot
- Updates instantly — every change to scope / pricing / roadmap /
  notes is reflected next time you click Preview
- Cleaner artifact than the drawer screenshot — printable A4 doc
  with proper hierarchy and colour-coded BANT

### Tests
- 319 total (+7). `test_project_preview.py` covers:
  - minimal snapshot renders valid HTML
  - summary sections (state, facts, questions, risks) render
  - BANT tiles get RAG classes
  - scope streams + criteria render
  - pricing totals format with currency symbol + phase/role breakdowns
  - roadmap milestones + extended items render
  - empty sections omit their headings cleanly

## [0.10.0u] — 2026-05-21 — Inline document preview modal

SOWs used to open in a new browser tab (a Blob URL with no
filename, no toolbar context). Reviewing meant context-switching
out of the platform. Now SOWs preview **inline** in a full-page
modal with Print / Download / Open-in-new-tab options.

### Added
- **Document preview modal** (`#doc-preview-overlay`) — full-page
  overlay with backdrop blur, dark sticky header with title +
  subtitle, white document body via `<iframe>` srcdoc (keeps the
  SOW's CSS isolated from the app shell).
- **Header actions**: 🖨 Print · ⇣ Download HTML · ↗ Open in new tab ·
  ✕ Close.
- **Esc to close** — modal Esc takes priority over the lead drawer's
  Esc handler so it closes the right thing.
- **Backdrop click closes** — clicking outside the modal body
  dismisses, modal body click does nothing.
- **Body scroll-lock** while open so the underlying page doesn't
  scroll behind it.
- **Tablet/mobile**: modal becomes full-bleed with tightened header
  buttons under 720px width.

### Changed
- **SOW versions table**: each row now has a primary **👁 Preview**
  button + the existing **↗** (new tab) as a quieter ghost.
  Preview is the new default action.
- **Drafting a new SOW** now opens the preview modal immediately
  instead of spawning a new tab. Print / Download / Open-in-new-tab
  are all one click away from there.

### Why this matters
- AEs review SOWs without losing their place in Project Build.
- Print path is reliable — the iframe handles its own print dialog
  with the document CSS intact.
- Download as HTML gives an artifact for email attachment.
- Open-in-new-tab is still there for AEs who want a permanent tab.

### Plumbing
- `_docPreviewState` holds the html / leadId / version / filename
  for the active preview so Print/Download/New-tab can act on it
  without re-fetching.
- `previewSow(leadId, version)` fetches the rendered HTML (same
  endpoint the new-tab path uses), populates the iframe via
  `srcdoc`, sets title + subtitle, opens the overlay.
- Reusable: the same modal will handle Proposal previews, future
  PDF rendering, etc. — `previewSow` is the first consumer.

### Tests
- 312 total. UI-only change; existing SOW endpoint tests cover the
  render path that feeds the modal.

## [0.10.0t] — 2026-05-21 — Country dropdown for Apollo people search

Without a country filter, Apollo's people search returns the whole
global org. For a multinational like KFC / IHG / Marriott, that's a
hundred unrelated marketers across 50 countries — useless for an AE
selling into a specific region. This release scopes the search.

### Added — Country dropdown on the qualify form
Step 1 ("Input") now has two new fields:
- **Country** — dropdown with 40+ ICP-relevant countries, grouped
  into Core ICP / EMEA / APAC / LATAM, plus "Any (global)" default.
- **Multiple countries** — free-text comma-separated input for
  multi-region searches (e.g. *"United States, United Kingdom"*).
  Overrides the dropdown when both are set.

Selected countries are sent as `overrides.person_locations` on the
`/api/qualify` POST.

### Added — Country picker on the drawer's contact-search button
The 🔍 Search Apollo button in the Contacts panel now sits next to
the same country dropdown. AE can refine which region to pull each
time they re-search — no need to re-qualify the lead. The dropdown
**defaults to the lead's saved region** (extracted from strings like
"NAM (United States)") so the smart pick is one click.

### Plumbing
- **`apollo.search_people` accepts `person_locations: list[str]`**.
  Apollo's API uses this as a free-text list of countries/regions
  ("United States", "EMEA", "DACH" all work). Cleaned and dropped
  from payload when empty.
- **Fixture mode honours the filter** — fixtures are filtered
  client-side by the person's `country` field so tests can exercise
  the path without hitting Apollo.
- **`QualificationOverrides` gets `person_locations: list[str]`** so
  the full qualify pipeline carries it through to the people search.
- **`POST /api/contacts/<id>/search` accepts**
  `{person_locations: [...]}` OR shorthand `{countries: "a,b,c"}`.

### Tests
- 312 total (+4). New tests cover endpoint acceptance of both
  parameter shapes, Apollo location filter narrowing fixture
  results, and country country-match correctness.

### Why this matters operationally
- **CDP/ESP buyers usually live in HQ.** Yum!/KFC headquartered in
  Louisville means US filter pulls the actual decision-makers, not
  KFC India marketers.
- **Regional rollouts** (e.g. "Marriott EMEA" engagement) get a
  tight contact list instead of a 100-person global dump.
- **Faster discovery** — fewer to triage, more relevant to outreach.

## [0.10.0s] — 2026-05-21 — Search Apollo from the contact panel + harden save-contact

Three asks bundled. Contacts are now searchable, saveable, and
unambiguously bound to their lead.

### Added — Search Apollo for contacts (from the drawer)
Prominent new **🔍 Search Apollo for contacts** button at the top of
the Contacts section. Click → server runs `apollo.search_people`
against the lead's URL/domain → returns up to 15 candidates flagged
with `already_saved: true` for any we've already got.

UI then renders the candidate list with checkboxes:
- Pre-checked by default for unsaved entries
- Disabled + `SAVED` badge for already-saved entries
- Toggle-all helper
- **Save selected →** commits via the existing bulk `POST
  /api/contacts/<lead_id>` array shape
- Close button to dismiss without saving

Works whether or not the AE has clicked Re-score recently — the
search uses whatever URL is currently on the lead.

### Added — New endpoint `POST /api/contacts/<lead_id>/search`
- Body: `{domain?: str, url?: str, apollo_id?: str, limit?: int}`
- Returns: `{candidates: [...], count: int}` with each candidate
  annotated `already_saved: bool` based on email/linkedin/apollo_id
  match against the lead's existing contacts.
- Errors handled gracefully — Apollo failures return 502 with
  empty candidates so the UI shows a clean error toast.
- Audit log captures `contacts_searched` events.

### Hardened — addContactManual save flow
- Spinner state on the "Add contact" button while in flight.
- Manual-add `<details>` auto-closes on successful save.
- Explicit success toast names the contact: *"Contact added — Jane Doe"*.
- Errors now log to console as `[addContactManual]` for diagnostics.

### Contact association — confirmed sound
Contacts are stored per-lead at `cache/contacts/<slug>.json`. The
same lead_id flows from URL → store path → file → list_contacts.
Verified by the new test suite that the round-trip works even with
hyphenated UUIDs (Notion page IDs). No bug here — the path is
construction-correct.

### Tests
- 308 total (+3). New `ContactSearchEndpointTests`:
  - 400 when neither domain nor apollo_id provided
  - 200 + candidates array shape on a valid domain
  - `already_saved` flag round-trips correctly

## [0.10.0r] — 2026-05-21 — Martech contacts + clipboard share for notes

Two AE-quality-of-life asks landed together.

### Added — Martech / Marketing Operations titles in Apollo search
`DEFAULT_PEOPLE_TITLES` was missing the Marketing Technology /
Marketing Operations roles that actually own the CDP + ESP decision
in QSR / retail / travel buyers. Now includes:

- VP / Director / Head of Marketing Technology
- VP / Director / Head of Martech
- Martech Lead, Martech Architect, Marketing Technologist
- VP / Director / Head of Marketing Operations
- Marketing Operations Manager, Senior Manager Marketing Operations
- Director Marketing Technology & Analytics
- Director / Head of Digital Experience
- Director / Head of Digital Product
- Head / Director of Data Platform
- Head / Director of Data Science

`qualify_service.qualify()` uses the default list (no consumer
changes), so every new qualification picks them up. Existing
qualified leads keep their saved stakeholders; re-run qualification
on a lead if you want to refresh the contact pull with the broader
title net.

### Added — Copy buttons for synthesised notes
Per Ben's feedback that the team needs to share notes externally.

- **Per-call 📋 Copy button** on every call card (next to ✎ Edit
  note). Copies the synthesised note as portable markdown, prefixed
  with TYPE · TITLE · TIMESTAMP. Drops cleanly into Slack, email,
  Notion.
- **Lead Summary 📋 Copy button** in the drawer hero. Copies the
  whole structured summary as markdown:
  ```
  # Lead Summary — <Company>
  <state-of-play>
  **Key facts**
  - ...
  **Open questions**
  - ...
  **Next action:** ...
  **Risks**
  - ...
  _Generated <when> by Claude_
  ```
- New `copyToClipboard(text, sourceBtn)` helper. Uses modern
  `navigator.clipboard` on https/localhost; falls back to
  `execCommand('copy')` on non-secure / older browsers. Button
  flashes "✓ Copied" or "× Copy failed" for 1.4s.
- New `formatNoteForCopy(call)` + `formatLeadSummaryForCopy(ai,
  company)` formatters keep clipboard output consistent.
- Latest summary cached client-side per lead in `_summaryCache` so
  the header copy can grab structured data without re-fetching.

### Tests
- 305 total (+1). `test_includes_martech_and_marketing_ops` pins
  the new titles.

## [0.10.0q] — 2026-05-21 — Light theme + theme switcher

Adds a light theme alongside the existing dark one. AE clicks the
🌙 / ☀️ button in the top nav to toggle. Choice persists in
localStorage; first-time users get whatever their OS is set to
(`prefers-color-scheme`).

### Added
- **Theme token system** in `:root` and `:root[data-theme="light"]`.
  Every colour, glass surface, focus ring, and gradient routes
  through a CSS variable so swapping themes is a single attribute
  change.
- **Light palette** designed for long-session readability:
  - `--bg` warm off-white (`#f7f7f2`), `--surface` pure white,
    `--surface-2` very subtle grey
  - Status colours bumped slightly for white-background contrast:
    `--green` `#16a34a`, `--yellow` `#d97706`, `--red` `#dc2626`,
    `--blue` `#2563eb`
  - Brand orange (`--accent #ff4d2a`) stays consistent across themes
  - Shadows softer: `0 4px 14px rgba(20,20,30,.06)` vs dark's
    `0 8px 24px rgba(0,0,0,.32)`
- **Theme toggle button** (🌙 / ☀️) in the top nav, right of the
  view tabs.
- **Inline hydration script** in `<head>` flips the `data-theme`
  attribute before paint so users never see a dark-flash-then-light
  flicker.
- **OS preference fallback**: if no stored choice, reads
  `matchMedia('(prefers-color-scheme: light)')`.
- **icp-pill colour variants** (`.icp-pill.qualify_in`,
  `.borderline`, `.qualify_out`) so the score chip in the drawer
  header carries the right colour in both themes. Was a pre-existing
  cosmetic gap — colours were assigned but never styled.

### Fixed alongside
- **Spinner used hardcoded white** (`border-top-color: #fff`) which
  vanished on light surfaces. Now uses `currentColor` so it inherits
  from the surrounding text; primary buttons force white via a more
  specific selector.
- Backdrop-blur surfaces (top nav, drawer header) now read from
  `--bg-glass` / `--bg-drawer-glass` tokens.

### Smooth switch
150ms `background-color`/`color`/`border-color` transition on heavy
surfaces (cards, tiles, drawer, inputs) so flipping the theme feels
deliberate, not jarring.

### What stays the same in either theme
- Brand orange (accent)
- Status semantics (green = qualified, yellow = borderline, red = out)
- Layout, hierarchy, all interactions

### Tests
- 304 total. No behavioural change — pure CSS + JS hydration.
  Both inline `<script>` blocks parse cleanly.

## [0.10.0p] — 2026-05-17 — Re-score on lead edit + auto-summary on note save + visual polish

Three asks from Ben in one release.

### Fixed: editing scoring fields doesn't re-score the lead
Editing Tech Stack (or revenue, employees, vertical, complexity,
region, deal_size, stack_confidence) in the drawer was landing the
change in Notion but leaving the ICP score stale. Now the PATCH
endpoint re-runs `calculate_icp_score` whenever any scoring-relevant
field changes, writes the new score back to Notion, and returns it in
the response. The drawer header pill updates instantly.

- `notion_sync.update_page` now accepts `icp_normalised`, `icp_total`,
  `opportunity_type_key` so the rescoring write can land cleanly.
- New `_SCORING_FIELDS` constant in server.py defines the trigger
  set; only changes inside that set kick off a rescore.
- Audit log captures `lead_rescored` events with new score + changed
  fields.

### Added: auto-summary refresh on note save
Previously the AE had to click ✨ Refresh to merge a new call's
content into the Lead Summary. Now `api_calls_add` re-runs
`synthesise_lead` inline after each note save and writes the updated
summary back. ~2 seconds of added latency, much better UX.

- Summary mirrors to Notion the same way the explicit refresh does.
- Returned on the call POST response as `summary`, so the UI renders
  the new state-of-play immediately without an extra GET.
- Both addCall (inline button) and saveLead's pending-note path
  consume the fresh summary.

### Visual polish (CSS only)
Lighter touch — no HTML restructuring, no breaking changes.

- **Background gradient**: subtle radial accent glow at the top of
  the page + faint blue counterpoint top-right + linear fade to flat
  bg by ~600px. Adds depth without distraction.
- **Cards**: subtle top-edge highlight + border-color hover.
- **Tiles**: subtle gradient overlay + lift-on-hover + accent-tinted
  background when manually overridden.
- **Score number**: bumped 64px → 72px, weight 700 → 800, gradient
  text fill that shifts colour with the qualify status (green for
  qualified, yellow for borderline, red for out). Tabular numerics
  so the digits don't jiggle on update.
- **Input focus**: soft 3px accent ring instead of just a border
  colour change.
- **Buttons**: lift-on-hover + accent-tinted shadow for primary; no
  shadow for ghost variant.
- **Drawer header**: backdrop-blur glass effect.
- **Dirty Save button**: stronger accent glow (3px ring + 14px
  shadow) so the call to action is unmissable.
- **Typography**: tighter letter-spacing on headings + tabular
  numerics on score/pill displays.

### Tests
- 304 total. No new tests — UI/CSS changes + server-side logic
  paths covered by existing endpoint tests with no behavioural
  regression.

## [0.10.0o] — 2026-05-17 — SDK implementation criteria under Engineering

Adds an SDK implementation block to the Engineering project type so
the AE can capture, per opportunity, exactly how many surfaces need
the SDK and which vendor we're implementing. Drives the pricing
model — each surface is real dev + QA work.

### Added — 7 new criteria under `engineering`
- **`sdk_platform`** — which SDK vendor (Braze, Iterable, mParticle,
  Segment, Firebase, AppsFlyer, etc.). Free text. No role driver
  (qualitative, doesn't scale a role on its own).
- **`sdk_websites_count`** — number of websites. Drives Software
  Engineer effort at scale_factor 1.0.
- **`sdk_ios_apps_count`** — iOS native apps. White-label brand
  variants count separately. SE × 1.2.
- **`sdk_android_apps_count`** — Android native apps. Same rule. SE × 1.2.
- **`sdk_hybrid_apps_count`** — React Native / Flutter / Cordova /
  Ionic etc. Bridge work less than fully native. SE × 0.9.
- **`sdk_other_surfaces`** — Connected TV, kiosks, in-store, voice,
  watch apps. Free text. Drives Architect effort at × 0.8 for the
  unusual-platform tax.
- **`sdk_complexity`** (1-5) — greenfield (1) vs identity merge /
  custom mapping (3) vs legacy GTM/Tealium → SDK migration (5).
  Drives Architect at × 0.6.

### Why discrete per-platform counts
Asked rather than computed because per-surface effort isn't linear:
two iOS apps with shared SDK config takes ~1.4× one; same for
Android. White-label brand variants are the common multiplier
(QSR / retail with 4-8 brand apps each get their own implementation).
The AE captures the count once during discovery; pricing scales
predictably.

### Where it shows up
- **Project Build → Engineering stream**: when an AE adds Engineering
  to a project's scope, the 7 SDK fields appear alongside the
  existing integrations / APIs / infra criteria.
- **Roadmap**: SDK rows count toward Software Engineer effort in the
  pricing preview, so the team budget reflects realistic build cost.
- **Criteria admin UI**: existing edit / delete / reset paths work
  on these the same as any other criterion.

### Tests
- 304 total (+2). Pin the SDK keys exist on engineering;
  per-platform counts must drive Software Engineer with positive
  scale_factor.

### Action note
Railway's `cache/` is ephemeral. If you've never customised
engineering criteria via the admin UI, the new SDK fields appear
on next redeploy automatically. If you HAVE customised, hit
**Reset to defaults** for the Engineering stream in admin to pick
up the new fields (you'll lose any custom edits).

## [0.10.0n] — 2026-05-17 — Save · 1 stale badge fix (root cause found)

The "Save button bug" was a stale badge, not a broken handler.

### Root cause
After clicking the inline "Save note now" button (`addCall`),
`$('#ld-new-call-content').value = ''` clears the composer
**programmatically**. Programmatic `.value` assignment does NOT
fire `input` events, so `updateDirtyState()` never re-runs. The
header **Save · 1** badge stays lit even though there's nothing
left to save. Clicking it triggers `saveLead()`, which correctly
sees empty edits + empty pendingNote and exits via the
"No changes to save" branch silently.

User sees Save · 1 → clicks → nothing visible → "broken Save button".

### Fix
- `addCall()` now calls `updateDirtyState()` immediately after
  clearing the composer fields. Badge correctly returns to ghost
  (no count) once the inline save completes.
- Same fix applies anywhere we clear form state programmatically.

### Diagnostics removed
v0.10.0i through v0.10.0m added visible diagnostics (toasts,
banners, native onclick alert, init try/catch with bright red
banner) to chase this bug. With the cause known, those are stripped
to keep the UI quiet. Kept the init try/catch as a safety net (it
just logs to console + shows a single non-noisy banner if init
genuinely fails).

### What this changes for you
- Save button now correctly reflects unsaved state at all times.
- After clicking "Save note now" inline, the header Save returns to
  its idle ghost state immediately, no leftover · 1.
- The header Save still commits notes too (v0.10.0f behaviour
  unchanged) — both paths are valid.

### Tests
- 302 total. UI fix only. No new tests — the bug was a one-line
  miss easier caught by E2E than unit.

## [0.10.0j] — 2026-05-17 — RAG MEDDPICC + BANT-S Health rollup

The hybrid framework from the design conversation. AE assigns RAG
(🔴 🟡 🟢) per MEDDPICC criterion; the system computes a 5-tile
BANT-S Health strip (Budget / Authority / Need / Timeline / Scope)
above the qualify result and in the drawer hero. No duplicate data
entry — BANT renders from MEDDPICC + scope.

### Added
- **9th MEDDPICC criterion: Budget Confirmed.** Feeds the BANT-S
  Budget tile. Same schema as the other 8 (value + status + health).
- **`health` field** on every MEDDPICC entry: `"red" | "amber" |
  "green" | None`. Separate from `status` (workflow state) so we can
  render qualification confidence independently of "have we touched
  this." Status auto-mirrors from RAG for back-compat
  (red/amber → in_progress, green → confirmed, cleared → not_started).
- **`bant_health.py`** module:
  - `derive_bant_health(meddpicc, scope_state)` returns 5 tiles, each
    with `{health, caption}`.
  - `overall_score(bant)` returns counts + worst-of for future
    pipeline filter chips ("show me leads where Budget is red").
  - Mapping: Budget→budget_confirmed, Authority→economic_buyer,
    Need→worst(identify_pain, metrics), Timeline→decision_process,
    Scope→derived from streams + project_scope text.
- **`bant_health`** appears on the `/api/qualify` response and on
  `/api/calls/<lead_id>` GET (derived from rolling MEDDPICC +
  project scope), so the drawer renders the strip without an extra
  round-trip.
- **AI extraction prompt** now teaches Claude to suggest `health`
  per criterion with an explicit rubric (green = clearly satisfied,
  amber = partial, red = actively concerning, null = no signal).
  Bumped to be conservative — only set when notes really support it.

### UI
- **Qualify view: new "3 · BANT-S Health" card** between Auto-Discovery
  and ICP Score. 5 horizontal tiles, each with:
  - RAG-tinted border + faint background
  - Section label (BUDGET / AUTHORITY / etc.)
  - Caption: the captured MEDDPICC value, truncated to 2 lines, or a
    default ("Strong" / "Needs work" / "Concern" / "Not assessed")
  - RAG dot indicator top-right
- **Drawer hero: same 5-tile strip** above the Lead Summary text.
  Renders from `data.bant_health` returned by `/api/calls/<id>`.
- **MEDDPICC rows: replaced the 3-button "Not started / In progress /
  Confirmed" toggle** with a 4-button RAG toggle: 🔴 🟡 🟢 × (clear).
  Click → updates `health` immediately, mirrors to `status` for
  back-compat, re-renders the BANT strip live.
- **Section renumbering** in the Qualify view: BANT-S Health is now
  step 3; ICP Score → 4; Notes → 5; MEDDPICC → 6; Project Scope → 7;
  Fit Analysis → 8; Save lead → 9.

### Decisions made (for the record)
- **No separate BANT input fields.** Authority duplicates Economic
  Buyer; Need duplicates Pain+Metrics; Scope duplicates scope.py.
  Hybrid model (RAG on MEDDPICC + computed BANT strip) avoids double
  data entry while delivering the at-a-glance view Ben asked for.
- **Health is a separate field, not a replacement for status.** Two
  axes: status = workflow state, health = AE's qualification
  confidence. UI shows only the RAG buttons for now; status is
  auto-mirrored under the hood.

### Tests
- 302 total (+22). New `test_bant_health.py` covers: worst-of
  comparator, scope health derivation (empty/free-text/drafted/
  validated), per-tile derivation rules, default captions,
  truncation, overall aggregate. Existing MEDDPICC tests updated
  to 9 keys + assert `health` and `bant_health` shape.

## [0.10.0g] — 2026-05-17 — Drawer redesign

Single biggest UX upgrade since v0.1. The lead drawer was 7+ stacked
sections deep with three competing save buttons; you'd open KFC and
scroll to find anything. Now it has a sticky header, one save button,
the Lead Summary surfaced as a hero block, and accordion sections
collapsed by default so the most-touched part (Calls & Notes) is
always visible without scrolling.

### Changed (drawer)
- **Sticky header redesigned:**
  - Lead title bigger (17px vs 15px)
  - ICP score pill + status chip + group chip aggregated into a
    subtitle row (was three different places before)
  - ONE primary **Save** button — ghost when nothing's pending,
    accent-coloured with a count badge when there are unsaved changes
    (e.g. *"Save · 3"*)
  - **✕** button shrunk to a small ghost — the visual hierarchy is now
    clear about which action matters
- **Lead Summary moved to a hero block** at the top of the body, with
  accent border + faint background so it reads as the entry point.
  Was previously buried below 5 other sections.
- **All 6 other sections converted to native `<details>` accordions**
  (Identity / Qualification / Discovered / Notes & Fit / Project &
  Pricing / Contacts / Calls & Notes). Caret rotates on open. Header
  styled like an `<h4>` so the visual language stays consistent.
- **Calls & Notes opens by default** — it's the most-touched section.
  Everything else is collapsed so the drawer fits a single screen on
  open.
- **Section count badges** in summaries: *"Calls & Notes (4)"*,
  *"Contacts (2)"*. Tells you what's there without expanding.
- **Section dirty highlights:** when a section has pending changes
  the summary turns accent-coloured + caret tints orange. You can see
  at a glance which collapsed sections you've edited.
- **Footer removed.** The status line drops to a small inline element
  at the very bottom of the body; Save and Close both moved to the
  header where they're always visible regardless of scroll position.

### Added
- **`updateDirtyState()`** — counts dirty `data-ld` fields + draft
  note text + parent-link queue + sourced-for diff, updates the Save
  button class + count badge + per-section accent highlight.
- **Universal dirty listener** on `input` / `change` / sourced-for
  chip clicks within `#lead-drawer`. One listener, fires on every
  edit, never misses a field.

### Removed
- `#ld-cancel` button (the old footer Cancel — its job was "close
  without saving" which is what ✕ already does)
- The old footer entirely
- The duplicated read-only ICP pill inside the Qualification section
  (still rendered in the header)
- The old `<h4>` "Lead Summary" header (now lives in `.hero .hero-title`)

### Why this matters
The recent *"Save changes / No changes to save"* bug was a symptom of
the design: three save buttons and seven sections is too many for the
AE to track. With one save button and accordion sections, the model
is obvious — type anywhere, see the Save button light up, click it.

### Tests
- 280 total. Layout change only, no Python behaviour change. JS sanity
  parse green.

## [0.10.0f] — 2026-05-17 — Save changes commits pending notes + Lead Summary syncs to Notion

Two issues raised after Phase E rollout:

### Fixed: "Save changes" said "No changes to save" with a pending note
When the AE typed in the Calls & Notes composer and clicked the
drawer's footer "Save changes" instead of the inline "Save call /
note", the bottom save diffed only `data-ld` fields and refused. The
draft text was abandoned on close/refresh.

`saveLead()` now also picks up `#ld-new-call-content` as part of the
save flow:
- If lead fields changed AND there's draft note text → save both
  (lead PATCH first, then call POST).
- If only the composer has text → just save the call.
- If only lead fields changed → existing behaviour.
- If nothing changed → "No changes to save" (unchanged).

Status line summarises what was saved, e.g. *"Saved 2 fields + note"*.

### Added: Lead Summary auto-syncs to Notion
The cached AI summary lives in `cache/lead_summaries/` — ephemeral on
Railway. After ✨ Refresh, the summary now also writes to a **"Lead
Summary"** rich-text property on the Notion page (formatted block:
state of play → key facts → open questions → next action → risks →
generated timestamp).

- New writable field `lead_summary` in `notion_sync.update_page`.
- New helper `_format_summary_for_notion(summary)` renders the
  structured dict into a single text block (~1900 chars cap).
- Notion sync is best-effort: if the DB doesn't have a "Lead Summary"
  property yet, Notion returns 400, we log a warning, and the local
  cache still works.
- Audit log captures `notion_synced: bool` so failures are visible.

**Action for you:** add a **"Lead Summary"** column (type: Text) to
the Notion DB. Once it exists, every ✨ Refresh updates it. Until
then the local cache works the same as before.

### Tests
- 280 total (+2). New tests pin the format helper: full-summary
  renders all sections; minimal-summary omits empty ones.

## [0.10.0e] — 2026-05-17 — Account Groups (Phase E): add opportunity under a group

Two new entry points for adding a brand under a parent group, asked
for after the initial A–D rollout:

### Added
- **Qualify view: "Parent group" picker** inside Auto-Discovery,
  between the auto-detected tiles and the "Re-score with overrides"
  button. Typeahead over existing pipeline accounts plus a
  *"+ Use 'X' as parent group (created on save)"* fallback. Once
  picked, the chosen parent is stashed in `state.pendingParentLink`
  and the Notion save flow auto-links it as soon as the lead has an
  id (reuses the Phase B pending-link queue).
- **Parent drawer: "+ Add brand under this group" button** on the
  "Brands in this group" panel. Closes the drawer, switches to the
  Qualify view, prefills the parent picker, and focuses the company-
  name field — one click and you're typing the new brand.
- **Picker shows a `Group` chip** next to existing parents in the
  suggestions list so it's obvious whether you're linking to a
  standalone account or an already-established group.

### Behaviour
- Picker value is sticky until "× Clear" is clicked or the qualify
  form is cleared.
- The link only fires on save — Re-score doesn't create the link, so
  the AE can change their mind freely.
- Works for both Apollo-suggested and AE-picked parents — both paths
  share `state.pendingParentLink` and converge in `pushToNotion`.

### Tests
- 278 total. UI-only change, no new Python tests. JS sanity check green.

## [0.10.0d] — 2026-05-17 — Account Groups (Phase D): AI sibling + portfolio context

Final phase of the Account Groups feature. Claude now writes
portfolio-aware Lead Summaries. When you ✨ Refresh on KFC, the
summary draws on Pizza Hut / Taco Bell / Habit Burger state too:
*"Pizza Hut is closed-won on a similar CDP build — use as proof on
this call."* When you open Yum! Brands' drawer, the section is
relabelled **Portfolio Summary** and Claude writes group-wide
commentary across all 4 brands.

### Added
- **`_gather_group_context(lead_id)`** in server.py builds the parent /
  siblings / children block for Claude. Resolves slugs to display
  names via the pipeline. Returns one of three shapes:
  - `{role: "child", parent: {...}, siblings: [...]}` — brand under
    a parent
  - `{role: "parent", children: [...]}` — parent group, with each
    child's ICP, status, stage, vertical, opp type
  - `None` — standalone
- **`_gather_lead_context()` now includes** the `group` block on
  every summary call (wrapped in try/except so a graph lookup failure
  never blocks the summary).
- **`_LEAD_SUMMARY_SYSTEM_PROMPT` updated** with explicit GROUP
  CONTEXT rules teaching Claude to:
  - For children: surface sibling wins as reference points, call out
    central-buying risk when the parent looks like the economic
    buyer, flag sibling-status patterns in key_facts. Keep
    open_questions specific to THIS lead, not siblings.
  - For parents: describe portfolio-wide momentum; next_action is a
    portfolio-level move (exec briefing, MSA renewal, cross-brand
    reference call).
- **Drawer Lead Summary card relabels** based on the group role:
  - Parent → "Portfolio Summary — AI synthesis across all brands in
    this group"
  - Child → "Lead Summary — AI synthesis, sibling-brand context
    included"
  - Standalone → "Lead Summary — AI synthesis across notes +
    qualification" (unchanged)

### Tests
- 278 total (+2). New `test_group_context_none_for_standalone`
  verifies the default; `test_prompt_documents_group_context`
  pins the prompt schema so a future refactor can't silently drop
  the group-context teaching.

### Account Groups feature — complete summary
After Phase A → B → C → D, you can:
1. **Manually link** a brand to a parent via the drawer picker.
2. **Auto-suggested links** appear after qualification when Apollo
   data hints at a parent.
3. **Pipeline shows** parents grouped with their brands collapsed,
   filterable by group.
4. **Claude writes** portfolio-aware analysis from both directions
   (child sees siblings, parent sees portfolio).

What's deliberately out of scope:
- Multi-level (Corp → Division → Brand). One level only.
- Mirror to Notion. The graph lives in `cache/` until you mount a
  Railway volume or migrate to Postgres.
- Group-level TCV roll-up in pipeline. Backlog.
- Auto-creating brand leads when a parent enriches. The AE always
  confirms each child link.

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
