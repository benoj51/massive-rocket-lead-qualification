"""
Project preview renderer (v0.10.0v).

Renders the current Project Build state — scope criteria, BANT-S health,
pricing snapshot, roadmap milestones, AI lead summary — as a single
printable HTML document. Mirrors the SOW pattern (`sow.render_html`)
but lighter: this is an internal briefing doc, not a customer-facing
SOW. AE uses it to share the project state with the delivery team or
print/email it for stakeholder reviews.

Inputs: the assembled snapshot from `_gather_project_preview_snapshot`
in server.py. Pure function — no I/O.
"""
from __future__ import annotations

from html import escape
from typing import Any


_HTML_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Project · {title}</title>
<style>
  @page {{ size: A4; margin: 16mm 14mm; }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
    color: #1a1a24; background: #f6f6f8; margin: 0;
    line-height: 1.5;
  }}
  .page {{
    max-width: 820px; margin: 24px auto; padding: 32px 40px;
    background: #ffffff; border: 1px solid #d8d8e0;
    box-shadow: 0 10px 30px rgba(0,0,0,.08);
  }}
  h1 {{ font-size: 26px; margin: 0 0 4px; letter-spacing: -0.02em; }}
  h2 {{ font-size: 14px; margin: 24px 0 8px; text-transform: uppercase;
       letter-spacing: .08em; color: #e82b23; border-bottom: 1px solid #f0e0db;
       padding-bottom: 4px; }}
  h3 {{ font-size: 13px; margin: 14px 0 6px; color: #2a2a3a; }}
  p {{ margin: 6px 0; }}
  ul {{ margin: 4px 0 8px 18px; }}
  li {{ margin: 3px 0; }}
  .meta {{ color: #6a6a80; font-size: 11px; }}
  .hero {{ background: #fef5f2; border: 1px solid #f6d8cf; padding: 14px 16px;
          border-radius: 8px; margin: 12px 0 18px; }}
  .hero .state {{ font-size: 13.5px; color: #1a1a24; margin: 0 0 8px; }}
  .pill {{ display: inline-block; padding: 2px 10px; border-radius: 12px;
          font-size: 11px; background: #efe9db; color: #6a4a2c; margin-right: 4px; }}
  .pill.red {{ background: #fde2e2; color: #8b1f1f; }}
  .pill.amber {{ background: #fff3d1; color: #876300; }}
  .pill.green {{ background: #dff5e2; color: #1f6e2c; }}
  .pill.qualified {{ background: #dff5e2; color: #1f6e2c; }}
  .pill.borderline {{ background: #fff3d1; color: #876300; }}
  .pill.disqualified {{ background: #fde2e2; color: #8b1f1f; }}
  .bant {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px;
          margin: 8px 0 14px; }}
  .bant-tile {{ border: 1px solid #e1e1e8; border-radius: 6px; padding: 8px 10px;
               background: #fafafc; min-height: 56px; }}
  .bant-tile.red {{ border-color: #f3c8c8; background: #fff5f5; }}
  .bant-tile.amber {{ border-color: #f5e1a8; background: #fffbe8; }}
  .bant-tile.green {{ border-color: #b8e1c3; background: #f3faf4; }}
  .bant-tile .label {{ font-size: 10px; text-transform: uppercase;
                      letter-spacing: .07em; font-weight: 600; color: #6a6a80; }}
  .bant-tile.red .label {{ color: #8b1f1f; }}
  .bant-tile.amber .label {{ color: #876300; }}
  .bant-tile.green .label {{ color: #1f6e2c; }}
  .bant-tile .caption {{ font-size: 12px; color: #1a1a24; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 12px; }}
  th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #ececf2; }}
  th {{ font-size: 10px; text-transform: uppercase; letter-spacing: .06em;
       color: #6a6a80; background: #fafafc; }}
  .totals {{ background: #fafafc; border: 1px solid #e1e1e8;
            padding: 12px 16px; margin: 10px 0; border-radius: 6px; }}
  .totals .row {{ display: flex; justify-content: space-between; padding: 3px 0; }}
  .totals .row.grand {{ font-weight: 700; border-top: 1px solid #d8d8e0;
                       margin-top: 6px; padding-top: 8px; font-size: 14px; }}
  .stream {{ background: #fafafc; border: 1px solid #e1e1e8; border-radius: 6px;
             padding: 10px 12px; margin-bottom: 10px; }}
  .stream-head {{ font-size: 13px; font-weight: 600; color: #1a1a24;
                  text-transform: capitalize; }}
  .toolbar {{
    position: sticky; top: 0; z-index: 50;
    background: #2a2a3a; color: #fff; padding: 10px 16px;
    display: flex; justify-content: space-between; align-items: center;
  }}
  .toolbar button {{
    background: #e82b23; color: #fff; border: 0; padding: 6px 14px;
    border-radius: 6px; font-size: 13px; cursor: pointer; margin-left: 8px;
  }}
  .toolbar .meta {{ color: #c9c9d4; font-size: 11px; }}
  @media print {{
    .toolbar {{ display: none; }}
    body {{ background: #ffffff; }}
    .page {{ box-shadow: none; border: 0; margin: 0; padding: 0; }}
  }}
</style>
</head>
<body>
<div class="toolbar">
  <div>Project Briefing · {title}<span class="meta"> · generated {generated_at}</span></div>
  <div><button onclick="window.print()" type="button">⤓ Print / Save as PDF</button></div>
</div>
<article class="page">
"""

_HTML_FOOT = """
</article>
</body>
</html>
"""


def render_html(snapshot: dict[str, Any]) -> str:
    """Render the full project briefing as a single HTML document.

    snapshot shape (assembled by server._gather_project_preview_snapshot):
      {
        "company_name": str,
        "generated_at": str (ISO),
        "lead": { id, company, url, region, vertical, icp_normalised,
                  status, sales_stage, owner, opportunity_type },
        "summary": {state_of_play, key_facts, open_questions,
                    next_action, risks, generated_at} | None,
        "bant_health": {budget, authority, need, timeline, scope},
        "scope": {
          "project_types": [str],
          "streams": [{project_type, criteria: [{key, label, value, health}], ...}],
        } | None,
        "pricing": {
          "currency", "rate_card", "months", "totals": {gross, net, ...},
          "phase_breakdown": [{phase, months, gross, net}],
          "team_breakdown": [{role, fte, gross, net}],
        } | None,
        "roadmap": {
          "start_date", "end_date", "milestones": [{name, phase, workstream, start_month, length_months}],
          "extended_items": [{title, ...}],
        } | None,
      }
    """
    title = snapshot.get("company_name") or snapshot.get("lead", {}).get("company") or "Untitled project"
    generated_at = snapshot.get("generated_at") or ""
    parts: list[str] = [_HTML_HEAD.format(
        title=escape(title), generated_at=escape(generated_at),
    )]

    lead = snapshot.get("lead") or {}
    parts.append(f"<h1>{escape(title)}</h1>")
    meta_bits = []
    if lead.get("url"): meta_bits.append(escape(lead["url"]))
    if lead.get("region"): meta_bits.append(escape(lead["region"]))
    if lead.get("vertical"): meta_bits.append(escape(lead["vertical"]))
    if meta_bits:
        parts.append(f'<p class="meta">{" · ".join(meta_bits)}</p>')

    # Status pills row
    status_pills = []
    status = (lead.get("status") or "").lower()
    if status:
        cls = "qualified" if "qualif" in status and "out" not in status and "dis" not in status else (
              "borderline" if "border" in status or "research" in status else "disqualified")
        status_pills.append(f'<span class="pill {cls}">{escape(lead["status"])}</span>')
    if lead.get("sales_stage"):
        status_pills.append(f'<span class="pill">Stage: {escape(lead["sales_stage"])}</span>')
    if lead.get("opportunity_type"):
        status_pills.append(f'<span class="pill">{escape(lead["opportunity_type"])}</span>')
    if lead.get("icp_normalised") is not None:
        status_pills.append(f'<span class="pill">ICP {lead["icp_normalised"]}/10</span>')
    if lead.get("owner"):
        status_pills.append(f'<span class="pill">Owner: {escape(lead["owner"])}</span>')
    if status_pills:
        parts.append('<p>' + ' '.join(status_pills) + '</p>')

    # Lead Summary (hero)
    summary = snapshot.get("summary") or {}
    if summary.get("state_of_play"):
        parts.append('<div class="hero">')
        parts.append(f'<p class="state">{escape(summary["state_of_play"])}</p>')
        if summary.get("next_action"):
            parts.append(f'<p><strong>Next action:</strong> {escape(summary["next_action"])}</p>')
        parts.append('</div>')

    # BANT-S Health
    bant = snapshot.get("bant_health") or {}
    if bant:
        parts.append("<h2>BANT-S Health</h2>")
        parts.append('<div class="bant">')
        for key, label in (("budget", "Budget"), ("authority", "Authority"),
                           ("need", "Need"), ("timeline", "Timeline"),
                           ("scope", "Scope")):
            t = bant.get(key) or {}
            health = t.get("health") or ""
            caption = escape(t.get("caption") or "Not assessed")
            parts.append(
                f'<div class="bant-tile {health}">'
                f'<div class="label">{label}</div>'
                f'<div class="caption">{caption}</div>'
                f'</div>'
            )
        parts.append('</div>')

    # Key facts + open questions + risks from summary
    if summary.get("key_facts"):
        parts.append("<h3>Key facts</h3><ul>")
        for f in summary["key_facts"]:
            parts.append(f"<li>{escape(f)}</li>")
        parts.append("</ul>")
    if summary.get("open_questions"):
        parts.append("<h3>Open questions</h3><ul>")
        for q in summary["open_questions"]:
            parts.append(f"<li>{escape(q)}</li>")
        parts.append("</ul>")
    if summary.get("risks"):
        parts.append("<h3>Risks</h3><ul>")
        for r in summary["risks"]:
            parts.append(f'<li style="color:#8b1f1f;">{escape(r)}</li>')
        parts.append("</ul>")

    # Scope
    scope = snapshot.get("scope")
    if scope and scope.get("streams"):
        parts.append("<h2>Scope</h2>")
        types = scope.get("project_types") or []
        if types:
            parts.append(f'<p class="meta">Streams: {", ".join(escape(t) for t in types)}</p>')
        for s in scope["streams"]:
            parts.append('<div class="stream">')
            parts.append(f'<div class="stream-head">{escape(str(s.get("project_type", "")).replace("_", " "))}</div>')
            crits = [c for c in (s.get("criteria") or []) if c.get("value")]
            if crits:
                parts.append('<table><thead><tr><th>Criterion</th><th>Value</th><th>Health</th></tr></thead><tbody>')
                for c in crits:
                    h = c.get("health") or ""
                    h_pill = f'<span class="pill {h}">{h}</span>' if h else ""
                    parts.append(
                        f'<tr><td>{escape(c.get("label") or c.get("key") or "")}</td>'
                        f'<td>{escape(str(c.get("value") or ""))}</td>'
                        f'<td>{h_pill}</td></tr>'
                    )
                parts.append('</tbody></table>')
            else:
                parts.append('<p class="meta">No criteria filled yet.</p>')
            parts.append('</div>')

    # Pricing
    pricing = snapshot.get("pricing")
    if pricing and pricing.get("totals"):
        parts.append("<h2>Pricing snapshot</h2>")
        ccy = pricing.get("currency") or "USD"
        sym = {"USD": "$", "GBP": "£", "EUR": "€"}.get(ccy.upper(), ccy + " ")
        totals = pricing.get("totals") or {}
        rate_card = pricing.get("rate_card") or "MR Default"
        months = pricing.get("months") or ""
        parts.append(f'<p class="meta">{escape(rate_card)} · {months} months · {escape(ccy)}</p>')
        parts.append('<div class="totals">')
        def _fmt(n: Any) -> str:
            try: return f"{sym}{round(float(n)):,}"
            except: return "—"
        if totals.get("gross") is not None:
            parts.append(f'<div class="row"><span>Gross</span><span>{_fmt(totals.get("gross"))}</span></div>')
        if totals.get("discount") is not None and totals.get("discount"):
            parts.append(f'<div class="row"><span>Discount</span><span>−{_fmt(totals.get("discount"))}</span></div>')
        if totals.get("net") is not None:
            parts.append(f'<div class="row grand"><span>Net</span><span>{_fmt(totals.get("net"))}</span></div>')
        parts.append('</div>')

        phases = pricing.get("phase_breakdown") or []
        if phases:
            parts.append("<h3>By phase</h3>")
            parts.append('<table><thead><tr><th>Phase</th><th>Months</th><th>Gross</th><th>Net</th></tr></thead><tbody>')
            for p in phases:
                parts.append(
                    f'<tr><td>{escape(p.get("phase") or "")}</td>'
                    f'<td>{p.get("months", "")}</td>'
                    f'<td>{_fmt(p.get("gross"))}</td>'
                    f'<td>{_fmt(p.get("net"))}</td></tr>'
                )
            parts.append('</tbody></table>')

        team = pricing.get("team_breakdown") or []
        if team:
            parts.append("<h3>By role</h3>")
            parts.append('<table><thead><tr><th>Role</th><th>FTE</th><th>Gross</th><th>Net</th></tr></thead><tbody>')
            for t in team:
                parts.append(
                    f'<tr><td>{escape(t.get("role") or "")}</td>'
                    f'<td>{t.get("fte", "")}</td>'
                    f'<td>{_fmt(t.get("gross"))}</td>'
                    f'<td>{_fmt(t.get("net"))}</td></tr>'
                )
            parts.append('</tbody></table>')

    # Roadmap
    roadmap = snapshot.get("roadmap")
    if roadmap and roadmap.get("milestones"):
        parts.append("<h2>Roadmap</h2>")
        date_meta = []
        if roadmap.get("start_date"): date_meta.append(f"Start: {escape(roadmap['start_date'])}")
        if roadmap.get("end_date"): date_meta.append(f"End: {escape(roadmap['end_date'])}")
        if date_meta:
            parts.append(f'<p class="meta">{" · ".join(date_meta)}</p>')
        parts.append('<table><thead><tr><th>Milestone</th><th>Phase</th><th>Workstream</th><th>Month</th><th>Length</th></tr></thead><tbody>')
        for m in roadmap["milestones"]:
            parts.append(
                f'<tr><td>{escape(m.get("name") or "")}</td>'
                f'<td>{escape(m.get("phase") or "")}</td>'
                f'<td>{escape(m.get("workstream") or "")}</td>'
                f'<td>{m.get("start_month", "")}</td>'
                f'<td>{m.get("length_months", "")} mo</td></tr>'
            )
        parts.append('</tbody></table>')

        ext = roadmap.get("extended_items") or []
        if ext:
            parts.append("<h3>Extended engagement opportunities</h3><ul>")
            for e in ext:
                title = e.get("title") or ""
                desc = e.get("description") or e.get("rationale") or ""
                if desc:
                    parts.append(f'<li><strong>{escape(title)}</strong> — {escape(desc)}</li>')
                else:
                    parts.append(f'<li>{escape(title)}</li>')
            parts.append('</ul>')

    parts.append(_HTML_FOOT)
    return "".join(parts)
