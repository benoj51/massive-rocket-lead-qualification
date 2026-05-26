---
name: railway-deploy-check
description: Use when shipping HTML/CSS/JS changes and the user says "it looks the same" on the deployed Railway URL. Walks through verifying the deploy actually picked up the latest commit.
---

# Railway deploy verification

## The problem

This repo deploys to Railway from `main`. Push to `main` is
SUPPOSED to trigger a build, but multiple things can break the
chain:

- GitHub → Railway webhook silently disabled
- Build failed (Railway shows a red dot, you don't see it from
  CLI)
- Build succeeded but Railway is serving a cached old asset (less
  common but possible with `qualify.html` since it's served by
  Flask, not a CDN — usually NOT the issue here)
- Browser cache (`Cmd+Shift+R` proves or disproves)

If the user says "it looks the same" after a push, **don't ship
another design pass**. Verify the deploy first.

## Steps

1. **Confirm the commit is on origin/main.**
   ```bash
   git log --oneline -5 origin/main
   ```

2. **Open the live URL in a browser** (ask the user for the URL if
   unknown — likely `lead-qualification-platform.railway.app` or
   a custom domain).

3. **View source on the live URL.** The latest commit should be
   reflected somewhere. For this repo, the safest version stamp is
   the `<!-- v1.0.0xx -->` comments in `qualify.html` or a search
   for a unique class name added in the most recent commit.

   If the live HTML lacks that class, **the deploy didn't go
   through**. Tell the user and stop. Do not ship more CSS.

4. **If you can't see source remotely**, ask the user to:
   - Open Railway → Deployments tab
   - Confirm the latest deploy matches your commit SHA
   - Confirm the deploy is "Active" not "Failed"

## Add a visible version stamp (preventive)

To make future checks faster, the platform should expose its
version somewhere a human can see without dev tools. Options:

- A tiny `v1.0.0xx` next to the brand mark
- The version in the page `<title>`
- A footer line "Updated: 2026-05-26 · v1.0.0xx"

The util-strip at the top of the header is the natural spot.

## When to suspect deploy vs. taste

| Symptom | Likely cause |
|---|---|
| User says "same" + you can see your change locally | Deploy didn't go through |
| User says "same" + change is in computed CSS but invisible | Tokens-only / sub-perception change. See `visible-design-changes` skill |
| Some pages show new design, others don't | Soft refresh + browser cache. `Cmd+Shift+R` |
| New JS works but new CSS doesn't | CSS file cached, JS revved. Add cache-bust query param to the stylesheet href |

## Note for this repo specifically

`qualify.html` is served inline by Flask — there's no separate CSS
file. So "the CSS is cached but the JS isn't" can't really happen
for THIS file. If the live HTML lacks your change, it's a deploy
issue, full stop.
