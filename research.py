"""
Massive Rocket Lead Research Module
Gathers company intelligence from multiple sources.
"""

import re
import json
import urllib.parse
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class CompanyData:
    """Structured company data."""
    name: str
    url: str
    description: str = ""
    revenue: str = ""
    employees: str = ""
    vertical: str = ""
    tech_stack: str = ""
    complexity: str = ""
    region: str = ""
    headquarters: str = ""
    founded: str = ""
    funding: str = ""
    news_highlights: List[str] = None
    linkedin_url: str = ""
    competitors: List[str] = None
    key_people: List[Dict] = None
    sources: List[str] = None

    def __post_init__(self):
        if self.news_highlights is None:
            self.news_highlights = []
        if self.competitors is None:
            self.competitors = []
        if self.key_people is None:
            self.key_people = []
        if self.sources is None:
            self.sources = []

    def to_dict(self):
        return asdict(self)


def extract_domain(url: str) -> str:
    """Extract clean domain from URL."""
    if not url:
        return ""
    url = url.lower().strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc.replace('www.', '')
        return domain
    except:
        return url.replace('www.', '').split('/')[0]


def clean_company_name(name: str) -> str:
    """Clean company name for search queries."""
    # Remove common suffixes
    suffixes = [' Inc', ' Inc.', ' LLC', ' Ltd', ' Ltd.', ' Limited',
                ' Corp', ' Corp.', ' Corporation', ' Co', ' Co.', ' PLC']
    cleaned = name.strip()
    for suffix in suffixes:
        if cleaned.endswith(suffix):
            cleaned = cleaned[:-len(suffix)]
    return cleaned.strip()


def build_search_queries(company_name: str, url: str) -> Dict[str, str]:
    """Build search queries for different research aspects."""
    domain = extract_domain(url)
    clean_name = clean_company_name(company_name)

    return {
        "overview": f"{clean_name} company overview",
        "revenue": f"{clean_name} revenue annual report 2024 2025",
        "employees": f"{clean_name} number of employees company size",
        "tech_stack": f"{clean_name} technology stack Braze Snowflake marketing",
        "news": f"{clean_name} news 2025 2024",
        "funding": f"{clean_name} funding valuation investors",
        "linkedin": f"site:linkedin.com/company {clean_name}",
        "crunchbase": f"site:crunchbase.com {clean_name}",
        "industry": f"{clean_name} industry vertical market segment"
    }


def parse_revenue_from_text(text: str) -> Optional[str]:
    """Extract revenue figures from text."""
    patterns = [
        r'\$[\d,.]+\s*(?:billion|bn|B)\b',
        r'\$[\d,.]+\s*(?:million|mn|M)\b',
        r'£[\d,.]+\s*(?:billion|bn|B)\b',
        r'£[\d,.]+\s*(?:million|mn|M)\b',
        r'€[\d,.]+\s*(?:billion|bn|B)\b',
        r'€[\d,.]+\s*(?:million|mn|M)\b',
        r'revenue of \$[\d,.]+\s*(?:billion|million|bn|mn|B|M)',
        r'revenues? (?:of |were |was |reached |hit )?\$[\d,.]+\s*(?:billion|million|bn|mn|B|M)?',
        r'[\d,.]+\s*(?:billion|million)\s*(?:dollars?|USD|GBP|EUR)',
    ]

    text_lower = text.lower()
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0)

    return None


def parse_employee_count_from_text(text: str) -> Optional[str]:
    """Extract employee count from text."""
    patterns = [
        r'(\d{1,3}(?:,\d{3})*)\s*(?:\+\s*)?employees',
        r'(\d{1,3}(?:,\d{3})*)\s*(?:\+\s*)?workers',
        r'(\d{1,3}(?:,\d{3})*)\s*(?:\+\s*)?staff',
        r'employs?\s*(?:over\s*|approximately\s*|about\s*|around\s*)?(\d{1,3}(?:,\d{3})*)',
        r'workforce of\s*(?:over\s*|approximately\s*)?(\d{1,3}(?:,\d{3})*)',
        r'team of\s*(?:over\s*)?(\d{1,3}(?:,\d{3})*)',
        r'(\d+(?:,\d{3})*)\s*-\s*(\d+(?:,\d{3})*)\s*employees',  # Range like "1,000-5,000 employees"
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            # Return the first captured group (or format range)
            groups = match.groups()
            if len(groups) == 2 and groups[1]:  # Range
                return f"{groups[0]}-{groups[1]}"
            return groups[0] if groups[0] else match.group(0)

    return None


def identify_vertical_from_text(text: str) -> Optional[str]:
    """Identify industry vertical from text."""
    vertical_indicators = {
        "QSR / Fast Food": ["quick service restaurant", "fast food", "qsr", "fast casual", "restaurant chain"],
        "Retail": ["retailer", "retail company", "e-commerce", "ecommerce", "online retail", "fashion retail"],
        "Travel & Hospitality": ["hotel", "hospitality", "travel company", "airline", "booking platform", "vacation"],
        "Fintech": ["fintech", "financial technology", "neobank", "digital bank", "payments company", "financial services"],
        "Delivery": ["delivery service", "food delivery", "last-mile", "logistics", "delivery platform"],
        "Convenience": ["convenience store", "c-store", "petrol station", "gas station", "convenience retail"],
        "Telecom": ["telecommunications", "telecom", "mobile carrier", "wireless provider", "mobile operator"],
        "Media & Entertainment": ["media company", "streaming", "entertainment", "gaming", "content platform"],
        "Healthcare": ["healthcare", "health tech", "medical", "pharmaceutical", "digital health"],
        "Smart Home / IoT": ["smart home", "iot", "connected devices", "home automation"],
        "SaaS / Technology": ["software company", "saas", "technology company", "tech startup", "b2b software"],
    }

    text_lower = text.lower()
    for vertical, keywords in vertical_indicators.items():
        for keyword in keywords:
            if keyword in text_lower:
                return vertical

    return None


def detect_tech_stack_from_text(text: str) -> List[str]:
    """Detect marketing/data tech stack from text."""
    tech_keywords = {
        "Braze": ["braze"],
        "Snowflake": ["snowflake"],
        "Segment": ["segment", "twilio segment"],
        "Hightouch": ["hightouch"],
        "mParticle": ["mparticle"],
        "Amplitude": ["amplitude"],
        "Mixpanel": ["mixpanel"],
        "BigQuery": ["bigquery", "google bigquery"],
        "Redshift": ["redshift", "amazon redshift"],
        "Databricks": ["databricks"],
        "Salesforce": ["salesforce", "marketing cloud"],
        "Adobe": ["adobe experience", "adobe campaign"],
        "Iterable": ["iterable"],
        "Customer.io": ["customer.io"],
        "Klaviyo": ["klaviyo"],
        "HubSpot": ["hubspot"],
        "Marketo": ["marketo"],
    }

    found_tech = []
    text_lower = text.lower()

    for tech, keywords in tech_keywords.items():
        for keyword in keywords:
            if keyword in text_lower:
                found_tech.append(tech)
                break

    return list(set(found_tech))


def detect_complexity_from_text(text: str) -> str:
    """Detect organizational complexity from text."""
    text_lower = text.lower()

    multi_brand = any(x in text_lower for x in [
        "multi-brand", "multiple brands", "brand portfolio", "family of brands",
        "portfolio of brands", "subsidiary", "subsidiaries"
    ])

    multi_market = any(x in text_lower for x in [
        "global", "international", "worldwide", "across countries",
        "multiple markets", "multi-market", "operates in", "countries"
    ])

    if multi_brand and multi_market:
        return "Multi-Brand + Multi-Market (Global)"
    elif multi_brand:
        return "Multi-Brand"
    elif multi_market:
        return "Multi-Market / International"
    elif any(x in text_lower for x in ["enterprise", "fortune 500", "ftse"]):
        return "Enterprise"
    else:
        return "Standard"


def detect_region_from_text(text: str) -> str:
    """Detect geographic region from text."""
    text_lower = text.lower()

    regions = []
    if any(x in text_lower for x in ["united states", "us-based", "american", "north america", "headquartered in us"]):
        regions.append("NAM")
    if any(x in text_lower for x in ["uk", "united kingdom", "europe", "european", "emea", "london", "britain"]):
        regions.append("EMEA")
    if any(x in text_lower for x in ["asia", "apac", "australia", "japan", "singapore", "china", "india"]):
        regions.append("APAC")
    if any(x in text_lower for x in ["latin america", "latam", "brazil", "mexico"]):
        regions.append("LATAM")

    if len(regions) > 1:
        return f"Multi-Region ({', '.join(regions)})"
    elif len(regions) == 1:
        return regions[0]
    else:
        return "Unknown"


def aggregate_research_data(
    company_name: str,
    url: str,
    search_results: Dict[str, str]
) -> CompanyData:
    """
    Aggregate research data from multiple search results.

    Args:
        company_name: Company name
        url: Company website URL
        search_results: Dict mapping query type to search result text

    Returns:
        CompanyData object with aggregated information
    """
    company = CompanyData(name=company_name, url=url)

    all_text = " ".join(search_results.values())

    # Extract structured data
    company.revenue = parse_revenue_from_text(all_text) or ""
    company.employees = parse_employee_count_from_text(all_text) or ""
    company.vertical = identify_vertical_from_text(all_text) or ""
    company.complexity = detect_complexity_from_text(all_text)
    company.region = detect_region_from_text(all_text)

    # Tech stack
    tech_found = detect_tech_stack_from_text(all_text)
    company.tech_stack = ", ".join(tech_found) if tech_found else ""

    # Track sources
    company.sources = list(search_results.keys())

    return company


def format_research_report(company: CompanyData) -> str:
    """Format company data as a research report."""
    lines = []
    lines.append(f"\n{'='*60}")
    lines.append(f"COMPANY RESEARCH REPORT")
    lines.append(f"{'='*60}")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"{'='*60}\n")

    lines.append(f"COMPANY: {company.name}")
    lines.append(f"URL: {company.url}")
    lines.append("")

    lines.append("COMPANY PROFILE:")
    lines.append("-" * 40)
    lines.append(f"  Industry:      {company.vertical or 'Unknown'}")
    lines.append(f"  Revenue:       {company.revenue or 'Unknown'}")
    lines.append(f"  Employees:     {company.employees or 'Unknown'}")
    lines.append(f"  Headquarters:  {company.headquarters or 'Unknown'}")
    lines.append(f"  Complexity:    {company.complexity or 'Unknown'}")
    lines.append(f"  Region:        {company.region or 'Unknown'}")
    lines.append("")

    lines.append("TECHNOLOGY STACK:")
    lines.append("-" * 40)
    if company.tech_stack:
        lines.append(f"  {company.tech_stack}")
    else:
        lines.append("  No marketing/data stack identified")
    lines.append("")

    if company.news_highlights:
        lines.append("RECENT NEWS:")
        lines.append("-" * 40)
        for news in company.news_highlights[:5]:
            lines.append(f"  • {news}")
        lines.append("")

    if company.sources:
        lines.append("DATA SOURCES:")
        lines.append("-" * 40)
        for source in company.sources:
            lines.append(f"  • {source}")

    return "\n".join(lines)


# Integration helper for Claude Code
def create_research_prompt(company_name: str, url: str) -> str:
    """
    Create a research prompt for Claude to gather company data.
    This can be used with Claude's web search capabilities.
    """
    queries = build_search_queries(company_name, url)

    prompt = f"""Research the company "{company_name}" ({url}) for lead qualification.

Please search for and gather the following information:

1. **Company Overview**: What does {company_name} do? What industry/vertical?
2. **Revenue**: What is their annual revenue? Look for recent financial reports.
3. **Employee Count**: How many employees do they have?
4. **Technology Stack**: Do they use Braze, Snowflake, Segment, or other marketing/data tools?
5. **Geographic Presence**: Where do they operate? Which regions/countries?
6. **Organizational Complexity**: Multi-brand? Global operations? Enterprise scale?
7. **Recent News**: Any significant announcements, funding, or changes in 2024-2025?
8. **Key People**: Who are the CMO, VP Marketing, Head of CRM, Chief Digital Officer?

Search queries to consider:
"""
    for query_type, query in queries.items():
        prompt += f"\n- {query_type}: {query}"

    return prompt


if __name__ == "__main__":
    # Test with sample data
    print("Research module loaded successfully.")
    print("\nSample search queries for 'McDonald's':")
    queries = build_search_queries("McDonald's", "mcdonalds.com")
    for qtype, query in queries.items():
        print(f"  {qtype}: {query}")
