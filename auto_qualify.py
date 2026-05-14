#!/usr/bin/env python3
"""
Massive Rocket Auto Lead Qualification
=======================================

Automatically researches a company by URL and qualifies against ICP.

Usage:
    python auto_qualify.py "Company Name" "company-url.com"
    python auto_qualify.py "Chipotle" "chipotle.com" --output json
    python auto_qualify.py "Marriott" "marriott.com" --output html
"""

import argparse
import json
import re
import sys
import os
import time
import html as html_lib
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
from urllib.parse import urlparse, urljoin, quote_plus

# Add parent directory for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Required packages not installed. Run:")
    print("  pip install requests beautifulsoup4")
    sys.exit(1)

from config import (
    ICP_CRITERIA, THRESHOLDS, POSITIVE_SIGNALS,
    QUALIFICATION_STATUS, TECH_KEYWORDS, VERTICAL_KEYWORDS
)
from scoring import (
    calculate_icp_score, check_hard_disqualifiers,
    identify_positive_signals, generate_score_summary
)
from research import (
    CompanyData, detect_tech_stack_from_text, detect_complexity_from_text,
    detect_region_from_text, identify_vertical_from_text,
    parse_revenue_from_text, parse_employee_count_from_text
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
TIMEOUT = 15


# ═══════════════════════════════════════════════
# WEB SCRAPING
# ═══════════════════════════════════════════════

def fetch_page(url: str) -> Optional[str]:
    """Fetch a web page and return text content."""
    try:
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  ⚠ Could not fetch {url}: {e}")
        return None


def extract_text_from_html(html_content: str) -> str:
    """Extract clean text from HTML."""
    soup = BeautifulSoup(html_content, 'html.parser')
    # Remove scripts, styles, navs, footers
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "iframe"]):
        tag.decompose()
    text = soup.get_text(separator=' ', strip=True)
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text)
    return text[:50000]  # Limit to 50k chars


def extract_meta_info(html_content: str) -> Dict[str, str]:
    """Extract meta tags and structured data from HTML."""
    soup = BeautifulSoup(html_content, 'html.parser')
    meta = {}

    # Meta description
    desc_tag = soup.find('meta', attrs={'name': 'description'})
    if desc_tag:
        meta['description'] = desc_tag.get('content', '')

    # OG tags
    for og in soup.find_all('meta', attrs={'property': re.compile(r'^og:')}):
        key = og.get('property', '').replace('og:', '')
        meta[f'og_{key}'] = og.get('content', '')

    # Title
    title = soup.find('title')
    if title:
        meta['title'] = title.text.strip()

    # JSON-LD structured data
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict):
                if data.get('@type') == 'Organization':
                    meta['org_name'] = data.get('name', '')
                    meta['org_description'] = data.get('description', '')
                    if 'numberOfEmployees' in data:
                        emp = data['numberOfEmployees']
                        if isinstance(emp, dict):
                            meta['employees_structured'] = str(emp.get('value', emp.get('minValue', '')))
                        else:
                            meta['employees_structured'] = str(emp)
        except:
            pass

    return meta


def search_duckduckgo(query: str) -> List[Dict[str, str]]:
    """Search DuckDuckGo HTML and return results."""
    results = []
    try:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        soup = BeautifulSoup(resp.text, 'html.parser')

        for result in soup.select('.result'):
            title_el = result.select_one('.result__title')
            snippet_el = result.select_one('.result__snippet')
            link_el = result.select_one('.result__url')

            title = title_el.get_text(strip=True) if title_el else ''
            snippet = snippet_el.get_text(strip=True) if snippet_el else ''
            link = link_el.get_text(strip=True) if link_el else ''

            if title or snippet:
                results.append({
                    'title': title,
                    'snippet': snippet,
                    'url': link
                })

        return results[:10]
    except Exception as e:
        print(f"  ⚠ Search failed for '{query}': {e}")
        return []


def search_and_extract(query: str) -> str:
    """Search and return combined text from results."""
    results = search_duckduckgo(query)
    texts = []
    for r in results:
        texts.append(f"{r['title']}. {r['snippet']}")
    return " ".join(texts)


# ═══════════════════════════════════════════════
# TECH STACK DETECTION
# ═══════════════════════════════════════════════

def detect_tech_from_website(html_content: str) -> List[str]:
    """Detect tech stack from website HTML source code."""
    tech_found = []
    html_lower = html_content.lower()

    # Check for known marketing/data platform scripts and tags
    tech_signatures = {
        "Braze": ["braze.com", "sdk.iad-01.braze", "appboy", "braze-web-sdk"],
        "Snowflake": ["snowflake", "snowflakecomputing"],
        "Segment": ["cdn.segment.com", "analytics.js", "segment.io"],
        "Amplitude": ["cdn.amplitude.com", "amplitude.com"],
        "Mixpanel": ["cdn.mxpnl.com", "mixpanel.com"],
        "Salesforce": ["salesforce.com", "sfmc", "marketing cloud", "exacttarget"],
        "Adobe": ["adobedtm", "adobe.com/experience", "omniture", "demdex"],
        "Google Analytics": ["google-analytics.com", "gtag", "googletagmanager"],
        "HubSpot": ["hubspot.com", "hs-scripts", "hbspt"],
        "Iterable": ["iterable.com"],
        "Klaviyo": ["klaviyo.com"],
        "mParticle": ["mparticle.com"],
        "Hightouch": ["hightouch.io", "hightouch.com"],
        "Customer.io": ["customer.io"],
        "Optimizely": ["optimizely.com"],
        "LaunchDarkly": ["launchdarkly.com"],
        "Contentful": ["contentful.com"],
        "OneTrust": ["onetrust.com"],
    }

    for tech, signatures in tech_signatures.items():
        for sig in signatures:
            if sig in html_lower:
                tech_found.append(tech)
                break

    return list(set(tech_found))


# ═══════════════════════════════════════════════
# RESEARCH ENGINE
# ═══════════════════════════════════════════════

def research_company(company_name: str, url: str) -> Dict[str, Any]:
    """
    Research a company using website scraping and web search.

    Returns a dict with all discovered company data.
    """
    print(f"\n{'='*60}")
    print(f"🔍 RESEARCHING: {company_name}")
    print(f"   URL: {url}")
    print(f"{'='*60}\n")

    data = {
        "name": company_name,
        "url": url,
        "revenue": "",
        "employees": "",
        "vertical": "",
        "tech_stack": "",
        "complexity": "",
        "region": "",
        "description": "",
        "sources": [],
        "raw_data": {}
    }

    all_text = ""

    # ─── Step 1: Scrape company website ───
    print("📡 Step 1: Scraping company website...")
    site_html = fetch_page(url)
    if site_html:
        site_text = extract_text_from_html(site_html)
        meta = extract_meta_info(site_html)
        all_text += f" {site_text}"
        data["sources"].append(f"Company website ({url})")
        data["raw_data"]["website_meta"] = meta

        # Tech detection from HTML source
        site_tech = detect_tech_from_website(site_html)
        if site_tech:
            print(f"  ✓ Tech detected from site: {', '.join(site_tech)}")
            data["raw_data"]["site_tech"] = site_tech

        if meta.get("description"):
            data["description"] = meta["description"]
            print(f"  ✓ Description: {meta['description'][:80]}...")

        if meta.get("employees_structured"):
            data["employees"] = meta["employees_structured"]
            print(f"  ✓ Employees (structured data): {data['employees']}")

    # Also try /about page
    print("  → Checking /about page...")
    about_html = fetch_page(f"{url}/about") or fetch_page(f"{url}/about-us")
    if about_html:
        about_text = extract_text_from_html(about_html)
        all_text += f" {about_text}"
        data["sources"].append(f"About page ({url}/about)")

    # ─── Step 2: Search for revenue ───
    print("\n💰 Step 2: Searching for revenue data...")
    rev_text = search_and_extract(f"{company_name} annual revenue 2024 2025")
    if rev_text:
        all_text += f" {rev_text}"
        data["sources"].append("Web search (revenue)")
        found_rev = parse_revenue_from_text(rev_text)
        if found_rev:
            data["revenue"] = found_rev
            print(f"  ✓ Revenue found: {found_rev}")
        else:
            print("  ⚠ Revenue not found in search results")

    # ─── Step 3: Search for employee count ───
    print("\n👥 Step 3: Searching for employee count...")
    if not data["employees"]:
        emp_text = search_and_extract(f"{company_name} number of employees company size 2024")
        if emp_text:
            all_text += f" {emp_text}"
            data["sources"].append("Web search (employees)")
            found_emp = parse_employee_count_from_text(emp_text)
            if found_emp:
                data["employees"] = found_emp
                print(f"  ✓ Employees found: {found_emp}")
            else:
                print("  ⚠ Employee count not found")

    # ─── Step 4: Search for tech stack ───
    print("\n🔧 Step 4: Searching for technology stack...")
    tech_text = search_and_extract(f"{company_name} technology stack marketing Braze Snowflake CRM platform")
    if tech_text:
        all_text += f" {tech_text}"
        data["sources"].append("Web search (tech stack)")

    # Combine all tech findings
    all_tech = set()
    if data["raw_data"].get("site_tech"):
        all_tech.update(data["raw_data"]["site_tech"])
    search_tech = detect_tech_stack_from_text(all_text)
    all_tech.update(search_tech)

    if all_tech:
        data["tech_stack"] = ", ".join(sorted(all_tech))
        print(f"  ✓ Tech stack: {data['tech_stack']}")
    else:
        print("  ⚠ No marketing tech stack identified")

    # ─── Step 5: Identify vertical ───
    print("\n🏢 Step 5: Identifying industry vertical...")
    if not data["vertical"]:
        vertical = identify_vertical_from_text(all_text)
        if vertical:
            data["vertical"] = vertical
            print(f"  ✓ Vertical: {vertical}")
        else:
            # Try a more specific search
            ind_text = search_and_extract(f"{company_name} industry sector what does {company_name} do")
            if ind_text:
                all_text += f" {ind_text}"
                vertical = identify_vertical_from_text(ind_text)
                if vertical:
                    data["vertical"] = vertical
                    print(f"  ✓ Vertical: {vertical}")
                else:
                    print("  ⚠ Vertical not identified")

    # ─── Step 6: Determine complexity & region ───
    print("\n🌍 Step 6: Determining complexity and region...")
    geo_text = search_and_extract(f"{company_name} headquarters global operations countries offices")
    if geo_text:
        all_text += f" {geo_text}"
        data["sources"].append("Web search (geography)")

    if not data["complexity"]:
        data["complexity"] = detect_complexity_from_text(all_text)
        print(f"  ✓ Complexity: {data['complexity']}")

    if not data["region"]:
        data["region"] = detect_region_from_text(all_text)
        print(f"  ✓ Region: {data['region']}")

    # ─── Step 7: Search for agency / Braze relationship ───
    print("\n🤝 Step 7: Checking for agency relationships...")
    agency_text = search_and_extract(f"{company_name} marketing agency partner Braze Merkle Accenture")
    if agency_text:
        all_text += f" {agency_text}"
        agency_lower = agency_text.lower()
        if "merkle" in agency_lower:
            data["incumbent_agency"] = "Merkle"
            print(f"  ✓ Incumbent: Merkle")
        elif "accenture" in agency_lower:
            data["incumbent_agency"] = "Accenture"
            print(f"  ✓ Incumbent: Accenture")

    # ─── Step 8: Recent news ───
    print("\n📰 Step 8: Checking recent news...")
    news_text = search_and_extract(f"{company_name} news 2025 2024 announcement")
    if news_text:
        data["sources"].append("Web search (news)")
        data["raw_data"]["news"] = news_text[:1000]

    print(f"\n{'─'*60}")
    print(f"✓ Research complete. {len(data['sources'])} sources used.")
    print(f"{'─'*60}\n")

    return data


# ═══════════════════════════════════════════════
# QUALIFICATION
# ═══════════════════════════════════════════════

def auto_qualify(company_name: str, url: str, output_format: str = "text") -> Dict:
    """Research and qualify a lead automatically."""

    # Normalize URL
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    # Research the company
    company_data = research_company(company_name, url)

    # Calculate ICP score
    score_result = calculate_icp_score(company_data)
    disqualifiers = check_hard_disqualifiers(company_data)
    signals = identify_positive_signals(company_data)

    final_status = score_result["status"]
    if disqualifiers:
        final_status = "qualify_out"

    # Build result
    result = {
        "company": {"name": company_name, "url": url},
        "data": company_data,
        "icp_score": {
            "score": score_result["normalized_score"],
            "max_score": 10,
            "weighted_total": score_result["total_weighted"],
            "weighted_max": score_result["max_weighted"],
            "breakdown": score_result["breakdown"]
        },
        "qualification": {
            "status": final_status,
            "status_display": QUALIFICATION_STATUS.get(final_status, final_status),
            "hard_disqualifiers": disqualifiers,
            "positive_signals": signals
        },
        "research": {
            "sources_count": len(company_data.get("sources", [])),
            "sources": company_data.get("sources", []),
            "researched_at": datetime.now().isoformat()
        }
    }

    # Generate fit summary
    result["analysis"] = generate_analysis(result)

    # Output
    if output_format == "json":
        print(json.dumps(result, indent=2, default=str))
    elif output_format == "html":
        html_report = generate_html_report(result)
        output_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            f"report_{company_name.lower().replace(' ', '_')}.html"
        )
        with open(output_path, 'w') as f:
            f.write(html_report)
        print(f"\n📄 Report saved: {output_path}")
    else:
        print_report(result)

    return result


def generate_analysis(result: Dict) -> Dict:
    """Generate analysis from qualification result."""
    score = result["icp_score"]["score"]
    status = result["qualification"]["status"]
    breakdown = result["icp_score"]["breakdown"]
    disqualifiers = result["qualification"]["hard_disqualifiers"]
    signals = result["qualification"]["positive_signals"]

    # Fit summary
    if disqualifiers:
        fit = f"Not a fit. {len(disqualifiers)} hard disqualifier(s): {', '.join(disqualifiers)}"
    elif status == "qualify_in":
        strengths = []
        if breakdown["revenue"]["raw_score"] >= 2: strengths.append("strong revenue")
        if breakdown["vertical"]["raw_score"] >= 2: strengths.append("target vertical")
        if breakdown["tech_stack"]["raw_score"] >= 2: strengths.append("aligned tech stack")
        if breakdown["complexity"]["raw_score"] >= 2: strengths.append("enterprise complexity")
        fit = f"Strong fit. Score of {score}/10 with {', '.join(strengths) or 'multiple strengths'}."
        if signals:
            fit += f" Plus {len(signals)} positive signal(s)."
    elif status == "borderline":
        fit = f"Borderline. Score of {score}/10. Requires discovery call to validate."
    else:
        fit = f"Weak fit. Score of {score}/10 falls below ICP threshold."

    # Next steps
    if disqualifiers:
        steps = ["Document disqualification reason", "Send polite decline / nurture email", "Add to long-term nurture list"]
    elif status == "qualify_in":
        steps = [
            "Schedule discovery call within 48 hours",
            "Research key stakeholders (CMO, VP Marketing, CRM Lead)",
            "Prepare pain point questions based on vertical",
            "Identify Braze/Hightouch connection for warm intro"
        ]
    elif status == "borderline":
        steps = [
            "Conduct brief qualification call to validate data",
            "Confirm revenue and tech stack details",
            "Assess budget timeline and decision process",
            "Re-score after discovery call"
        ]
    else:
        steps = ["Add to nurture campaign", "Set reminder to re-qualify in 6 months", "Monitor for growth announcements"]

    # Stakeholder targets
    targets = [
        {"role": "Chief Marketing Officer (CMO)", "priority": "High"},
        {"role": "VP of Marketing / Growth", "priority": "High"},
        {"role": "Head of CRM / Lifecycle", "priority": "High"},
        {"role": "Chief Digital Officer", "priority": "Medium"},
        {"role": "VP of Engineering / Data", "priority": "Medium"},
    ]

    return {"fit_summary": fit, "next_steps": steps, "stakeholder_targets": targets}


def print_report(result: Dict):
    """Print formatted qualification report."""
    company = result["company"]
    data = result["data"]
    icp = result["icp_score"]
    qual = result["qualification"]
    analysis = result["analysis"]

    print(f"""
{'='*60}
QUALIFICATION REPORT: {company['name']}
{'='*60}
URL: {company['url']}
Researched: {result['research']['researched_at'][:16]}
Sources: {result['research']['sources_count']}

{'─'*60}
COMPANY PROFILE (Auto-Discovered):
{'─'*60}
  Revenue:      {data.get('revenue', 'Unknown')}
  Employees:    {data.get('employees', 'Unknown')}
  Vertical:     {data.get('vertical', 'Unknown')}
  Tech Stack:   {data.get('tech_stack', 'Unknown')}
  Complexity:   {data.get('complexity', 'Unknown')}
  Region:       {data.get('region', 'Unknown')}

{'─'*60}
ICP SCORE: {icp['score']}/10  {qual['status_display']}
{'─'*60}

SCORE BREAKDOWN:""")

    for criterion, d in icp["breakdown"].items():
        name = criterion.replace("_", " ").title()
        print(f"  {name:15} │ {d['value']:25} │ {d['weighted']}/{d['max_weighted']} pts")

    print(f"""{'─'*60}
  {'TOTAL':15} │ {'':<25} │ {icp['weighted_total']}/{icp['weighted_max']} pts

{'─'*60}
FIT ANALYSIS: {analysis['fit_summary']}""")

    if qual["positive_signals"]:
        print("\n✓ POSITIVE SIGNALS:")
        for s in qual["positive_signals"]:
            print(f"  • {s}")

    if qual["hard_disqualifiers"]:
        print("\n✗ HARD DISQUALIFIERS:")
        for d in qual["hard_disqualifiers"]:
            print(f"  • {d}")

    print("\n📋 NEXT STEPS:")
    for i, step in enumerate(analysis["next_steps"], 1):
        print(f"  {i}. {step}")

    print(f"\n🎯 STAKEHOLDER TARGETS:")
    for t in analysis["stakeholder_targets"]:
        print(f"  • {t['role']} [{t['priority']}]")

    print(f"\n📡 DATA SOURCES:")
    for s in result["research"]["sources"]:
        print(f"  • {s}")

    print(f"\n{'='*60}")


def generate_html_report(result: Dict) -> str:
    """Generate a standalone HTML report."""
    company = result["company"]
    data = result["data"]
    icp = result["icp_score"]
    qual = result["qualification"]
    analysis = result["analysis"]

    status_colors = {
        "qualify_in": ("#22c55e", "rgba(34,197,94,.1)"),
        "borderline": ("#eab308", "rgba(234,179,8,.1)"),
        "qualify_out": ("#ef4444", "rgba(239,68,68,.1)")
    }
    color, bg = status_colors.get(qual["status"], ("#888", "rgba(136,136,136,.1)"))
    status_labels = {"qualify_in": "QUALIFY IN", "borderline": "BORDERLINE", "qualify_out": "QUALIFY OUT"}

    # Build breakdown rows
    bar_colors = {
        "revenue": "#3b82f6", "employees": "#8b5cf6", "vertical": "#f59e0b",
        "tech_stack": "#22c55e", "complexity": "#ec4899", "deal_size": "#06b6d4", "region": "#6366f1"
    }
    breakdown_html = ""
    for key, d in icp["breakdown"].items():
        pct = (d["weighted"] / d["max_weighted"]) * 100 if d["max_weighted"] > 0 else 0
        bc = bar_colors.get(key, "#888")
        name = key.replace("_", " ").title()
        val = html_lib.escape(str(d["value"]))
        breakdown_html += f"""
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;font-size:14px">
          <span style="width:100px;color:#999">{name}</span>
          <div style="flex:1;height:22px;background:#111;border-radius:6px;overflow:hidden">
            <div style="height:100%;width:{pct}%;background:{bc};border-radius:6px"></div>
          </div>
          <span style="width:120px;text-align:right;font-size:12px;color:#999">{val}</span>
          <span style="width:60px;text-align:right;font-weight:600">{d['weighted']}/{d['max_weighted']}</span>
        </div>"""

    # Signals
    signals_html = ""
    for s in qual.get("positive_signals", []):
        signals_html += f'<div style="padding:8px 12px;background:rgba(34,197,94,.1);border-radius:8px;margin-bottom:4px;font-size:14px">✓ {html_lib.escape(s)}</div>'
    for d in qual.get("hard_disqualifiers", []):
        signals_html += f'<div style="padding:8px 12px;background:rgba(239,68,68,.1);border-radius:8px;margin-bottom:4px;font-size:14px">✗ {html_lib.escape(d)}</div>'

    # Steps
    steps_html = ""
    for i, step in enumerate(analysis.get("next_steps", []), 1):
        steps_html += f'<div style="padding:8px 12px;background:rgba(59,130,246,.1);border-radius:8px;margin-bottom:4px;font-size:14px">{i}. {html_lib.escape(step)}</div>'

    # Sources
    sources_html = ""
    for s in result["research"].get("sources", []):
        sources_html += f'<div style="padding:4px 0;font-size:13px;color:#999">• {html_lib.escape(s)}</div>'

    name = html_lib.escape(company["name"])
    url_display = html_lib.escape(company["url"])
    fit = html_lib.escape(analysis.get("fit_summary", ""))
    desc = html_lib.escape(data.get("description", "")[:200])

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Qualification Report — {name}</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0a0a0f;color:#e8e8f0;padding:40px 24px}}
  .container{{max-width:800px;margin:0 auto}}
  .card{{background:#13131a;border:1px solid #2a2a3a;border-radius:16px;padding:32px;margin-bottom:24px}}
  h2{{font-size:16px;margin-bottom:16px;display:flex;align-items:center;gap:8px}}
  .profile-grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px 24px}}
  .profile-item{{font-size:14px;padding:4px 0}}
  .profile-label{{color:#999;font-size:12px;text-transform:uppercase;letter-spacing:.5px}}
</style></head>
<body><div class="container">
  <!-- Header -->
  <div class="card" style="text-align:center;border-top:4px solid {color}">
    <div style="font-size:13px;color:#999;margin-bottom:8px">{url_display}</div>
    <h1 style="font-size:28px;font-weight:700;margin-bottom:4px">{name}</h1>
    <div style="font-size:13px;color:#999;margin-bottom:24px">{desc}</div>
    <div style="font-size:72px;font-weight:800;color:{color}">{icp['score']}</div>
    <div style="font-size:13px;color:#999;margin-bottom:12px">ICP SCORE OUT OF 10</div>
    <span style="display:inline-block;padding:6px 20px;border-radius:20px;background:{bg};color:{color};font-size:14px;font-weight:600;border:1px solid {color}33">{status_labels.get(qual['status'], 'UNKNOWN')}</span>
  </div>

  <!-- Company Profile -->
  <div class="card">
    <h2>🏢 Company Profile (Auto-Discovered)</h2>
    <div class="profile-grid">
      <div class="profile-item"><div class="profile-label">Revenue</div>{html_lib.escape(data.get('revenue','Unknown'))}</div>
      <div class="profile-item"><div class="profile-label">Employees</div>{html_lib.escape(str(data.get('employees','Unknown')))}</div>
      <div class="profile-item"><div class="profile-label">Vertical</div>{html_lib.escape(data.get('vertical','Unknown'))}</div>
      <div class="profile-item"><div class="profile-label">Tech Stack</div>{html_lib.escape(data.get('tech_stack','Unknown'))}</div>
      <div class="profile-item"><div class="profile-label">Complexity</div>{html_lib.escape(data.get('complexity','Unknown'))}</div>
      <div class="profile-item"><div class="profile-label">Region</div>{html_lib.escape(data.get('region','Unknown'))}</div>
    </div>
  </div>

  <!-- Score Breakdown -->
  <div class="card">
    <h2>📊 Score Breakdown</h2>
    {breakdown_html}
    <div style="margin-top:12px;padding-top:12px;border-top:1px solid #2a2a3a;display:flex;justify-content:space-between;font-weight:700">
      <span>TOTAL</span><span>{icp['weighted_total']}/{icp['weighted_max']} pts</span>
    </div>
  </div>

  <!-- Fit Analysis -->
  <div class="card">
    <h2>💡 Fit Analysis</h2>
    <div style="padding:16px;background:{bg};border-radius:10px;margin-bottom:16px;font-size:15px">{fit}</div>
    {signals_html}
  </div>

  <!-- Next Steps -->
  <div class="card">
    <h2>📋 Next Steps</h2>
    {steps_html}
  </div>

  <!-- Sources -->
  <div class="card">
    <h2>📡 Data Sources ({result['research']['sources_count']})</h2>
    {sources_html}
    <div style="margin-top:8px;font-size:12px;color:#666">Researched: {result['research']['researched_at'][:16]}</div>
  </div>

  <div style="text-align:center;font-size:12px;color:#555;margin-top:24px">
    Massive Rocket Lead Qualification Tool v1.0
  </div>
</div></body></html>"""


def main():
    parser = argparse.ArgumentParser(
        description="Auto-research and qualify a lead against Massive Rocket ICP"
    )
    parser.add_argument("company_name", help="Company name")
    parser.add_argument("url", help="Company website URL")
    parser.add_argument("--output", "-o", choices=["text", "json", "html"], default="text",
                        help="Output format")
    args = parser.parse_args()

    auto_qualify(args.company_name, args.url, args.output)


if __name__ == "__main__":
    main()
