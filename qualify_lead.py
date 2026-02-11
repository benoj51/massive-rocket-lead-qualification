#!/usr/bin/env python3
"""
Massive Rocket Lead Qualification Tool
======================================

Qualifies sales leads against ICP criteria using company research.

Usage:
    python qualify_lead.py "Company Name" "company-url.com"
    python qualify_lead.py "McDonald's" "mcdonalds.com" --output json
    python qualify_lead.py "Chipotle" "chipotle.com" --sync-notion

Requirements:
    pip install requests beautifulsoup4
"""

import argparse
import json
import sys
import os
from datetime import datetime
from typing import Dict, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    ICP_CRITERIA, THRESHOLDS, HARD_DISQUALIFIERS,
    POSITIVE_SIGNALS, QUALIFICATION_STATUS
)
from scoring import (
    calculate_icp_score, check_hard_disqualifiers,
    identify_positive_signals, generate_score_summary
)
from research import (
    CompanyData, build_search_queries, create_research_prompt,
    format_research_report, extract_domain
)


def print_header():
    """Print tool header."""
    print("""
╔═══════════════════════════════════════════════════════════════╗
║          MASSIVE ROCKET LEAD QUALIFICATION TOOL               ║
║                    ICP Scoring Engine v1.0                    ║
╚═══════════════════════════════════════════════════════════════╝
""")


def qualify_lead(
    company_name: str,
    url: str,
    company_data: Optional[Dict[str, Any]] = None,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Qualify a lead against ICP criteria.

    Args:
        company_name: Company name
        url: Company website URL
        company_data: Optional pre-gathered company data dict
        verbose: Print detailed output

    Returns:
        Qualification result dict
    """
    if verbose:
        print(f"\n🔍 Qualifying: {company_name}")
        print(f"   URL: {url}")
        print("-" * 60)

    # If no data provided, create empty data structure
    if company_data is None:
        company_data = {
            "name": company_name,
            "url": url,
            "revenue": "",
            "employees": "",
            "vertical": "",
            "tech_stack": "",
            "complexity": "",
            "region": "",
        }

    # Calculate ICP score
    score_result = calculate_icp_score(company_data)

    # Check for hard disqualifiers
    disqualifiers = check_hard_disqualifiers(company_data)

    # Identify positive signals
    signals = identify_positive_signals(company_data)

    # Override qualification if hard disqualifiers exist
    final_status = score_result["status"]
    if disqualifiers:
        final_status = "qualify_out"

    # Build qualification result
    result = {
        "company": {
            "name": company_name,
            "url": url,
            "domain": extract_domain(url)
        },
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
        "analysis": {
            "fit_summary": generate_fit_summary(company_data, score_result, disqualifiers, signals),
            "next_steps": generate_next_steps(final_status, score_result, disqualifiers),
            "stakeholder_targets": generate_stakeholder_targets(company_data)
        },
        "metadata": {
            "qualified_at": datetime.now().isoformat(),
            "tool_version": "1.0"
        }
    }

    if verbose:
        print_qualification_report(result)

    return result


def generate_fit_summary(
    company_data: Dict,
    score_result: Dict,
    disqualifiers: list,
    signals: list
) -> str:
    """Generate a fit summary explanation."""
    score = score_result["normalized_score"]
    status = score_result["status"]

    if disqualifiers:
        return f"❌ NOT A FIT: This lead has {len(disqualifiers)} hard disqualifier(s) that make it unsuitable regardless of score. Issues: {', '.join(disqualifiers)}"

    if status == "qualify_in":
        positives = []
        breakdown = score_result["breakdown"]

        if breakdown["revenue"]["raw_score"] >= 2:
            positives.append("strong revenue")
        if breakdown["vertical"]["raw_score"] >= 2:
            positives.append("target vertical")
        if breakdown["tech_stack"]["raw_score"] >= 2:
            positives.append("aligned tech stack")
        if breakdown["complexity"]["raw_score"] >= 2:
            positives.append("enterprise complexity")

        signal_text = f" Plus {len(signals)} positive signal(s)." if signals else ""
        return f"✅ STRONG FIT: Score of {score}/10 with {', '.join(positives) if positives else 'multiple strengths'}.{signal_text}"

    elif status == "borderline":
        weaknesses = []
        breakdown = score_result["breakdown"]

        if breakdown["revenue"]["raw_score"] <= 1:
            weaknesses.append("revenue uncertainty")
        if breakdown["tech_stack"]["raw_score"] <= 1:
            weaknesses.append("tech stack alignment unclear")
        if breakdown["employees"]["raw_score"] <= 1:
            weaknesses.append("company size")

        return f"⚠️ BORDERLINE: Score of {score}/10. Concerns: {', '.join(weaknesses) if weaknesses else 'mixed signals'}. Requires discovery to validate."

    else:
        return f"❌ WEAK FIT: Score of {score}/10 falls below ICP threshold. Consider qualifying out unless there are compelling factors."


def generate_next_steps(status: str, score_result: Dict, disqualifiers: list) -> list:
    """Generate recommended next steps based on qualification."""
    steps = []

    if disqualifiers:
        steps.append("Document disqualification reason")
        steps.append("Send polite decline / nurture email")
        steps.append("Add to long-term nurture list if relevant")
        return steps

    if status == "qualify_in":
        steps.append("Schedule discovery call within 48 hours")
        steps.append("Research key stakeholders (CMO, VP Marketing, CRM Lead)")
        steps.append("Prepare pain point questions based on vertical")
        steps.append("Identify potential Braze/Hightouch connection for warm intro")
    elif status == "borderline":
        steps.append("Conduct brief qualification call to validate data")
        steps.append("Confirm revenue and tech stack details")
        steps.append("Assess budget timeline and decision process")
        steps.append("Re-score after discovery call")
    else:
        steps.append("Add to nurture campaign")
        steps.append("Set reminder to re-qualify in 6 months")
        steps.append("Monitor for funding/growth announcements")

    return steps


def generate_stakeholder_targets(company_data: Dict) -> list:
    """Generate target stakeholder roles to identify."""
    targets = [
        {"role": "Chief Marketing Officer (CMO)", "priority": "High", "why": "Budget authority, strategic vision"},
        {"role": "VP of Marketing / Growth", "priority": "High", "why": "Operational owner, day-to-day champion"},
        {"role": "Head of CRM / Lifecycle", "priority": "High", "why": "Direct user, pain point owner"},
        {"role": "Chief Digital Officer", "priority": "Medium", "why": "Digital transformation sponsor"},
        {"role": "VP of Engineering / Data", "priority": "Medium", "why": "Technical validation, integration"},
    ]

    vertical = company_data.get("vertical", "").lower()

    # Add vertical-specific roles
    if "retail" in vertical or "ecommerce" in vertical:
        targets.append({"role": "VP of E-commerce", "priority": "High", "why": "Channel owner"})
    if "qsr" in vertical or "restaurant" in vertical:
        targets.append({"role": "VP of Digital / Loyalty", "priority": "High", "why": "App/loyalty program owner"})

    return targets


def print_qualification_report(result: Dict):
    """Print formatted qualification report."""
    company = result["company"]
    icp = result["icp_score"]
    qual = result["qualification"]
    analysis = result["analysis"]

    print(f"""
{'='*60}
QUALIFICATION REPORT: {company['name']}
{'='*60}

ICP SCORE: {icp['score']}/10  {qual['status_display']}
{'─'*60}

SCORE BREAKDOWN:""")

    for criterion, data in icp["breakdown"].items():
        name = criterion.replace("_", " ").title()
        print(f"  {name:15} │ {data['value']:25} │ {data['weighted']}/{data['max_weighted']} pts")

    print(f"""{'─'*60}
  {'TOTAL':15} │ {'':<25} │ {icp['weighted_total']}/{icp['weighted_max']} pts

{'─'*60}
FIT ANALYSIS:
{analysis['fit_summary']}
""")

    if qual["hard_disqualifiers"]:
        print("❌ HARD DISQUALIFIERS:")
        for d in qual["hard_disqualifiers"]:
            print(f"   • {d}")
        print()

    if qual["positive_signals"]:
        print("✓ POSITIVE SIGNALS:")
        for s in qual["positive_signals"]:
            print(f"   • {s}")
        print()

    print("📋 RECOMMENDED NEXT STEPS:")
    for i, step in enumerate(analysis["next_steps"], 1):
        print(f"   {i}. {step}")

    print(f"""
{'─'*60}
🎯 STAKEHOLDER TARGETS:""")
    for target in analysis["stakeholder_targets"][:5]:
        print(f"   • {target['role']} [{target['priority']}]")

    print(f"""
{'='*60}
""")


def interactive_mode(company_name: str, url: str):
    """Run in interactive mode, prompting for missing data."""
    print_header()
    print(f"Qualifying: {company_name} ({url})")
    print("\nPlease provide company information (press Enter to skip):\n")

    company_data = {
        "name": company_name,
        "url": url
    }

    prompts = [
        ("revenue", "Annual Revenue (e.g., $2B, £500M): "),
        ("employees", "Employee Count (e.g., 5000, 10000+): "),
        ("vertical", "Industry/Vertical (e.g., QSR, Retail, Fintech): "),
        ("tech_stack", "Tech Stack (e.g., Braze, Snowflake, Segment): "),
        ("complexity", "Complexity (e.g., Multi-brand, Global, Enterprise): "),
        ("region", "Primary Region (e.g., US, UK, EMEA, Global): "),
        ("incumbent_agency", "Current Agency (if known): "),
        ("source", "Lead Source (e.g., Braze referral, inbound): "),
    ]

    for key, prompt in prompts:
        value = input(f"  {prompt}").strip()
        if value:
            company_data[key] = value

    print()
    return qualify_lead(company_name, url, company_data)


def main():
    parser = argparse.ArgumentParser(
        description="Massive Rocket Lead Qualification Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python qualify_lead.py "McDonald's" "mcdonalds.com"
  python qualify_lead.py "Chipotle" "chipotle.com" --interactive
  python qualify_lead.py "Domino's" "dominos.com" --output json

Data Input Options:
  --revenue       Annual revenue (e.g., "$2B", "£500M")
  --employees     Employee count (e.g., "5000", "10000+")
  --vertical      Industry vertical (e.g., "QSR", "Retail")
  --tech-stack    Technology stack (e.g., "Braze, Snowflake")
  --region        Geographic region (e.g., "US", "EMEA", "Global")
        """
    )

    parser.add_argument("company_name", help="Company name")
    parser.add_argument("url", help="Company website URL")
    parser.add_argument("--interactive", "-i", action="store_true",
                        help="Interactive mode - prompt for company data")
    parser.add_argument("--output", "-o", choices=["text", "json"], default="text",
                        help="Output format (default: text)")
    parser.add_argument("--sync-notion", action="store_true",
                        help="Sync result to Notion database")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Minimal output (just score)")

    # Data input arguments
    parser.add_argument("--revenue", help="Annual revenue")
    parser.add_argument("--employees", help="Employee count")
    parser.add_argument("--vertical", help="Industry vertical")
    parser.add_argument("--tech-stack", help="Technology stack")
    parser.add_argument("--complexity", help="Organizational complexity")
    parser.add_argument("--region", help="Geographic region")
    parser.add_argument("--source", help="Lead source")
    parser.add_argument("--incumbent", help="Current agency")

    args = parser.parse_args()

    if args.interactive:
        result = interactive_mode(args.company_name, args.url)
    else:
        # Build company data from arguments
        company_data = {
            "name": args.company_name,
            "url": args.url,
        }

        if args.revenue:
            company_data["revenue"] = args.revenue
        if args.employees:
            company_data["employees"] = args.employees
        if args.vertical:
            company_data["vertical"] = args.vertical
        if args.tech_stack:
            company_data["tech_stack"] = args.tech_stack
        if args.complexity:
            company_data["complexity"] = args.complexity
        if args.region:
            company_data["region"] = args.region
        if args.source:
            company_data["source"] = args.source
        if args.incumbent:
            company_data["incumbent_agency"] = args.incumbent

        if not args.quiet:
            print_header()

        verbose = not args.quiet and args.output == "text"
        result = qualify_lead(args.company_name, args.url, company_data, verbose=verbose)

    # Output handling
    if args.output == "json":
        print(json.dumps(result, indent=2, default=str))
    elif args.quiet:
        print(f"{result['icp_score']['score']}/10 - {result['qualification']['status_display']}")

    # Notion sync
    if args.sync_notion:
        try:
            from notion_sync import sync_to_notion
            print("\n📤 Syncing to Notion...")
            sync_to_notion(result)
            print("✓ Synced successfully!")
        except ImportError:
            print("\n⚠️  Notion sync not available. Run: pip install notion-client")
        except Exception as e:
            print(f"\n⚠️  Notion sync failed: {e}")

    return result


if __name__ == "__main__":
    main()
