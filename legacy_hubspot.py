"""
Massive Rocket Lead Qualification Server
Flask backend for HubSpot enrichment + Notion sync. Serves qualify.html.

Setup:
    pip install flask flask-cors requests python-dotenv
    cp .env.example .env   # add your HubSpot + Notion keys
    python server.py       # opens at http://localhost:5050

Endpoints:
    GET  /                  - Serves qualify.html
    POST /api/enrich        - HubSpot enrichment (company + deals + contacts + notes)
    POST /api/sync-to-notion - Push qualification to Notion
    GET  /api/health        - Health check
"""

import os
import json
import requests as http_requests
from datetime import datetime
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from notion_client import Client as NotionClient
    NOTION_AVAILABLE = True
except ImportError:
    NOTION_AVAILABLE = False

app = Flask(__name__)
CORS(app)

HUBSPOT_API_KEY = os.environ.get("HUBSPOT_API_KEY", "")
NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "6552dcec12b644ba9e88500396260f60")
HUBSPOT_BASE = "https://api.hubapi.com"


# ═══════════════════════════════════════════════════════════════
# HUBSPOT API HELPERS
# ═══════════════════════════════════════════════════════════════

def hs_headers():
    return {
        "Authorization": f"Bearer {HUBSPOT_API_KEY}",
        "Content-Type": "application/json"
    }


def hs_search_company(name, domain=None):
    """Search HubSpot for a company by name and/or domain."""
    if not HUBSPOT_API_KEY:
        return None, "HubSpot API key not configured"

    url = f"{HUBSPOT_BASE}/crm/v3/objects/companies/search"
    properties = [
        "name", "domain", "industry", "annualrevenue", "numberofemployees",
        "city", "state", "country", "description", "founded_year",
        "total_revenue", "hs_num_open_deals", "num_associated_contacts",
        "num_associated_deals", "lifecyclestage", "hs_lead_status",
        "notes_last_updated", "hs_lastmodifieddate", "createdate"
    ]

    results = []

    # Try domain search first (more precise)
    if domain:
        clean_domain = domain.replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")
        payload = {
            "filterGroups": [{
                "filters": [{
                    "propertyName": "domain",
                    "operator": "CONTAINS_TOKEN",
                    "value": clean_domain
                }]
            }],
            "properties": properties,
            "limit": 5
        }
        try:
            resp = http_requests.post(url, headers=hs_headers(), json=payload, timeout=10)
            if resp.status_code == 200:
                results = resp.json().get("results", [])
        except Exception as e:
            print(f"Domain search error: {e}")

    # Fall back to name search
    if not results and name:
        payload = {
            "query": name,
            "properties": properties,
            "limit": 5
        }
        try:
            resp = http_requests.post(url, headers=hs_headers(), json=payload, timeout=10)
            if resp.status_code == 200:
                results = resp.json().get("results", [])
        except Exception as e:
            return None, f"Search error: {e}"

    if not results:
        return None, "No matching company found in HubSpot"

    company = results[0]
    return {
        "id": company["id"],
        "properties": company.get("properties", {}),
        "all_matches": len(results)
    }, None


def hs_get_associated(company_id, object_type, properties_str, limit=20):
    """Generic: get objects associated with a company."""
    if not HUBSPOT_API_KEY or not company_id:
        return []

    assoc_url = f"{HUBSPOT_BASE}/crm/v3/objects/companies/{company_id}/associations/{object_type}"
    try:
        resp = http_requests.get(assoc_url, headers=hs_headers(), timeout=10)
        if resp.status_code != 200:
            return []
        associations = resp.json().get("results", [])
    except Exception:
        return []

    if not associations:
        return []

    items = []
    for a in associations[:limit]:
        obj_url = f"{HUBSPOT_BASE}/crm/v3/objects/{object_type}/{a['id']}"
        params = {"properties": properties_str}
        try:
            resp = http_requests.get(obj_url, headers=hs_headers(), params=params, timeout=10)
            if resp.status_code == 200:
                obj = resp.json()
                items.append({"id": obj["id"], "properties": obj.get("properties", {})})
        except Exception:
            continue

    return items


def hs_get_deals(company_id):
    return hs_get_associated(
        company_id, "deals",
        "dealname,dealstage,amount,closedate,pipeline,createdate,description,dealtype,hs_lastmodifieddate",
        limit=20
    )


def hs_get_contacts(company_id):
    return hs_get_associated(
        company_id, "contacts",
        "firstname,lastname,email,jobtitle,phone,lifecyclestage,hs_lead_status,lastmodifieddate",
        limit=15
    )


def hs_get_notes(company_id):
    raw = hs_get_associated(
        company_id, "notes",
        "hs_note_body,hs_timestamp,hs_lastmodifieddate",
        limit=10
    )
    notes = []
    for n in raw:
        body = n["properties"].get("hs_note_body", "")
        ts = n["properties"].get("hs_timestamp", "")
        if body:
            # Strip HTML tags from note body
            import re
            clean = re.sub(r"<[^>]+>", " ", body).strip()
            clean = re.sub(r"\s+", " ", clean)
            notes.append({"body": clean[:500], "timestamp": ts})
    return sorted(notes, key=lambda n: n.get("timestamp", ""), reverse=True)


# ═══════════════════════════════════════════════════════════════
# ENRICHMENT PIPELINE
# ═══════════════════════════════════════════════════════════════

# Map HubSpot industry codes to MR verticals
INDUSTRY_MAP = {
    "RESTAURANTS": "QSR", "FOOD_BEVERAGES": "QSR", "FOOD_PRODUCTION": "QSR",
    "RETAIL": "Retail", "CONSUMER_GOODS": "Retail", "APPAREL_FASHION": "Retail",
    "LUXURY_GOODS_JEWELRY": "Retail", "COSMETICS": "Retail",
    "HOSPITALITY": "Travel & Hospitality", "LEISURE_TRAVEL_TOURISM": "Travel & Hospitality",
    "AIRLINES_AVIATION": "Travel & Hospitality",
    "BANKING_MORTGAGE": "Fintech", "FINANCIAL_SERVICES": "Fintech",
    "CAPITAL_MARKETS": "Fintech", "INSURANCE": "Fintech",
    "TELECOMMUNICATIONS": "Telecom", "WIRELESS": "Telecom",
    "MEDIA_COMMUNICATIONS": "Media", "ENTERTAINMENT": "Media",
    "BROADCAST_MEDIA": "Media", "ONLINE_MEDIA": "Media",
    "HEALTH_CARE": "Healthcare", "HOSPITAL_HEALTH_CARE": "Healthcare",
    "COMPUTER_SOFTWARE": "SaaS", "INFORMATION_TECHNOLOGY_AND_SERVICES": "SaaS",
    "INTERNET": "SaaS",
}

NAM_COUNTRIES = ["United States", "Canada", "US", "USA"]
EMEA_COUNTRIES = ["United Kingdom", "UK", "Germany", "France", "Netherlands",
                  "Belgium", "Spain", "Italy", "Sweden", "Norway", "Denmark", "Ireland"]


def build_enrichment(name, domain):
    """Full enrichment: company + deals + contacts + notes + prefill."""
    result = {
        "source": "hubspot",
        "timestamp": datetime.now().isoformat(),
        "company": None,
        "deals": [],
        "contacts": [],
        "notes": [],
        "prefill": {},
        "account_history": [],
        "context_summary": "",
        "error": None
    }

    # 1. Find the company
    company_data, error = hs_search_company(name, domain)
    if error:
        result["error"] = error
        result["context_summary"] = f"HubSpot: {error}"
        return result

    result["company"] = company_data
    props = company_data.get("properties", {})
    company_id = company_data["id"]

    # 2. Get deals, contacts, notes in sequence
    deals = hs_get_deals(company_id)
    result["deals"] = deals

    contacts = hs_get_contacts(company_id)
    result["contacts"] = contacts

    notes = hs_get_notes(company_id)
    result["notes"] = notes

    # 3. Build pre-fill values for qualify.html fields
    prefill = {}
    revenue = props.get("annualrevenue")
    employees = props.get("numberofemployees")
    industry = props.get("industry", "")
    country = props.get("country", "")
    city = props.get("city", "")

    if revenue:
        try:
            rev_num = float(revenue)
            if rev_num >= 1e9:
                prefill["revenue"] = f"${rev_num/1e9:.1f}B"
            elif rev_num >= 1e6:
                prefill["revenue"] = f"${rev_num/1e6:.0f}M"
            elif rev_num > 0:
                prefill["revenue"] = f"${rev_num:,.0f}"
        except (ValueError, TypeError):
            pass

    if employees:
        prefill["employees"] = str(employees)

    if industry:
        prefill["vertical"] = INDUSTRY_MAP.get(industry, industry.replace("_", " ").title())

    if country:
        if any(c in country for c in NAM_COUNTRIES):
            prefill["region"] = f"US" + (f" ({city})" if city else "")
        elif any(c in country for c in EMEA_COUNTRIES):
            prefill["region"] = f"EMEA" + (f" ({city}, {country})" if city else f" ({country})")
        else:
            prefill["region"] = f"{city}, {country}" if city else country

    if props.get("domain"):
        prefill["url"] = props["domain"]

    result["prefill"] = prefill

    # 4. Build account history timeline
    history = []

    for d in deals:
        dp = d["properties"]
        stage = dp.get("dealstage", "unknown")
        stage_label = {
            "closedwon": "WON", "closedlost": "LOST",
            "appointmentscheduled": "Scheduled", "qualifiedtobuy": "Qualified",
            "presentationscheduled": "Presentation", "decisionmakerboughtin": "Decision Maker",
            "contractsent": "Contract Sent"
        }.get(stage, stage.replace("_", " ").title() if stage else "Unknown")

        amount = dp.get("amount", "")
        amount_str = ""
        if amount:
            try:
                amt = float(amount)
                amount_str = f"${amt:,.0f}" if amt >= 1000 else f"${amt:.0f}"
            except (ValueError, TypeError):
                amount_str = amount

        history.append({
            "type": "deal",
            "name": dp.get("dealname", "Unnamed deal"),
            "status": stage_label,
            "amount": amount_str,
            "date": (dp.get("closedate") or dp.get("createdate") or "")[:10],
            "description": dp.get("description", "")[:200]
        })

    result["account_history"] = sorted(history, key=lambda h: h.get("date", ""), reverse=True)

    # 5. Build context summary text
    lines = []
    lines.append(f"HubSpot record: {props.get('name', name)}")
    if prefill.get("revenue"):
        lines.append(f"Revenue: {prefill['revenue']}")
    if employees:
        lines.append(f"Employees: {employees}")
    if industry:
        lines.append(f"Industry: {industry.replace('_', ' ').title()}")
    if prefill.get("region"):
        lines.append(f"Region: {prefill['region']}")

    won = [d for d in deals if d["properties"].get("dealstage") == "closedwon"]
    active = [d for d in deals if d["properties"].get("dealstage") not in ("closedlost", "closedwon", None)]
    lost = [d for d in deals if d["properties"].get("dealstage") == "closedlost"]

    if won:
        lines.append(f"\nPrevious wins ({len(won)}):")
        for w in won[:5]:
            wp = w["properties"]
            lines.append(f"  - {wp.get('dealname','Unnamed')}: {wp.get('amount','N/A')} (closed {(wp.get('closedate') or '')[:10]})")

    if active:
        lines.append(f"\nActive deals ({len(active)}):")
        for a in active[:5]:
            ap = a["properties"]
            lines.append(f"  - {ap.get('dealname','Unnamed')}: stage={ap.get('dealstage','N/A')}, amount={ap.get('amount','N/A')}")

    if lost:
        lines.append(f"\nLost deals: {len(lost)}")
        for l in lost[:3]:
            lp = l["properties"]
            lines.append(f"  - {lp.get('dealname','Unnamed')} ({(lp.get('closedate') or '')[:10]})")

    if not deals:
        lines.append("\nNo previous deals in HubSpot (new prospect)")

    if contacts:
        lines.append(f"\nContacts on file ({len(contacts)}):")
        for c in contacts[:8]:
            cp = c["properties"]
            cname = f"{cp.get('firstname', '')} {cp.get('lastname', '')}".strip()
            title = cp.get("jobtitle", "")
            email = cp.get("email", "")
            if cname:
                parts = [cname]
                if title:
                    parts.append(title)
                if email:
                    parts.append(email)
                lines.append(f"  - {' | '.join(parts)}")

    if notes:
        lines.append(f"\nRecent notes ({len(notes)}):")
        for n in notes[:3]:
            ts = n.get("timestamp", "")[:10]
            body = n.get("body", "")[:150]
            lines.append(f"  [{ts}] {body}")

    result["context_summary"] = "\n".join(lines)
    return result


# ═══════════════════════════════════════════════════════════════
# FLASK ROUTES
# ═══════════════════════════════════════════════════════════════

@app.route("/")
def serve_tool():
    """Serve the qualification tool."""
    return send_file("qualify.html")


@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "hubspot_configured": bool(HUBSPOT_API_KEY),
        "notion_configured": bool(NOTION_API_KEY and NOTION_DATABASE_ID),
        "timestamp": datetime.now().isoformat()
    })


@app.route("/api/enrich", methods=["POST"])
def enrich():
    """
    HubSpot enrichment endpoint.
    Body: { "name": "Company Name", "domain": "company.com" }
    Returns: company data, deals, contacts, notes, pre-fill values, context summary
    """
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    domain = data.get("domain", "").strip()

    if not name and not domain:
        return jsonify({"error": "Provide a company name or domain"}), 400

    if not HUBSPOT_API_KEY:
        return jsonify({
            "error": None,
            "source": "hubspot",
            "company": None,
            "deals": [],
            "contacts": [],
            "notes": [],
            "prefill": {},
            "account_history": [],
            "context_summary": "HubSpot not connected. Add HUBSPOT_API_KEY to .env to enable auto-enrichment."
        }), 200

    result = build_enrichment(name, domain)
    return jsonify(result)


@app.route("/api/sync-to-notion", methods=["POST"])
def sync_to_notion():
    """Push qualification data to Notion. Uses notion_sync.py module."""
    try:
        from notion_sync import NotionSync
        data = request.get_json()
        syncer = NotionSync(
            api_key=NOTION_API_KEY or None,
            database_id=NOTION_DATABASE_ID or None
        )
        page = syncer.sync(data)
        return jsonify({
            "success": True,
            "page_id": page["id"],
            "page_url": page.get("url", ""),
            "message": f"Synced to Notion"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  Massive Rocket Lead Qualification Server")
    print("=" * 60)
    print(f"  HubSpot:  {'Configured' if HUBSPOT_API_KEY else 'NOT CONFIGURED (add HUBSPOT_API_KEY to .env)'}")
    print(f"  Notion:   {'Configured' if NOTION_API_KEY else 'NOT CONFIGURED (add NOTION_API_KEY to .env)'}")
    print(f"  Notion DB: {NOTION_DATABASE_ID or 'NOT SET'}")
    print(f"  Tool:      http://localhost:5050")
    print(f"  Health:    http://localhost:5050/api/health")
    print("=" * 60 + "\n")

    app.run(host="0.0.0.0", port=5050, debug=True)
