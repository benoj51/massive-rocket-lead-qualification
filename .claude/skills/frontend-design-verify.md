---
name: frontend-design-verify
description: Use BEFORE making any visual/CSS change to qualify.html. Locks in the verify-before-claim loop so I stop shipping "design refreshes" the user can't see.
---

# Frontend design verification — qualify.html

## The failure mode this prevents

v1.0.0ch and v1.0.0ci both shipped CSS refreshes Ben described as
invisible ("I don't see any changes"). The pattern that failed:

1. Read about "modern dashboard" patterns
2. Edit CSS tokens (`--pad`, `--radius`, shadows, etc.)
3. Run unit tests + `node --check`
4. Commit + push
5. Tell Ben it's "modernised"
6. Ben: "I don't see any changes"

**The hole:** tests + syntax check confirm nothing broke. They do
NOT confirm anything looks different. CSS-token-only changes also
tend to land below the perception threshold — borders that go from
`#2a2a3a` to `#32323f` are invisible to humans even though they're
"correctly" softer.

## The rule

**Before claiming any UI change is shipped, take before + after
screenshots and compare them with your own eyes (or paste them to
the user).** Tests can't verify "looks better." Only eyes can.

## The loop

1. **Boot the local preview server** so I can see what I'm shipping:
   ```
   mcp__Claude_Preview__preview_start { name: "qualify-flask" }
   mcp__Claude_Preview__preview_resize { width: 1440, height: 900 }
   ```
   The repo has `.claude/launch.json` configured for this. The
   profile picker auto-opens on first load — dismiss it via:
   ```js
   Array.from(document.querySelectorAll('button'))
     .find(b => /Ben Ojuolape/.test(b.textContent)).click()
   ```

2. **Screenshot BEFORE** — at least Home + Pipeline + one detail view.

3. **Make the change.** Edit qualify.html.

4. **Hard-reload the preview** (the dev server serves the file from
   disk, so a normal reload picks up edits):
   ```js
   location.reload()
   ```

5. **Screenshot AFTER** the same surfaces. Compare side-by-side.

6. **If the diff isn't obvious to a casual glance, the change is too
   subtle. Don't ship it.** Go bigger:
   - Change `--sans` to a different font family
   - Shift `--bg` to a different hue
   - Move the nav from top to sidebar
   - Add a brand-new component (sparkline, progress bar, avatar
     circles)
   Tokens-only refinement won't register.

7. **Only after the visual diff is clear**, commit and push.

## Anti-patterns to refuse

- "It's more refined" / "subtler shadows" / "tighter radius" as the
  primary justification. Refinement is invisible.
- Editing 5 tokens and calling it a redesign. The visible delta of
  10 token tweaks ≈ the visible delta of 1 token tweak.
- Trusting `node --check` + unit tests as proof the design changed.
  They never prove that.
- Trusting "Railway deployed it" — verify the build actually picked
  up the latest commit. Open the deploy URL, view-source, look for
  the version string. (See `railway-deploy-check` skill.)

## When the user says "I don't see any changes"

Don't argue and don't ship another tokens pass. The fastest fixes,
in order of certainty:

1. **Verify the deploy.** Was the latest commit actually deployed?
   Did Railway succeed the build? Open dev tools → Network → check
   the qualify.html response headers / etag.
2. **Pick a dramatic single change** they can't possibly miss:
   font family, primary background colour, nav position. Ship just
   that one thing first, then iterate.
3. **Screenshot before/after as proof of what you changed.** Paste
   both into the chat.

## Tools to use

- `mcp__Claude_Preview__preview_start` — boot the Flask server
- `mcp__Claude_Preview__preview_screenshot` — capture renders
- `mcp__Claude_Preview__preview_eval` — navigate, dismiss modals
- `mcp__Claude_Preview__preview_resize` — set 1440x900 viewport
- `mcp__Claude_Preview__preview_inspect` — read computed styles to
  verify a specific change landed (e.g. did `font-family` actually
  change?)

## Repo-specific notes

- `qualify.html` is ~16k lines. Use the Edit tool with surgical
  `old_string` / `new_string` — never rewrite the file.
- Inline styles in HTML override stylesheet rules. If a change to
  the global CSS doesn't appear, grep for inline `style="..."` on
  the same property and remove it.
- The Settings → Integrations strip is at the top above the header.
  Keep verifying that strip still shows after layout changes.
- Light + dark mode both need to look right. Test both with
  `preview_resize { colorScheme: "dark" }`.
