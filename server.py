"""
Massive Rocket Lead Qualification Server
Simple Flask server to handle Notion API integration securely.

Setup:
    pip install flask flask-cors notion-client python-dotenv

    Create a .env file with:
        NOTION_API_KEY=your-notion-api-key
        NOTION_DATABASE_ID=your-database-id

Run:
    python server.py
"""

import os
import json
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Try to import notion-client
try:
    from notion_client import Client
    NOTION_AVAILABLE = True
except ImportError:
    NOTION_AVAILABLE = False
    print("Warning: notion-client not installed. Run: pip install notion-client")

app = Flask(__name__)
CORS(app)  # Enable CORS for local development

# Notion configuration
NOTION_API_KEY = os.environ.get("NOTION_API_KEY")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")


def get_notion_client():
    """Get Notion client instance."""
    if not NOTION_AVAILABLE:
        raise Exception("notion-client not installed. Run: pip install notion-client")
    if not NOTION_API_KEY:
        raise Exception("NOTION_API_KEY not set in environment")
    return Client(auth=NOTION_API_KEY)


def create_notion_properties(data):
    """Convert lead data to Notion page properties."""

    # Map status to Notion select values
    status_map = {
        "qualify_in": "Qualify In",
        "borderline": "Borderline",
        "qualify_out": "Qualify Out"
    }

    properties = {
        "Company Name": {
            "title": [{"text": {"content": data.get("companyName", "Unknown")}}]
        },
        "ICP Score": {
            "number": data.get("normalizedScore", 0)
        },
        "Status": {
            "select": {"name": status_map.get(data.get("status"), "Unknown")}
        },
        "Qualified Date": {
            "date": {"start": datetime.now().isoformat()[:10]}
        }
    }

    # URL
    if data.get("companyUrl"):
        url = data["companyUrl"]
        if not url.startswith("http"):
            url = f"https://{url}"
        properties["URL"] = {"url": url}

    # Vertical
    vertical_map = {
        "qsr": "QSR / Fast Food",
        "retail": "Retail",
        "travel": "Travel & Hospitality",
        "fintech": "Fintech",
        "delivery": "Delivery",
        "convenience": "Convenience",
        "telecom": "Telecom",
        "media": "Media & Entertainment",
        "healthcare": "Healthcare",
        "smart_home": "Smart Home / IoT",
        "saas": "SaaS / Technology",
        "manufacturing": "Manufacturing"
    }
    if data.get("vertical"):
        properties["Vertical"] = {
            "select": {"name": vertical_map.get(data["vertical"], "Other")}
        }

    # Revenue
    if data.get("revenue"):
        properties["Revenue"] = {
            "rich_text": [{"text": {"content": data["revenue"]}}]
        }

    # Employees
    if data.get("employees"):
        properties["Employees"] = {
            "rich_text": [{"text": {"content": str(data["employees"])}}]
        }

    # Tech Stack
    if data.get("techStack"):
        tech_list = [t.strip() for t in data["techStack"].split(",") if t.strip()]
        properties["Tech Stack"] = {
            "multi_select": [{"name": tech} for tech in tech_list[:10]]
        }

    # Region
    region_map = {
        "nam": "NAM",
        "emea": "EMEA",
        "apac": "APAC",
        "nam_emea": "Multi-Region",
        "global": "Global"
    }
    if data.get("region"):
        properties["Region"] = {
            "select": {"name": region_map.get(data["region"], "Other")}
        }

    # Fit Summary
    if data.get("fitSummary"):
        properties["Fit Summary"] = {
            "rich_text": [{"text": {"content": data["fitSummary"][:2000]}}]
        }

    # Next Steps
    if data.get("nextSteps"):
        steps_text = "\n".join(f"• {step}" for step in data["nextSteps"])
        properties["Next Steps"] = {
            "rich_text": [{"text": {"content": steps_text[:2000]}}]
        }

    # Positive Signals
    if data.get("positiveSignals"):
        properties["Positive Signals"] = {
            "multi_select": [{"name": s[:100]} for s in data["positiveSignals"][:5]]
        }

    # Disqualifiers
    if data.get("disqualifiers"):
        properties["Disqualifiers"] = {
            "multi_select": [{"name": d[:100]} for d in data["disqualifiers"][:5]]
        }

    # Lead Source
    if data.get("source"):
        properties["Lead Source"] = {
            "rich_text": [{"text": {"content": data["source"]}}]
        }

    return properties


def create_notion_content(data):
    """Create Notion page content blocks."""
    blocks = []

    # Header
    blocks.append({
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "Qualification Summary"}}]
        }
    })

    # Score callout
    score = data.get("normalizedScore", 0)
    status = data.get("statusDisplay", "Unknown")
    emoji = "✅" if "qualify_in" in data.get("status", "") else "⚠️" if "borderline" in data.get("status", "") else "❌"

    blocks.append({
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [{"type": "text", "text": {"content": f"ICP Score: {score}/10 — {emoji} {status}"}}],
            "icon": {"emoji": "📊"}
        }
    })

    # Score breakdown
    blocks.append({
        "object": "block",
        "type": "heading_3",
        "heading_3": {
            "rich_text": [{"type": "text", "text": {"content": "Score Breakdown"}}]
        }
    })

    breakdown = data.get("breakdown", {})
    criteria_labels = {
        "revenue": "Revenue",
        "employees": "Employees",
        "vertical": "Vertical",
        "techStack": "Tech Stack",
        "complexity": "Complexity",
        "dealSize": "Deal Size",
        "region": "Region"
    }

    for key, label in criteria_labels.items():
        item = breakdown.get(key, {})
        value = item.get("value", "N/A")
        weighted = item.get("weighted", 0)
        max_weighted = item.get("maxWeighted", 0)

        blocks.append({
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": f"{label}: {value} ({weighted}/{max_weighted} pts)"}
                }]
            }
        })

    # Next Steps
    if data.get("nextSteps"):
        blocks.append({
            "object": "block",
            "type": "heading_3",
            "heading_3": {
                "rich_text": [{"type": "text", "text": {"content": "Next Steps"}}]
            }
        })

        for step in data["nextSteps"]:
            blocks.append({
                "object": "block",
                "type": "to_do",
                "to_do": {
                    "rich_text": [{"type": "text", "text": {"content": step}}],
                    "checked": False
                }
            })

    # Massive Rocket Value Proposition
    blocks.append({
        "object": "block",
        "type": "divider",
        "divider": {}
    })

    blocks.append({
        "object": "block",
        "type": "heading_3",
        "heading_3": {
            "rich_text": [{"type": "text", "text": {"content": "Why Massive Rocket?"}}]
        }
    })

    blocks.append({
        "object": "block",
        "type": "quote",
        "quote": {
            "rich_text": [{
                "type": "text",
                "text": {"content": "We turn fragmented customer data and under-used data platforms into a growth engine that execs can steer and teams can run."}
            }]
        }
    })

    blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{
                "type": "text",
                "text": {"content": "Key pillars: Data Foundations • Engagement Stack • Measurement & Decisioning • Talent & Capacity"}
            }]
        }
    })

    return blocks


@app.route("/api/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "notion_available": NOTION_AVAILABLE,
        "notion_configured": bool(NOTION_API_KEY and NOTION_DATABASE_ID)
    })


@app.route("/api/config", methods=["GET"])
def get_config():
    """Return client configuration (non-sensitive)."""
    return jsonify({
        "notion_configured": bool(NOTION_API_KEY and NOTION_DATABASE_ID),
        "database_id_set": bool(NOTION_DATABASE_ID)
    })


@app.route("/api/sync-to-notion", methods=["POST"])
def sync_to_notion():
    """Sync lead qualification data to Notion."""
    try:
        if not NOTION_DATABASE_ID:
            return jsonify({
                "success": False,
                "error": "NOTION_DATABASE_ID not configured on server"
            }), 400

        data = request.json
        if not data:
            return jsonify({
                "success": False,
                "error": "No data provided"
            }), 400

        client = get_notion_client()

        # Check for existing page
        existing_page = None
        company_name = data.get("companyName", "")

        if company_name:
            try:
                response = client.databases.query(
                    database_id=NOTION_DATABASE_ID,
                    filter={
                        "property": "Company Name",
                        "title": {"equals": company_name}
                    }
                )
                if response["results"]:
                    existing_page = response["results"][0]
            except Exception as e:
                print(f"Warning: Could not search for existing page: {e}")

        properties = create_notion_properties(data)

        if existing_page:
            # Update existing page
            page = client.pages.update(
                page_id=existing_page["id"],
                properties=properties
            )
            action = "updated"
        else:
            # Create new page
            page = client.pages.create(
                parent={"database_id": NOTION_DATABASE_ID},
                properties=properties,
                children=create_notion_content(data)
            )
            action = "created"

        # Get page URL
        page_url = page.get("url", "")

        return jsonify({
            "success": True,
            "action": action,
            "page_id": page["id"],
            "page_url": page_url,
            "message": f"Successfully {action} page for {company_name}"
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/setup-database", methods=["POST"])
def setup_database():
    """Create a new Notion database with the correct schema."""
    try:
        data = request.json
        parent_page_id = data.get("parent_page_id")

        if not parent_page_id:
            return jsonify({
                "success": False,
                "error": "parent_page_id is required"
            }), 400

        client = get_notion_client()

        database = client.databases.create(
            parent={"type": "page_id", "page_id": parent_page_id},
            title=[{"type": "text", "text": {"content": "Lead Qualification Tracker"}}],
            properties={
                "Company Name": {"title": {}},
                "URL": {"url": {}},
                "ICP Score": {"number": {"format": "number"}},
                "Status": {
                    "select": {
                        "options": [
                            {"name": "Qualify In", "color": "green"},
                            {"name": "Borderline", "color": "yellow"},
                            {"name": "Qualify Out", "color": "red"}
                        ]
                    }
                },
                "Vertical": {
                    "select": {
                        "options": [
                            {"name": "QSR / Fast Food", "color": "orange"},
                            {"name": "Retail", "color": "blue"},
                            {"name": "Travel & Hospitality", "color": "purple"},
                            {"name": "Fintech", "color": "green"},
                            {"name": "Delivery", "color": "pink"},
                            {"name": "Media & Entertainment", "color": "red"},
                            {"name": "Telecom", "color": "gray"},
                            {"name": "Other", "color": "default"}
                        ]
                    }
                },
                "Revenue": {"rich_text": {}},
                "Employees": {"rich_text": {}},
                "Tech Stack": {"multi_select": {}},
                "Region": {
                    "select": {
                        "options": [
                            {"name": "NAM", "color": "blue"},
                            {"name": "EMEA", "color": "green"},
                            {"name": "APAC", "color": "purple"},
                            {"name": "Multi-Region", "color": "orange"},
                            {"name": "Global", "color": "red"}
                        ]
                    }
                },
                "Fit Summary": {"rich_text": {}},
                "Next Steps": {"rich_text": {}},
                "Qualified Date": {"date": {}},
                "Positive Signals": {"multi_select": {}},
                "Disqualifiers": {"multi_select": {}},
                "Lead Source": {"rich_text": {}},
                "Owner": {"people": {}}
            }
        )

        return jsonify({
            "success": True,
            "database_id": database["id"],
            "database_url": database.get("url", ""),
            "message": f"Database created. Set NOTION_DATABASE_ID={database['id']}"
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("Massive Rocket Lead Qualification Server")
    print("=" * 50)

    print(f"\nNotion Status:")
    print(f"  • notion-client installed: {'Yes' if NOTION_AVAILABLE else 'No'}")
    print(f"  • NOTION_API_KEY: {'Set' if NOTION_API_KEY else 'Not set'}")
    print(f"  • NOTION_DATABASE_ID: {'Set' if NOTION_DATABASE_ID else 'Not set'}")

    if not NOTION_API_KEY or not NOTION_DATABASE_ID:
        print("\n⚠️  To enable Notion sync:")
        print("  1. Create .env file with NOTION_API_KEY and NOTION_DATABASE_ID")
        print("  2. Or set environment variables")

    print("\n" + "-" * 50)
    print("Starting server at http://localhost:5000")
    print("-" * 50 + "\n")

    app.run(debug=True, port=5000)
