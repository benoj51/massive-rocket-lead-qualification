"""
Massive Rocket Notion Sync Module
Syncs lead qualification data to Notion database.

Setup:
1. Create a Notion integration at https://www.notion.so/my-integrations
2. Share your database with the integration
3. Set NOTION_API_KEY environment variable
4. Set NOTION_DATABASE_ID environment variable (or pass as argument)

Database Schema (recommended):
- Company Name (title)
- URL (url)
- ICP Score (number)
- Status (select: Qualify In, Borderline, Qualify Out)
- Vertical (select)
- Revenue (text)
- Employees (text)
- Tech Stack (multi-select)
- Region (select)
- Fit Summary (text)
- Next Steps (text)
- Qualified Date (date)
- Positive Signals (multi-select)
- Disqualifiers (multi-select)
"""

import os
import json
from datetime import datetime
from typing import Dict, Any, Optional, List

# Try to import notion-client, provide helpful error if not available
try:
    from notion_client import Client
    NOTION_AVAILABLE = True
except ImportError:
    NOTION_AVAILABLE = False


class NotionSync:
    """Handles syncing lead qualification data to Notion."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        database_id: Optional[str] = None
    ):
        """
        Initialize Notion sync.

        Args:
            api_key: Notion API key (or set NOTION_API_KEY env var)
            database_id: Notion database ID (or set NOTION_DATABASE_ID env var)
        """
        if not NOTION_AVAILABLE:
            raise ImportError(
                "notion-client not installed. Run: pip install notion-client"
            )

        self.api_key = api_key or os.environ.get("NOTION_API_KEY")
        self.database_id = database_id or os.environ.get("NOTION_DATABASE_ID")

        if not self.api_key:
            raise ValueError(
                "Notion API key required. Set NOTION_API_KEY environment variable "
                "or pass api_key parameter."
            )

        if not self.database_id:
            raise ValueError(
                "Notion database ID required. Set NOTION_DATABASE_ID environment "
                "variable or pass database_id parameter."
            )

        self.client = Client(auth=self.api_key)

    def create_page_properties(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Convert qualification result to Notion page properties."""
        company = result.get("company", {})
        icp = result.get("icp_score", {})
        qual = result.get("qualification", {})
        analysis = result.get("analysis", {})
        data = result.get("data", {})

        # Map status to Notion select values
        status_map = {
            "qualify_in": "Qualify In",
            "borderline": "Borderline",
            "qualify_out": "Qualify Out"
        }

        properties = {
            # Title (Company Name)
            "Company Name": {
                "title": [{"text": {"content": company.get("name", "Unknown")}}]
            },
            # URL
            "URL": {
                "url": company.get("url", "")
            },
            # ICP Score (number)
            "ICP Score": {
                "number": icp.get("score", 0)
            },
            # Status (select)
            "Status": {
                "select": {"name": status_map.get(qual.get("status"), "Unknown")}
            },
            # Qualified Date
            "Qualified Date": {
                "date": {"start": datetime.now().isoformat()[:10]}
            }
        }

        # Optional fields (only add if data exists)
        if data.get("vertical"):
            properties["Vertical"] = {
                "select": {"name": data["vertical"]}
            }

        if data.get("revenue"):
            properties["Revenue"] = {
                "rich_text": [{"text": {"content": data["revenue"]}}]
            }

        if data.get("employees"):
            properties["Employees"] = {
                "rich_text": [{"text": {"content": str(data["employees"])}}]
            }

        if data.get("tech_stack"):
            # Multi-select for tech stack
            tech_list = [t.strip() for t in data["tech_stack"].split(",") if t.strip()]
            properties["Tech Stack"] = {
                "multi_select": [{"name": tech} for tech in tech_list[:10]]  # Limit to 10
            }

        if data.get("region"):
            properties["Region"] = {
                "select": {"name": data["region"]}
            }

        if analysis.get("fit_summary"):
            # Truncate to 2000 chars for Notion
            summary = analysis["fit_summary"][:2000]
            properties["Fit Summary"] = {
                "rich_text": [{"text": {"content": summary}}]
            }

        if analysis.get("next_steps"):
            steps_text = "\n".join(f"• {step}" for step in analysis["next_steps"])[:2000]
            properties["Next Steps"] = {
                "rich_text": [{"text": {"content": steps_text}}]
            }

        if qual.get("positive_signals"):
            properties["Positive Signals"] = {
                "multi_select": [
                    {"name": signal[:100]} for signal in qual["positive_signals"][:5]
                ]
            }

        if qual.get("hard_disqualifiers"):
            properties["Disqualifiers"] = {
                "multi_select": [
                    {"name": dq[:100]} for dq in qual["hard_disqualifiers"][:5]
                ]
            }

        return properties

    def create_page_content(self, result: Dict[str, Any]) -> List[Dict]:
        """Create Notion page content blocks."""
        company = result.get("company", {})
        icp = result.get("icp_score", {})
        qual = result.get("qualification", {})
        analysis = result.get("analysis", {})

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
        score = icp.get("score", 0)
        status = qual.get("status_display", "Unknown")
        blocks.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{"type": "text", "text": {"content": f"ICP Score: {score}/10 — {status}"}}],
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

        breakdown = icp.get("breakdown", {})
        for criterion, data in breakdown.items():
            name = criterion.replace("_", " ").title()
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{
                        "type": "text",
                        "text": {"content": f"{name}: {data.get('value', 'N/A')} ({data.get('weighted', 0)}/{data.get('max_weighted', 0)} pts)"}
                    }]
                }
            })

        # Fit Analysis
        if analysis.get("fit_summary"):
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {
                    "rich_text": [{"type": "text", "text": {"content": "Fit Analysis"}}]
                }
            })
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": analysis["fit_summary"]}}]
                }
            })

        # Next Steps
        if analysis.get("next_steps"):
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {
                    "rich_text": [{"type": "text", "text": {"content": "Next Steps"}}]
                }
            })
            for step in analysis["next_steps"]:
                blocks.append({
                    "object": "block",
                    "type": "to_do",
                    "to_do": {
                        "rich_text": [{"type": "text", "text": {"content": step}}],
                        "checked": False
                    }
                })

        # Stakeholder Targets
        if analysis.get("stakeholder_targets"):
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {
                    "rich_text": [{"type": "text", "text": {"content": "Stakeholder Targets"}}]
                }
            })
            for target in analysis["stakeholder_targets"][:5]:
                blocks.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [{
                            "type": "text",
                            "text": {"content": f"{target['role']} [{target['priority']}] - {target['why']}"}
                        }]
                    }
                })

        return blocks

    def sync(self, result: Dict[str, Any], update_existing: bool = True) -> Dict:
        """
        Sync qualification result to Notion.

        Args:
            result: Qualification result from qualify_lead()
            update_existing: If True, update existing page; if False, always create new

        Returns:
            Notion page object
        """
        company_name = result.get("company", {}).get("name", "")
        url = result.get("company", {}).get("url", "")

        # Check for existing page
        existing_page = None
        if update_existing and (company_name or url):
            existing_page = self._find_existing_page(company_name, url)

        properties = self.create_page_properties(result)

        if existing_page:
            # Update existing page
            page = self.client.pages.update(
                page_id=existing_page["id"],
                properties=properties
            )
            print(f"✓ Updated existing Notion page: {company_name}")
        else:
            # Create new page
            page = self.client.pages.create(
                parent={"database_id": self.database_id},
                properties=properties,
                children=self.create_page_content(result)
            )
            print(f"✓ Created new Notion page: {company_name}")

        return page

    def _find_existing_page(
        self,
        company_name: str,
        url: str
    ) -> Optional[Dict]:
        """Find existing page by company name or URL."""
        try:
            # Search by company name
            response = self.client.databases.query(
                database_id=self.database_id,
                filter={
                    "property": "Company Name",
                    "title": {"equals": company_name}
                }
            )

            if response["results"]:
                return response["results"][0]

            # Search by URL if name didn't match
            if url:
                response = self.client.databases.query(
                    database_id=self.database_id,
                    filter={
                        "property": "URL",
                        "url": {"equals": url}
                    }
                )

                if response["results"]:
                    return response["results"][0]

        except Exception as e:
            print(f"Warning: Could not search for existing page: {e}")

        return None


def sync_to_notion(
    result: Dict[str, Any],
    api_key: Optional[str] = None,
    database_id: Optional[str] = None
) -> Dict:
    """
    Convenience function to sync qualification result to Notion.

    Args:
        result: Qualification result from qualify_lead()
        api_key: Notion API key (optional, uses env var if not provided)
        database_id: Notion database ID (optional, uses env var if not provided)

    Returns:
        Notion page object
    """
    syncer = NotionSync(api_key=api_key, database_id=database_id)
    return syncer.sync(result)


def setup_database(api_key: Optional[str] = None, parent_page_id: Optional[str] = None) -> str:
    """
    Create a new Notion database with the correct schema.

    Args:
        api_key: Notion API key
        parent_page_id: Parent page to create database under

    Returns:
        Database ID
    """
    if not NOTION_AVAILABLE:
        raise ImportError("notion-client not installed. Run: pip install notion-client")

    api_key = api_key or os.environ.get("NOTION_API_KEY")
    if not api_key:
        raise ValueError("Notion API key required")

    if not parent_page_id:
        raise ValueError("Parent page ID required to create database")

    client = Client(auth=api_key)

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

    print(f"✓ Created Notion database: {database['id']}")
    print(f"  Set NOTION_DATABASE_ID={database['id']}")

    return database["id"]


if __name__ == "__main__":
    print("Notion Sync Module")
    print("-" * 40)

    if not NOTION_AVAILABLE:
        print("⚠️  notion-client not installed")
        print("   Run: pip install notion-client")
    else:
        print("✓ notion-client is available")

    api_key = os.environ.get("NOTION_API_KEY")
    db_id = os.environ.get("NOTION_DATABASE_ID")

    print(f"\nEnvironment:")
    print(f"  NOTION_API_KEY: {'✓ Set' if api_key else '✗ Not set'}")
    print(f"  NOTION_DATABASE_ID: {'✓ Set' if db_id else '✗ Not set'}")

    if not api_key:
        print("\nTo set up Notion integration:")
        print("  1. Go to https://www.notion.so/my-integrations")
        print("  2. Create a new integration")
        print("  3. Copy the API key")
        print("  4. Run: export NOTION_API_KEY='your-key-here'")

    if not db_id:
        print("\nTo set up the database:")
        print("  1. Create a new page in Notion")
        print("  2. Share it with your integration")
        print("  3. Run: python notion_sync.py --setup <parent-page-id>")
