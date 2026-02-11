"""
Massive Rocket Company Research Server
Uses web search to gather company intelligence for lead qualification.

This server provides AI-powered company research via the Anthropic API.

Setup:
    pip install flask flask-cors anthropic python-dotenv

    Add to your .env file:
        ANTHROPIC_API_KEY=your-anthropic-api-key

Run:
    python research_server.py
"""

import os
import json
import re
from flask import Flask, request, jsonify
from flask_cors import CORS

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Try to import anthropic
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    print("Warning: anthropic not installed. Run: pip install anthropic")

app = Flask(__name__)
CORS(app)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")


def research_company(company_name: str, company_url: str = None) -> dict:
    """
    Research a company using Claude with web search.

    Returns structured data about the company.
    """
    if not ANTHROPIC_AVAILABLE:
        raise Exception("anthropic package not installed. Run: pip install anthropic")

    if not ANTHROPIC_API_KEY:
        raise Exception("ANTHROPIC_API_KEY not set in environment")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Build the research prompt
    url_hint = f" (website: {company_url})" if company_url else ""

    prompt = f"""Research the company "{company_name}"{url_hint} and provide the following information in JSON format:

{{
    "company_name": "Official company name",
    "description": "Brief 1-2 sentence description of what they do",
    "revenue": "Annual revenue estimate (e.g., '$2.5B', '$500M', 'Unknown')",
    "revenue_source": "Where this revenue figure comes from (e.g., '2024 annual report', 'Forbes estimate')",
    "employees": "Employee count estimate (e.g., '5000', '1000-5000', 'Unknown')",
    "employees_source": "Source for employee count",
    "vertical": "Primary industry vertical (choose from: QSR, Retail, Travel & Hospitality, Fintech, Delivery, Convenience, Telecom, Media & Entertainment, Healthcare, SaaS/Technology, Manufacturing, Other)",
    "headquarters": "HQ location (city, country)",
    "regions": "Regions of operation (e.g., 'Global', 'North America', 'US and Europe')",
    "tech_stack": "Known marketing/data technology (e.g., 'Braze, Snowflake, Segment' or 'Unknown')",
    "tech_stack_source": "How tech stack was determined",
    "complexity": "Organizational complexity assessment (Multi-brand + Multi-market, Multi-brand, Multi-market, Enterprise, Single brand)",
    "notable_info": "Any other relevant information for B2B sales qualification",
    "confidence": "High/Medium/Low - how confident are you in this data"
}}

Important:
- Use current, accurate data
- If you cannot find reliable information for a field, use "Unknown"
- For revenue and employees, provide your best estimate with the source
- Be specific about where data comes from

Return ONLY the JSON object, no other text."""

    try:
        # Use Claude with web search enabled
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        # Extract the response text
        response_text = response.content[0].text

        # Parse JSON from response
        # Try to find JSON in the response
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            data = json.loads(json_match.group())
            return {
                "success": True,
                "data": data
            }
        else:
            return {
                "success": False,
                "error": "Could not parse research results",
                "raw_response": response_text
            }

    except json.JSONDecodeError as e:
        return {
            "success": False,
            "error": f"Failed to parse JSON: {str(e)}",
            "raw_response": response_text if 'response_text' in locals() else None
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@app.route("/api/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "anthropic_available": ANTHROPIC_AVAILABLE,
        "anthropic_configured": bool(ANTHROPIC_API_KEY)
    })


@app.route("/api/research", methods=["POST"])
def research_endpoint():
    """Research a company and return structured data."""
    try:
        data = request.json
        if not data:
            return jsonify({
                "success": False,
                "error": "No data provided"
            }), 400

        company_name = data.get("company_name")
        company_url = data.get("company_url")

        if not company_name:
            return jsonify({
                "success": False,
                "error": "company_name is required"
            }), 400

        result = research_company(company_name, company_url)
        return jsonify(result)

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/research/config", methods=["GET"])
def research_config():
    """Return research configuration status."""
    return jsonify({
        "research_available": ANTHROPIC_AVAILABLE and bool(ANTHROPIC_API_KEY),
        "api_configured": bool(ANTHROPIC_API_KEY)
    })


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("Massive Rocket Company Research Server")
    print("=" * 50)

    print(f"\nAnthropic API Status:")
    print(f"  • anthropic package installed: {'Yes' if ANTHROPIC_AVAILABLE else 'No'}")
    print(f"  • ANTHROPIC_API_KEY: {'Set' if ANTHROPIC_API_KEY else 'Not set'}")

    if not ANTHROPIC_API_KEY:
        print("\n⚠️  To enable AI research:")
        print("  1. Add ANTHROPIC_API_KEY to your .env file")
        print("  2. Or set the environment variable")

    print("\n" + "-" * 50)
    print("Starting server at http://localhost:5001")
    print("-" * 50 + "\n")

    app.run(debug=True, port=5001)
