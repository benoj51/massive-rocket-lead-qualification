---
name: visible-design-changes
description: Use when user asks for a "design refresh", "more modern", "bolder", or anything similar. Lays out which axes of change humans actually perceive vs. which are invisible.
---

# Visible vs. invisible design changes

A taxonomy from the v1.0.0ch + ci postmortem. Every "modernise this"
ask should start by picking from the **visible** column.

## Visible (high signal-to-effort)

These changes are obvious to a casual glance and survive being
viewed on a different monitor / phone / glance speed.

| Axis | Example change | Why it lands |
|---|---|---|
| Font family | `system-ui` → Inter / Geist / Söhne | Every character changes shape |
| Primary background | flat `#fafafa` → tinted off-white or layered | Page tone shifts |
| Nav layout | Top bar → left sidebar | Whole page composition flips |
| Page width | 1180px → 1440px+ | Empty side margins shrink |
| Hero number size | 22px → 32–48px | Eye is drawn somewhere new |
| Color hue | Single red accent → red + blue accent | New colour appears on page |
| Card treatment | Flat white → tinted / gradient / glass | Surfaces feel different |
| Spacing scale | All margins 14px → all 24px+ | Whole page breathes more |
| Add a chart | None → sparkline / progress bar / gauge | New visual primitive |
| Icons in nav | Text-only → text + icon | Compose changes |
| Avatars | None → coloured initial circles | New atomic element |

## Invisible (low signal, high effort)

These changes are correct and good craft but humans rarely notice.

| Axis | Example change | Why it doesn't land |
|---|---|---|
| Border shade | `#2a2a3a` → `#32323f` | Sub-perception threshold |
| Shadow refinement | Single shadow → layered xs/sm/md/lg | Reads identically |
| Radius bump | 12px → 16px | Eye doesn't measure curves |
| Letter-spacing | 0 → -0.01em | Below noise floor |
| Hover state polish | Brightness shift → shadow lift | Only visible on intent |
| Token rename | `--pad` 22 → 28 px | Only visible if comparing pixels |
| Transition timing | 150ms → 120ms | Below conscious threshold |
| Font features | Add `ss01`, `cv11` | Renders identically on most setups |

## The recipe for a perceived redesign

When the ask is "modernise this", combine 2–3 from the visible
column. Anything else is polish — ship it AFTER the user has
acknowledged the visible change landed.

**Proven combo:**
1. Custom font (Inter is the safe default)
2. Refresh primary background tone
3. Add one new visual primitive (avatars, sparklines, or a
   sidebar)

**Special case — "make it pop":** add a second accent colour.
Single-accent designs read as "default brand bootstrap." Two
accents read as "designed."

## The order matters

Do font + colour FIRST. They establish what the redesign even
feels like. Then component-level work (tables, cards, chips) makes
sense in the context of the new aesthetic.

If you start with cards + chips + shadows, the work is correct
but the user is judging it against the OLD font + OLD palette, so
it just looks like a slightly worse version of what was there.

## Anti-patterns

- "Layered shadow scale" as the headline change. It's invisible.
- "Refined typography hierarchy" without a font change. The
  hierarchy was probably fine; the FONT is what reads as dated.
- A "design refresh" that doesn't touch the colour palette. Colour
  IS the design vibe.
- Long CHANGELOG entries listing 30 token tweaks. If the user
  needs the changelog to see the redesign, the redesign failed.

## When the user shares a Dribbble / Figma reference

Don't paraphrase the reference into tokens. Pick the 2–3 most
distinctive visible things about it:

- What font is it using?
- What's the background colour, exactly?
- Sidebar or top nav?
- Are there charts? What kind?

Match those FIRST. The rest is detail.
