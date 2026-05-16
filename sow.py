"""
Statement of Work renderer.

Snapshot-based, button-triggered. The AE clicks "Draft SOW" in Project
Build → this module reads the *current* Apollo + scope + pricing state,
freezes it into a versioned snapshot, and emits a print-friendly HTML
page the AE can review + download as PDF (via browser print).

A snapshot does NOT update when scope or pricing change afterward. Each
version is immutable. Re-clicking Draft SOW creates a new version.

Public surface:
    build_snapshot(lead_id)              -> dict   (Python-side data)
    render_html(snapshot, version)       -> str    (printable HTML page)
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any

import pricing
import project_store
import scope as scope_module

ASSUMPTIONS_BOILERPLATE = [
    "Pricing assumes a standard team allocation for the project shape described above; "
    "any change in volume, channel mix, or scope post-signature triggers a Change Order.",
    "Hours quoted are based on an availability window of 9.00–18.00 UK time, "
    "Monday to Friday, excluding UK bank holidays.",
    "Client agrees to make a named project owner available for weekly steering reviews.",
    "Third-party licence fees (Braze, Hightouch, Snowflake, etc.) are billed to the "
    "Client directly and are not included in this Statement of Work.",
    "All deliverables and source materials produced under this SOW transfer to the "
    "Client on full payment of fees.",
]

OUT_OF_SCOPE_BOILERPLATE = [
    "Hardware procurement, infrastructure hosting fees, and third-party tooling licences.",
    "Translation or localisation work beyond the languages agreed at kick-off.",
    "On-site presence outside the kick-off and quarterly review days.",
    "Support, maintenance, or new feature delivery after the Acceptance Date "
    "(covered separately by a managed services agreement).",
]


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def _safe_load_apollo(lead_id: str) -> dict[str, Any]:
    """Best-effort: SOW should still render if Apollo cache is empty."""
    try:
        import apollo
        org = apollo.enrich_organization(lead_id)
        return org or {}
    except Exception:
        return {}


def _executive_summary(project, apollo_org: dict, quote: dict) -> str:
    name = project.company_name
    streams = [scope_module.PROJECT_TYPES.get(s.project_type, {}).get("label", s.project_type)
               for s in project.streams]
    streams_str = ", ".join(streams[:-1]) + (" and " + streams[-1] if len(streams) > 1 else streams[0]) if streams else ""
    industry = apollo_org.get("industry") or "consumer marketing"
    total = quote["totals"]["net_usd"]
    months = quote["inputs"]["months"]
    return (
        f"Massive Rocket will deliver a {streams_str.lower()} engagement for {name}, "
        f"an industry leader in {industry.lower()}. The engagement runs across {months} months, "
        f"split into Understand, Execute, and Accelerate phases, for a total investment of "
        f"${total:,.0f}. Day one focus is establishing the data foundation and stakeholder "
        f"rhythm needed to compound value across the full lifecycle programme."
    )


def _engagement_overview(project, apollo_org: dict) -> dict[str, Any]:
    return {
        "background": apollo_org.get("short_description") or "",
        "industry": apollo_org.get("industry") or "",
        "region": apollo_org.get("region") or "",
        "estimated_employees": apollo_org.get("estimated_num_employees"),
        "annual_revenue": apollo_org.get("annual_revenue_printed"),
        "stream_labels": [
            {
                "key": s.project_type,
                "label": scope_module.PROJECT_TYPES.get(s.project_type, {}).get("label", s.project_type),
                "description": scope_module.PROJECT_TYPES.get(s.project_type, {}).get("description", ""),
            }
            for s in project.streams
        ],
    }


def _scope_of_work(project) -> list[dict[str, Any]]:
    """For each stream, list the criteria the AE marked Qualifying or Qualified.
    Unqualified items are omitted (we shouldn't promise what we haven't confirmed)."""
    out = []
    library = {pt: {c["key"]: c for c in criteria}
               for pt, criteria in scope_module.criteria_library().items()}
    for stream in project.streams:
        spec_lib = library.get(stream.project_type, {})
        in_scope_lines: list[dict[str, str]] = []
        open_questions: list[dict[str, str]] = []
        for ans in stream.criteria:
            crit_def = spec_lib.get(ans.key)
            label = crit_def["label"] if crit_def else ans.key
            entry = {"label": label, "value": (ans.value or "").strip()}
            if ans.status == "qualified":
                entry["confirmed"] = True
                in_scope_lines.append(entry)
            elif ans.status == "qualifying":
                entry["confirmed"] = False
                in_scope_lines.append(entry)
            elif (ans.value or "").strip():
                # Has a value but still unqualified — capture as open question
                open_questions.append(entry)
        out.append({
            "project_type": stream.project_type,
            "label": scope_module.PROJECT_TYPES.get(stream.project_type, {}).get("label", stream.project_type),
            "in_scope": in_scope_lines,
            "open_questions": open_questions,
        })
    return out


def _team_and_phases(quote: dict) -> dict[str, Any]:
    """Surface the role x phase FTE matrix for the SOW Team section."""
    return {
        "team_fte": quote["team"],          # {role: {phase: fte}}
        "hours_total": quote["totals"]["hours"],
        "phases": list(pricing.PHASES),
        "phase_months": quote["inputs"]["phase_months"],
    }


def _investment_summary(quote: dict) -> dict[str, Any]:
    return {
        "currency": quote["inputs"]["currency"],
        "months": quote["inputs"]["months"],
        "totals": quote["totals"],
        "monthly": quote["monthly"],
    }


def build_snapshot(lead_id: str, *, months: int = 12,
                   discount_first_half: float = 0.15,
                   discount_second_half: float = 0.0) -> dict[str, Any]:
    """Freeze the current state into a SOW snapshot dict.

    Raises ValueError if there's no project on file for the lead.
    """
    project = project_store.load(lead_id)
    if project is None:
        raise ValueError(f"No project found for lead_id={lead_id!r}")

    apollo_org = _safe_load_apollo(lead_id)

    multipliers = scope_module.role_drivers_for_project(project)
    quote = pricing.compute_quote(pricing.QuoteInputs(
        project_types=[s.project_type for s in project.streams],
        months=months,
        discount_pct_first_half=discount_first_half,
        discount_pct_second_half=discount_second_half,
        effort_multipliers=multipliers,
    ))

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "lead_id": lead_id,
        "company_name": project.company_name,
        "validation_status_at_generation": project.validation_status,
        "validation_notes_at_generation": project.validation_notes,
        "summary": scope_module.project_summary(project),
        "sections": {
            "executive_summary": _executive_summary(project, apollo_org, quote),
            "engagement_overview": _engagement_overview(project, apollo_org),
            "scope_of_work": _scope_of_work(project),
            "team_and_phases": _team_and_phases(quote),
            "investment": _investment_summary(quote),
            "assumptions": list(ASSUMPTIONS_BOILERPLATE),
            "out_of_scope": list(OUT_OF_SCOPE_BOILERPLATE),
        },
    }
    return snapshot


# ---------------------------------------------------------------------------
# HTML renderer
# ---------------------------------------------------------------------------

_HTML_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>SOW · {title}</title>
<style>
  @page {{ size: A4; margin: 18mm 16mm; }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: Georgia, "Times New Roman", serif;
    color: #1a1a24; background: #f6f6f0; margin: 0;
    line-height: 1.5;
  }}
  .page {{
    max-width: 800px; margin: 24px auto; padding: 36px 44px;
    background: #ffffff; border: 1px solid #d8d4c8;
    box-shadow: 0 10px 30px rgba(0,0,0,.08);
  }}
  h1 {{ font-size: 28px; margin: 0 0 4px; letter-spacing: .01em; }}
  h2 {{ font-size: 16px; margin: 28px 0 8px; text-transform: uppercase;
       letter-spacing: .08em; color: #6a4a2c; border-bottom: 1px solid #e3decf;
       padding-bottom: 4px; }}
  h3 {{ font-size: 14px; margin: 18px 0 6px; color: #2a2a3a; }}
  p {{ margin: 6px 0; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 12px; }}
  th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #e6e2d5; }}
  th {{ font-size: 10px; text-transform: uppercase; letter-spacing: .06em;
       color: #6a4a2c; }}
  ul {{ margin: 6px 0 8px 18px; }}
  li {{ margin: 3px 0; }}
  .meta {{ color: #6a6a80; font-size: 11px; }}
  .pill {{ display: inline-block; padding: 1px 8px; border-radius: 12px;
          font-size: 10px; background: #efe9db; color: #6a4a2c; margin-left: 6px; }}
  .pill.qualifying {{ background: #fff3d1; color: #876300; }}
  .pill.warn {{ background: #fde2e2; color: #8b1f1f; }}
  .totals {{ background: #faf6ec; border: 1px solid #e3decf; padding: 12px 16px; margin: 12px 0; }}
  .totals .row {{ display: flex; justify-content: space-between; padding: 3px 0; }}
  .totals .row.grand {{ font-weight: 700; border-top: 1px solid #d8d4c8;
                       margin-top: 6px; padding-top: 8px; font-size: 15px; }}
  .signatures {{ display: grid; grid-template-columns: 1fr 1fr; gap: 32px; margin-top: 36px; }}
  .sigblock {{ border-top: 1px solid #1a1a24; padding-top: 6px; font-size: 11px; }}
  .toolbar {{
    position: sticky; top: 0; z-index: 50;
    background: #2a2a3a; color: #fff; padding: 10px 16px;
    display: flex; justify-content: space-between; align-items: center;
  }}
  .toolbar a, .toolbar button {{
    background: #ff4d2a; color: #fff; border: 0; padding: 6px 14px;
    border-radius: 6px; font-size: 13px; cursor: pointer; text-decoration: none;
    margin-left: 8px;
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
  <div>Statement of Work · v{version}<span class="meta"> · generated {generated_at}</span></div>
  <div>
    <button onclick="window.print()" type="button">⤓ Print / Save as PDF</button>
  </div>
</div>
<article class="page">
"""

_HTML_FOOT = """
</article>
</body>
</html>
"""


def _render_table(rows: list[dict[str, Any]], cols: list[tuple[str, str]]) -> str:
    head = "".join(f"<th>{escape(label)}</th>" for _, label in cols)
    body = []
    for r in rows:
        body.append("<tr>" + "".join(
            f"<td>{escape(str(r.get(key, '')))}</td>" for key, _ in cols
        ) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def render_html(snapshot: dict[str, Any], version: int) -> str:
    sections = snapshot["sections"]
    inv = sections["investment"]
    t = inv["totals"]
    team_section = sections["team_and_phases"]

    head = _HTML_HEAD.format(
        title=escape(snapshot["company_name"]),
        version=version,
        generated_at=escape(snapshot["generated_at"]),
    )

    parts: list[str] = [head]

    parts.append(f"""
      <h1>Statement of Work</h1>
      <p class="meta">Massive Rocket &nbsp;·&nbsp; {escape(snapshot["company_name"])} &nbsp;·&nbsp; v{version} &nbsp;·&nbsp; {escape(snapshot["generated_at"])}</p>
    """)

    # Validation warning if scope wasn't validated
    if snapshot.get("validation_status_at_generation") != "validated":
        status_text = snapshot.get("validation_status_at_generation", "unknown")
        parts.append(f"""
          <p><span class="pill warn">Internal review</span>
          This SOW was drafted while scope was in <b>{escape(status_text)}</b>.
          Confirm with delivery before sending externally.</p>
        """)

    # Executive Summary
    parts.append("<h2>Executive Summary</h2>")
    parts.append(f"<p>{escape(sections['executive_summary'])}</p>")

    # Engagement Overview
    overview = sections["engagement_overview"]
    parts.append("<h2>Engagement Overview</h2>")
    if overview.get("background"):
        parts.append(f"<p>{escape(overview['background'])}</p>")
    overview_rows = []
    if overview.get("industry"): overview_rows.append(("Industry", overview["industry"]))
    if overview.get("region"): overview_rows.append(("Region", overview["region"]))
    if overview.get("annual_revenue"): overview_rows.append(("Annual revenue", overview["annual_revenue"]))
    if overview.get("estimated_employees"):
        overview_rows.append(("Estimated employees", f"{overview['estimated_employees']:,}"))
    if overview_rows:
        parts.append("<table>")
        for label, val in overview_rows:
            parts.append(f"<tr><th style='width:35%'>{escape(label)}</th><td>{escape(str(val))}</td></tr>")
        parts.append("</table>")

    parts.append("<h3>Streams in scope</h3><ul>")
    for s in overview["stream_labels"]:
        parts.append(f"<li><b>{escape(s['label'])}</b> — {escape(s['description'])}</li>")
    parts.append("</ul>")

    # Scope of Work
    parts.append("<h2>Scope of Work</h2>")
    for stream in sections["scope_of_work"]:
        parts.append(f"<h3>{escape(stream['label'])}</h3>")
        if not stream["in_scope"]:
            parts.append("<p class='meta'>No qualified or qualifying criteria captured yet for this stream.</p>")
        else:
            parts.append("<ul>")
            for item in stream["in_scope"]:
                pill = "" if item.get("confirmed") else " <span class='pill qualifying'>qualifying</span>"
                value = f" — {escape(item['value'])}" if item.get("value") else ""
                parts.append(f"<li><b>{escape(item['label'])}</b>{value}{pill}</li>")
            parts.append("</ul>")
        if stream.get("open_questions"):
            parts.append("<p class='meta'>Open questions for the next discovery call:</p><ul>")
            for q in stream["open_questions"]:
                value = f" — {escape(q['value'])}" if q.get("value") else ""
                parts.append(f"<li class='meta'>{escape(q['label'])}{value}</li>")
            parts.append("</ul>")

    # Team & Phases
    parts.append("<h2>Team &amp; Phases</h2>")
    pm = team_section["phase_months"]
    parts.append(
        f"<p>The engagement runs across "
        f"{pm.get('Understand', 0)} Understand months, "
        f"{pm.get('Execute', 0)} Execute months, and "
        f"{pm.get('Accelerate', 0)} Accelerate months, with total effort of "
        f"{team_section['hours_total']:,.0f} hours.</p>"
    )
    parts.append("<table><thead><tr><th>Role</th><th>Understand FTE</th><th>Execute FTE</th><th>Accelerate FTE</th></tr></thead><tbody>")
    for role, by_phase in team_section["team_fte"].items():
        parts.append(
            f"<tr><td>{escape(role)}</td>"
            f"<td>{by_phase.get('Understand', 0):.2f}</td>"
            f"<td>{by_phase.get('Execute', 0):.2f}</td>"
            f"<td>{by_phase.get('Accelerate', 0):.2f}</td></tr>"
        )
    parts.append("</tbody></table>")

    # Investment
    parts.append("<h2>Investment</h2>")
    parts.append(f"""
      <div class="totals">
        <div class="row"><span>Gross fees</span><span>${t['gross_usd']:,.0f} {inv['currency']}</span></div>
        <div class="row"><span>Discount</span><span>−${t['discount_usd']:,.0f}</span></div>
        <div class="row grand"><span>Total investment (net)</span><span>${t['net_usd']:,.0f} {inv['currency']}</span></div>
        <div class="row meta"><span>Total hours</span><span>{t['hours']:,.0f} · blended ${t['blended_rate_usd_per_hour']}/h</span></div>
      </div>
    """)
    parts.append("<h3>Monthly schedule</h3>")
    parts.append("<table><thead><tr><th>Month</th><th>Phase</th><th>Gross</th><th>Discount</th><th>Net</th></tr></thead><tbody>")
    for m in inv["monthly"]:
        parts.append(
            f"<tr><td>M{m['month']}</td><td>{escape(m['phase'])}</td>"
            f"<td>${m['gross_usd']:,.0f}</td>"
            f"<td>${m['discount_usd']:,.0f}</td>"
            f"<td>${m['net_usd']:,.0f}</td></tr>"
        )
    parts.append("</tbody></table>")

    # Assumptions + Out of Scope
    parts.append("<h2>Assumptions</h2><ul>")
    for a in sections["assumptions"]: parts.append(f"<li>{escape(a)}</li>")
    parts.append("</ul>")

    parts.append("<h2>Out of Scope</h2><ul>")
    for o in sections["out_of_scope"]: parts.append(f"<li>{escape(o)}</li>")
    parts.append("</ul>")

    # Signatures
    parts.append("""
      <h2>Term &amp; Acceptance</h2>
      <p>This Statement of Work is governed by the parties' existing Master Services Agreement
      (or if none exists, by Massive Rocket's standard terms attached as Annex A). Work begins
      on the Acceptance Date below and continues until completion of the deliverables or
      termination in accordance with the MSA.</p>
      <div class="signatures">
        <div class="sigblock">
          <div>For Massive Rocket</div>
          <div class="meta">Name · Title · Date</div>
        </div>
        <div class="sigblock">
          <div>For {client}</div>
          <div class="meta">Name · Title · Date</div>
        </div>
      </div>
    """.replace("{client}", escape(snapshot["company_name"])))

    parts.append(_HTML_FOOT)
    return "".join(parts)
