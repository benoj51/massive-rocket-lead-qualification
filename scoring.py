"""
Massive Rocket ICP Scoring Engine
Calculates ICP scores based on company data and criteria.
"""

from config import (
    ICP_CRITERIA, MAX_WEIGHTED_SCORE, THRESHOLDS,
    HARD_DISQUALIFIERS, POSITIVE_SIGNALS, CONCERN_INDICATORS,
    QUALIFICATION_STATUS, VERTICAL_KEYWORDS, TECH_KEYWORDS
)


def parse_revenue(revenue_str):
    """Parse revenue string to numeric value."""
    if not revenue_str:
        return None

    revenue_str = str(revenue_str).lower().replace(",", "").replace(" ", "")

    multipliers = {
        'b': 1_000_000_000,
        'bn': 1_000_000_000,
        'billion': 1_000_000_000,
        'm': 1_000_000,
        'mn': 1_000_000,
        'million': 1_000_000,
        'k': 1_000,
        'thousand': 1_000
    }

    # Remove currency symbols
    for symbol in ['$', '£', '€', 'usd', 'gbp', 'eur']:
        revenue_str = revenue_str.replace(symbol, '')

    # Extract number and multiplier
    import re
    match = re.search(r'([\d.]+)\s*([a-z]*)', revenue_str)
    if match:
        number = float(match.group(1))
        suffix = match.group(2)
        multiplier = multipliers.get(suffix, 1)
        return number * multiplier

    try:
        return float(revenue_str)
    except:
        return None


def parse_employees(employee_str):
    """Parse employee count string to numeric value."""
    if not employee_str:
        return None

    employee_str = str(employee_str).lower().replace(",", "").replace(" ", "")

    # Handle ranges like "1000-5000" - take upper bound
    if "-" in employee_str:
        parts = employee_str.split("-")
        try:
            return int(parts[-1].replace("+", "").replace("k", "000"))
        except:
            pass

    # Handle "5000+" format
    employee_str = employee_str.replace("+", "")

    # Handle "5k" format
    if employee_str.endswith("k"):
        try:
            return int(float(employee_str[:-1]) * 1000)
        except:
            pass

    try:
        return int(float(employee_str))
    except:
        return None


def score_numeric_criterion(value, criterion_config):
    """Score a numeric criterion (revenue, employees, deal_size)."""
    if value is None:
        return 0, "Unknown"

    for low, high, score, label in criterion_config["thresholds"]:
        if low <= value < high:
            return score, label

    return 0, "Out of range"


def score_vertical(vertical_str):
    """Score based on industry vertical."""
    if not vertical_str:
        return ICP_CRITERIA["vertical"]["default"], "Unknown"

    vertical_lower = vertical_str.lower()
    scores = ICP_CRITERIA["vertical"]["scores"]

    # Check for exact or partial matches
    best_score = ICP_CRITERIA["vertical"]["default"]
    matched_vertical = "Other"

    for vertical, score in scores.items():
        if vertical in vertical_lower:
            if score > best_score:
                best_score = score
                matched_vertical = vertical.title()

    # Also check keyword mappings
    for category, keywords in VERTICAL_KEYWORDS.items():
        for keyword in keywords:
            if keyword in vertical_lower:
                category_score = scores.get(category, ICP_CRITERIA["vertical"]["default"])
                if category_score > best_score:
                    best_score = category_score
                    matched_vertical = category.replace("_", " ").title()

    return best_score, matched_vertical


def score_tech_stack(tech_data):
    """Score based on technology stack."""
    if not tech_data:
        return 0, "Unknown"

    tech_lower = str(tech_data).lower()

    has_braze = any(kw in tech_lower for kw in TECH_KEYWORDS["braze"])
    has_snowflake = any(kw in tech_lower for kw in TECH_KEYWORDS["snowflake"])
    has_warehouse = has_snowflake or any(
        kw in tech_lower for kw in TECH_KEYWORDS["data_warehouse"]
    )

    if has_braze and has_snowflake:
        return 3, "Braze + Snowflake"
    elif has_braze and has_warehouse:
        return 2, "Braze + Data Warehouse"
    elif has_braze:
        return 1, "Braze Only"
    else:
        return 0, "No Braze Detected"


def score_complexity(complexity_data):
    """Score based on organizational complexity."""
    if not complexity_data:
        return 1, "Unknown"

    complexity_lower = str(complexity_data).lower()

    multi_brand = any(x in complexity_lower for x in ["multi-brand", "multi brand", "multiple brands", "portfolio"])
    multi_market = any(x in complexity_lower for x in ["multi-market", "multi market", "global", "international", "multiple countries", "regions"])

    if multi_brand and multi_market:
        return 3, "Multi-Brand + Multi-Market"
    elif multi_brand:
        return 2, "Multi-Brand"
    elif multi_market:
        return 2, "Multi-Market"
    elif any(x in complexity_lower for x in ["enterprise", "large", "complex"]):
        return 2, "Enterprise"
    else:
        return 1, "Standard"


def score_region(region_data):
    """Score based on geographic region."""
    if not region_data:
        return 1, "Unknown"

    region_lower = str(region_data).lower()

    nam = any(x in region_lower for x in ["us", "usa", "united states", "north america", "canada", "nam"])
    emea = any(x in region_lower for x in ["uk", "europe", "emea", "eu", "britain", "germany", "france"])
    apac = any(x in region_lower for x in ["asia", "apac", "australia", "japan", "singapore"])

    if (nam and emea) or (nam and apac) or (emea and apac):
        return 3, "Multi-Region (NAM/EMEA/APAC)"
    elif nam or emea:
        return 2, "NAM or EMEA"
    elif apac:
        return 1, "APAC"
    else:
        return 1, "Other"


def calculate_icp_score(company_data):
    """
    Calculate complete ICP score for a company.

    Args:
        company_data: dict with keys like 'revenue', 'employees', 'vertical',
                      'tech_stack', 'complexity', 'deal_size', 'region'

    Returns:
        dict with score breakdown and total
    """
    breakdown = {}
    total_weighted = 0

    # Revenue
    revenue = parse_revenue(company_data.get("revenue"))
    score, label = score_numeric_criterion(revenue, ICP_CRITERIA["revenue"])
    weight = ICP_CRITERIA["revenue"]["weight"]
    breakdown["revenue"] = {
        "raw_score": score,
        "weight": weight,
        "weighted": score * weight,
        "value": label,
        "max_weighted": weight * 3
    }
    total_weighted += score * weight

    # Employees
    employees = parse_employees(company_data.get("employees"))
    score, label = score_numeric_criterion(employees, ICP_CRITERIA["employees"])
    weight = ICP_CRITERIA["employees"]["weight"]
    breakdown["employees"] = {
        "raw_score": score,
        "weight": weight,
        "weighted": score * weight,
        "value": label,
        "max_weighted": weight * 3
    }
    total_weighted += score * weight

    # Vertical
    score, label = score_vertical(company_data.get("vertical"))
    weight = ICP_CRITERIA["vertical"]["weight"]
    breakdown["vertical"] = {
        "raw_score": score,
        "weight": weight,
        "weighted": score * weight,
        "value": label,
        "max_weighted": weight * 3
    }
    total_weighted += score * weight

    # Tech Stack
    score, label = score_tech_stack(company_data.get("tech_stack"))
    weight = ICP_CRITERIA["tech_stack"]["weight"]
    breakdown["tech_stack"] = {
        "raw_score": score,
        "weight": weight,
        "weighted": score * weight,
        "value": label,
        "max_weighted": weight * 3
    }
    total_weighted += score * weight

    # Complexity
    score, label = score_complexity(company_data.get("complexity"))
    weight = ICP_CRITERIA["complexity"]["weight"]
    breakdown["complexity"] = {
        "raw_score": score,
        "weight": weight,
        "weighted": score * weight,
        "value": label,
        "max_weighted": weight * 3
    }
    total_weighted += score * weight

    # Deal Size (estimated)
    deal_size = parse_revenue(company_data.get("deal_size"))
    if deal_size:
        score, label = score_numeric_criterion(deal_size, ICP_CRITERIA["deal_size"])
    else:
        score, label = 1, "Estimated"  # Default estimate
    weight = ICP_CRITERIA["deal_size"]["weight"]
    breakdown["deal_size"] = {
        "raw_score": score,
        "weight": weight,
        "weighted": score * weight,
        "value": label,
        "max_weighted": weight * 3
    }
    total_weighted += score * weight

    # Region
    score, label = score_region(company_data.get("region"))
    weight = ICP_CRITERIA["region"]["weight"]
    breakdown["region"] = {
        "raw_score": score,
        "weight": weight,
        "weighted": score * weight,
        "value": label,
        "max_weighted": weight * 3
    }
    total_weighted += score * weight

    # Normalize to 10-point scale
    normalized_score = round((total_weighted / MAX_WEIGHTED_SCORE) * 10, 1)

    # Determine qualification status
    if normalized_score >= THRESHOLDS["qualify_in"]:
        status = "qualify_in"
    elif normalized_score >= THRESHOLDS["borderline_low"]:
        status = "borderline"
    else:
        status = "qualify_out"

    return {
        "total_weighted": total_weighted,
        "max_weighted": MAX_WEIGHTED_SCORE,
        "normalized_score": normalized_score,
        "status": status,
        "status_display": QUALIFICATION_STATUS[status],
        "breakdown": breakdown
    }


def check_hard_disqualifiers(company_data):
    """Check for hard disqualifiers."""
    disqualifiers = []

    revenue = parse_revenue(company_data.get("revenue"))
    if revenue and revenue < 50_000_000:
        disqualifiers.append("Revenue under $50M")

    employees = parse_employees(company_data.get("employees"))
    if employees and employees < 200:
        disqualifiers.append("Employee count under 200")

    tech_stack = str(company_data.get("tech_stack", "")).lower()
    if "no braze" in tech_stack or company_data.get("no_braze"):
        disqualifiers.append("No Braze and no plans to adopt")

    return disqualifiers


def identify_positive_signals(company_data):
    """Identify positive qualification signals."""
    signals = []

    incumbent = str(company_data.get("incumbent_agency", "")).lower()
    if "merkle" in incumbent or "accenture" in incumbent:
        signals.append("Incumbent agency is Merkle or Accenture")

    tech_stack = str(company_data.get("tech_stack", "")).lower()
    if "braze" in tech_stack and "snowflake" in tech_stack:
        signals.append("Braze + Snowflake already in stack")

    source = str(company_data.get("source", "")).lower()
    if "braze" in source or "hightouch" in source or "referral" in source:
        signals.append("Referred by Braze/Hightouch partner team")

    if company_data.get("rfp_active"):
        signals.append("Active RFP in progress")

    if company_data.get("budget_allocated"):
        signals.append("Budget already allocated")

    return signals


def generate_score_summary(result):
    """Generate a formatted score summary."""
    lines = []
    lines.append(f"\n{'='*60}")
    lines.append(f"ICP SCORE: {result['normalized_score']}/10 {result['status_display']}")
    lines.append(f"{'='*60}\n")

    lines.append("SCORE BREAKDOWN:")
    lines.append("-" * 40)

    for criterion, data in result["breakdown"].items():
        criterion_name = criterion.replace("_", " ").title()
        lines.append(
            f"  {criterion_name:15} | {data['value']:25} | "
            f"{data['weighted']}/{data['max_weighted']} pts"
        )

    lines.append("-" * 40)
    lines.append(f"  {'TOTAL':15} | {'':<25} | {result['total_weighted']}/{result['max_weighted']} pts")
    lines.append(f"\n  Normalized Score: {result['normalized_score']}/10")

    return "\n".join(lines)


if __name__ == "__main__":
    # Test with sample data
    test_company = {
        "revenue": "$2.5B",
        "employees": "8000",
        "vertical": "Quick Service Restaurant",
        "tech_stack": "Braze, Snowflake, Segment",
        "complexity": "Multi-brand, global presence",
        "deal_size": "£60k/month",
        "region": "US, UK, Europe"
    }

    result = calculate_icp_score(test_company)
    print(generate_score_summary(result))

    disqualifiers = check_hard_disqualifiers(test_company)
    if disqualifiers:
        print("\nHARD DISQUALIFIERS:")
        for d in disqualifiers:
            print(f"  ❌ {d}")

    signals = identify_positive_signals(test_company)
    if signals:
        print("\nPOSITIVE SIGNALS:")
        for s in signals:
            print(f"  ✓ {s}")
