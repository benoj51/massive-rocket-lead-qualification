# Massive Rocket — Pricing + Scoping Best Practices

This is Jeff's reference doc. Edit anywhere in this file; Jeff reads
the live version on every turn. Updates take effect immediately —
no deploy needed.

The factual numbers (rate cards, role catalogue, team templates) are
read from `pricing.py` automatically. This doc is for the soft stuff:
when to push back, how to frame tradeoffs, common AE mistakes.

---

## Choosing the right project type

Project types drive the team template. Picking wrong inflates the
quote by 20-40% and makes the conversation about cost rather than
value.

- **`crm_build`** — full Braze (or similar) implementation from
  scratch. Use when there's no existing platform OR the platform is
  being replaced wholesale. Heavy CRM Architect ramp across phases.
- **`crm_strategy`** — strategy-only engagement. No build work, no
  developers. Common shape: a 3-6 month roadmap engagement that
  precedes a `crm_build` SOW. Don't bundle build hours into a
  strategy SOW just to get a bigger number — the margin is fine and
  the next SOW lands easier.
- **`crm_execute`** — staff augmentation OR specific build modules
  on top of an existing platform. Use when the client already has a
  CRM Strategist + Architect in-house and just needs hands.
- **`data_work`** — data architecture / ETL / CDP integration. No
  Braze-specific roles. Use when the conversation is "we have a
  data problem" rather than "we have a CRM problem".
- **`engineering`** — bespoke engineering (custom apps, integrations
  outside the CRM stack). Pulls Engineering Lead + Software
  Engineer. Margin profile differs from CRM work — flag to
  Daniel Craig before SOW.

If the client wants multiple things, combine project types (e.g.
`["crm_build", "data_work"]`) — the pricing engine merges templates.
Don't over-combine: 3+ types usually means the scope is wrong.

---

## Rate cards — when to use which

- **`MR Default`** — start here. Blended $200/hour USD across every
  role. Use for net-new clients with no pre-existing rate agreement.
- **`Staff Augmentation`** — per-role, per-seniority, per-region
  rates. Use when the engagement IS staff aug (client manages the
  team) OR when a specific client wants line-item billing rather
  than blended. Requires picking region + seniority for each role.
- **Client-specific cards** — e.g. `Popeyes`, `Shell`. These exist
  when a master agreement locked specific rates. Use the matching
  card; never quote MR Default to a client with their own card on
  file.

If the client is asking "what's your rate?", that's a signal they're
benchmarking. Quote the blended rate ($200/hour USD) and add: "we
work in fixed-scope SOWs, not T&M, so the rate is one input —
what matters is the team mix and duration."

---

## Phase split

Default is 3/6/3 for a 12-month deal: Understand → Execute → Accelerate.
- **Understand** — discovery, audit, current-state mapping. Heavy
  Strategist + Architect; light Developer. 15% discount applies.
- **Execute** — the build. Architect + Developer ramp up,
  Strategist tapers.
- **Accelerate** — testing, training, handover. Architect peaks,
  Developer winds down.

Common deviations:
- 3/9/0 for an aggressive build with no formal Accelerate (handover
  blends into Execute).
- 6/6/0 for a complex Understand (multi-brand, multi-region) — push
  back on this; usually means scope wasn't tight enough at SOW.
- 1/10/1 — pure execution after a prior strategy engagement. Use
  when the client says "we know what we want, just build it."

Don't go below 1 month per phase; the math breaks and the SOW
becomes hard to defend.

---

## Project Ops + Contingency

Two uplifts that sit ON TOP of the gross calculation:

- **Project Ops %** — covers the non-billable management overhead
  that scales with project size. Default is 0%; typical is **10-15%**.
  Apply for any deal > $250K or > 6 months. Don't apply on staff
  aug (the client absorbs it).
- **Contingency %** — covers the "things we didn't know" risk.
  Default is 0%; typical is **5-10%** for known clients, **10-15%**
  for new logos in regulated industries (finance, healthcare,
  utilities). Above 15% you're either pricing in risk you should
  push back on OR scoping too loosely.

Both compound on top of the discounted total. If the client asks
"what's this line?", call it Project Operations or Risk Adjustment
respectively — don't say "contingency" out loud unless they ask
directly.

---

## Common client objections + responses

**"Your rate is higher than [competitor]."**
- Don't defend the rate. Defend the outcome. "Our $200 blended
  includes Strategist + Architect time that most competitors quote
  separately at $300+. Our line-item rate is competitive when you
  normalize for the team mix."
- If they have a real line-item quote at a lower rate, that's a
  Staff Aug conversation, not an SOW conversation. Switch posture.

**"Can you discount further?"**
- The 15% on Understand + first-half Execute is already aggressive.
  Pushing past 20% blended discount breaks the deal margin.
- Instead, offer to **reduce scope** (drop Accelerate, narrow
  Understand) or **extend the phase split** (longer Execute) to hit
  their monthly target without breaking the blended rate.

**"We're paying you $X/hour, we expect Y hours/week from each role."**
- The blended rate isn't a per-role utilization commitment. Surface
  the FTE allocations in the SOW + reset expectations on day 1.
- If they insist on tracked hours, that's Staff Aug — re-paper the
  SOW with the Staff Augmentation rate card.

**"Why is Program Manager 40% of an FTE? We don't need that much PM."**
- The 40% PM ramps to 60% in Accelerate; it's a weighted average
  not a constant. Explain the phase ramp.
- If they insist, drop to 0.25 FTE PM but flag in writing: SOW
  risk goes up + you'll need to re-scope if PM hours run out.

**"Can we do a smaller pilot first?"**
- YES. Pitch a 3-month `crm_strategy` engagement as the on-ramp.
  Lower-risk for them, gets you discovery + a designed roadmap,
  the follow-on `crm_build` SOW lands at 2-3x the pilot.
- Don't pitch a "small build" pilot — building before strategy
  produces work that gets thrown away.

---

## Common AE mistakes (frequency-ordered)

1. **Picking too many project types.** 3+ types in one SOW means
   the scope is wrong. Push back on the client to sequence the work
   into multiple SOWs.
2. **Defaulting Project Ops to 0%.** On any deal > 6 months this
   leaves margin on the table. Even at 10% it's invisible to the
   client at the line level.
3. **Quoting MR Default to a client with a custom card.** Always
   check `/api/pricing/rate-cards` for the client name first.
4. **Skipping the Understand phase to "save the client money".**
   This is how SOWs go over budget. Discovery cost paid upfront is
   cheaper than re-scoping mid-Execute.
5. **Forgetting to flag staff aug deals to Daniel Craig.** Margin
   profile differs; he wants visibility before the SOW lands.
6. **Quoting in client currency when the cost model is USD.** The
   GBP→USD exchange rate floats; the rate card has fixed numbers in
   each currency to avoid this. Use the right card, not a conversion.

---

## When in doubt

Loop in:
- **Daniel Craig** — for staff aug deals, deals > $500K, anything
  involving Engineering project type.
- **Thierry** — for net-new client logos, anything regulated, or
  if the client is asking for a master services agreement.
- **Jamie MacDow** — for anything that needs marketing co-funding.

Don't ship an SOW you can't defend the maths on. If you can't
explain why the number is the number, the client will sense it.
