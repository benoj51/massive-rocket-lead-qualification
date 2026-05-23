# Changelog

All notable changes to the Massive Rocket Lead Qualification Platform.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
