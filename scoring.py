"""
Massive Rocket ICP Scoring Engine
Calculates ICP scores based on company data and criteria.

Updated 7 April 2026: Recalibrated vertical tiers, strict tech stack
scoring (0 for unknown/speculated), opportunity type classification.
"""

from config import (
    ICP_CRITERIA, MAX_WEIGHTED_SCORE, THRESHOLDS,
    HARD_DISQUALIFIERS, POSITIVE_SIGNALS, CONCERN_INDICATORS,
    QUALIFICATION_STATUS, VERTICAL_KEYWORDS, TECH_KEYWORDS,
    OPPORTUNITY_TYPES
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

    # Handle ranges like "1000-5000" -- take upper bound
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
    """
    Score based on industry vertical.

    Uses direct weighted scores (out of 9) calibrated to MR's
    actual delivery depth and win rate:
      Tier 1 (9/9): QSR, Roadside Convenience
      Tier 2 (7/9): Delivery, C-store / Convenience
      Tier 3 (6/9): Retail, Travel & Hospitality
      Tier 4 (5/9): Fintech, Telecom
      Tier 5 (3/9): Everything else
    """
    tiers = ICP_CRITERIA["vertical"]["tiers"]
    default = ICP_CRITERIA["vertical"]["default"]

    if not vertical_str:
        return default, "Unknown", default

    vertical_lower = vertical_str.lower()

    # Check for direct matches in tier table
    best_weighted = default
    matched_vertical = "Other"

    for vertical, weighted_score in tiers.items():
        if vertical in vertical_lower:
            if weighted_score > best_weighted:
                best_weighted = weighted_score
                matched_vertical = vertical.replace("_", " ").title()

    # Also check keyword mappings for fuzzy matches
    keyword_to_tier = {
        "qsr": 9, "roadside_convenience": 9,
        "delivery": 7, "convenience": 7,
        "retail": 6, "travel": 6,
        "fintech": 5, "telecom": 5,
        "media": 3, "healthcare": 3, "smart_home": 3,
    }
    for category, keywords in VERTICAL_KEYWORDS.items():
        for keyword in keywords:
            if keyword in vertical_lower:
                cat_weighted = keyword_to_tier.get(category, default)
                if cat_weighted > best_weighted:
                    best_weighted = cat_weighted
                    matched_vertical = category.replace("_", " ").title()

    return best_weighted, matched_vertical, best_weighted


def classify_opportunity_type(tech_data, stack_confidence="confirmed"):
    """
    Classify the opportunity type based on confirmed tech stack.

    Returns: (type_key, label, description)
    """
    if not tech_data or stack_confidence in ("unknown", "speculated", "inferred"):
        return "unknown", "Unknown", "Tech stack not confirmed"

    tech_lower = str(tech_data).lower()

    has_braze = any(kw in tech_lower for kw in TECH_KEYWORDS["braze"])
    has_snowflake = any(kw in tech_lower for kw in TECH_KEYWORDS["snowflake"])
    has_warehouse = has_snowflake or any(
        kw in tech_lower for kw in TECH_KEYWORDS["data_warehouse"]
    )
    has_hightouch = any(kw in tech_lower for kw in TECH_KEYWORDS["hightouch"])

    # Check for competitor CEPs
    competitor_ceps = ICP_CRITERIA["tech_stack"].get("competitor_ceps", [])
    has_competitor = any(cep in tech_lower for cep in competitor_ceps)

    if has_braze and has_snowflake:
        return "retention", "Retention", "Braze + Snowflake confirmed"
    elif has_braze and has_warehouse:
        return "retention_light", "Retention Light", "Braze + warehouse confirmed"
    elif has_braze:
        return "augmentation", "Augmentation", "Braze only, needs data layer"
    elif has_competitor and has_warehouse:
        return "migration", "Migration", f"Competitor CEP + warehouse"
    elif has_competitor:
        return "migration", "Migration", "Competitor CEP, potential Braze migration"
    elif has_warehouse or has_hightouch:
        return "greenfield", "Greenfield", "Data infrastructure but no CEP"
    else:
        return "greenfield", "Greenfield", "No relevant marketing stack detected"


def score_tech_stack(tech_data, stack_confidence="confirmed"):
    """
    Score based on technology stack.

    Uses direct weighted scores (out of 9).
    STRICT RULE: Unknown or speculated stack = 0/9.

    Scores:
      Retention (Braze + Snowflake confirmed):    9/9
      Retention Light (Braze + other warehouse):  7/9
      Migration (competitor CEP + warehouse):     5/9
      Augmentation (Braze only):                  4/9
      Greenfield (no relevant stack):             2/9
      Unknown/Speculated:                         0/9
    """
    opp_scores = ICP_CRITERIA["tech_stack"]["opportunity_scores"]

    # STRICT: Unknown or speculated tech stack = 0
    if not tech_data:
        return 0, "Unknown", 0
    if stack_confidence in ("unknown", "speculated", "inferred"):
        return 0, "Unconfirmed (scored as 0)", 0

    opp_type, opp_label, opp_desc = classify_opportunity_type(
        tech_data, stack_confidence
    )

    weighted_score = opp_scores.get(opp_type, 0)
    label = f"{opp_label}: {opp_desc}"

    return weighted_score, label, weighted_score


def score_complexity(complexity_data):
    """Score based on organisational complexity."""
    if not complexity_data:
        return 1, "Unknown"

    complexity_lower = str(complexity_data).lower()

    multi_brand = any(x in complexity_lower for x in [
        "multi-brand", "multi brand", "multiple brands", "portfolio"
    ])
    multi_market = any(x in complexity_lower for x in [
        "multi-market", "multi market", "global", "international",
        "multiple countries", "regions"
    ])

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

    nam = any(x in region_lower for x in [
        "us", "usa", "united states", "north america", "canada", "nam"
    ])
    emea = any(x in region_lower for x in [
        "uk", "europe", "emea", "eu", "britain", "germany", "france"
    ])
    apac = any(x in region_lower for x in [
        "asia", "apac", "australia", "japan", "singapore"
    ])

    is_global = "global" in region_lower

    if is_global or (nam and emea) or (nam and apac) or (emea and apac):
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
                      'tech_stack', 'complexity', 'deal_size', 'region',
                      'stack_confidence' (optional, defaults to 'confirmed')

    Returns:
        dict with score breakdown, total, opportunity type
    """
    breakdown = {}
    total_weighted = 0
    stack_confidence = company_data.get("stack_confidence", "confirmed")

    # Revenue (standard: raw * weight)
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

    # Employees (standard: raw * weight)
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

    # Vertical (DIRECT weighted score out of 9)
    weighted_v, label_v, _ = score_vertical(company_data.get("vertical"))
    weight = ICP_CRITERIA["vertical"]["weight"]
    breakdown["vertical"] = {
        "raw_score": round(weighted_v / weight, 2),
        "weight": weight,
        "weighted": weighted_v,
        "value": label_v,
        "max_weighted": weight * 3
    }
    total_weighted += weighted_v

    # Tech Stack (DIRECT weighted score out of 9)
    weighted_t, label_t, _ = score_tech_stack(
        company_data.get("tech_stack"), stack_confidence
    )
    weight = ICP_CRITERIA["tech_stack"]["weight"]
    breakdown["tech_stack"] = {
        "raw_score": round(weighted_t / weight, 2),
        "weight": weight,
        "weighted": weighted_t,
        "value": label_t,
        "max_weighted": weight * 3
    }
    total_weighted += weighted_t

    # Complexity (standard: raw * weight)
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

    # Deal Size (standard: raw * weight)
    deal_size = parse_revenue(company_data.get("deal_size"))
    if deal_size:
        score, label = score_numeric_criterion(deal_size, ICP_CRITERIA["deal_size"])
    else:
        score, label = 1, "Estimated"
    weight = ICP_CRITERIA["deal_size"]["weight"]
    breakdown["deal_size"] = {
        "raw_score": score,
        "weight": weight,
        "weighted": score * weight,
        "value": label,
        "max_weighted": weight * 3
    }
    total_weighted += score * weight

    # Region (standard: raw * weight)
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

    # Normalise to 10-point scale
    normalized_score = round((total_weighted / MAX_WEIGHTED_SCORE) * 10, 1)

    # Determine qualification status
    if normalized_score >= THRESHOLDS["qualify_in"]:
        status = "qualify_in"
    elif normalized_score >= THRESHOLDS["borderline_low"]:
        status = "borderline"
    else:
        status = "qualify_out"

    # Classify opportunity type
    opp_type, opp_label, opp_desc = classify_opportunity_type(
        company_data.get("tech_stack"), stack_confidence
    )

    return {
        "total_weighted": total_weighted,
        "max_weighted": MAX_WEIGHTED_SCORE,
        "normalized_score": normalized_score,
        "status": status,
        "status_display": QUALIFICATION_STATUS[status],
        "breakdown": breakdown,
        "opportunity_type": opp_type,
        "opportunity_label": opp_label,
        "opportunity_description": opp_desc,
    }


def apply_hard_disqualifier_status(score, disqualifiers):
    """A hard disqualifier is an automatic Qualify Out, regardless of the
    numeric ICP score (PRD section 9). The raw score keeps the numbers, but
    status / status_display are forced to qualify_out so the verdict, the
    next-steps guidance, and the Notion status all agree. Without this a
    high-scoring but disqualified lead synced to Notion as "Qualified".

    Mutates and returns the score dict. No-op when there are no
    disqualifiers or status is already qualify_out.
    """
    if disqualifiers and score.get("status") != "qualify_out":
        score["status"] = "qualify_out"
        score["status_display"] = QUALIFICATION_STATUS["qualify_out"]
        score["status_forced_by_disqualifier"] = True
    return score


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
    stack_confidence = company_data.get("stack_confidence", "confirmed")

    if stack_confidence == "confirmed":
        if "braze" in tech_stack and "snowflake" in tech_stack:
            signals.append("Braze + Snowflake already in stack (confirmed)")
        elif "braze" in tech_stack:
            signals.append("Braze already in stack (confirmed)")

    source = str(company_data.get("source", "")).lower()
    if "braze" in source or "hightouch" in source or "referral" in source:
        signals.append("Referred by Braze/Hightouch partner team")

    if company_data.get("rfp_active"):
        signals.append("Active RFP in progress")

    if company_data.get("budget_allocated"):
        signals.append("Budget already allocated")

    if stack_confidence in ("unknown", "speculated", "inferred"):
        signals.append("WARNING: Tech stack unconfirmed, scored as 0/9")

    return signals


def generate_score_summary(result):
    """Generate a formatted score summary."""
    lines = []
    lines.append(f"\n{'='*60}")
    lines.append(f"ICP SCORE: {result['normalized_score']}/10 {result['status_display']}")
    lines.append(f"Opportunity Type: {result['opportunity_label']} -- {result['opportunity_description']}")
    lines.append(f"{'='*60}\n")

    lines.append("SCORE BREAKDOWN:")
    lines.append("-" * 50)

    for criterion, data in result["breakdown"].items():
        criterion_name = criterion.replace("_", " ").title()
        lines.append(
            f"  {criterion_name:15} | {data['value']:30} | "
            f"{data['weighted']}/{data['max_weighted']} pts"
        )

    lines.append("-" * 50)
    lines.append(
        f"  {'TOTAL':15} | {'':<30} | "
        f"{result['total_weighted']}/{result['max_weighted']} pts"
    )
    lines.append(f"\n  Normalised Score: {result['normalized_score']}/10")

    return "\n".join(lines)


if __name__ == "__main__":
    # Test: Havaianas (should score ~33-34/51 with actual stack)
    print("=" * 60)
    print("TEST: Havaianas (Migration opportunity)")
    print("=" * 60)
    havaianas = {
        "revenue": "$800M",
        "employees": "3000",
        "vertical": "Retail",
        "tech_stack": "Salesforce Marketing Cloud, Databricks, Klaviyo",
        "complexity": "Multi-market, global presence",
        "deal_size": "£40k/month",
        "region": "Brazil, Latin America",
        "stack_confidence": "confirmed",
    }
    result = calculate_icp_score(havaianas)
    # Expected: ~33-34/51 = 6.5-6.7/10 (Borderline)
    print(generate_score_summary(result))
    disq = check_hard_disqualifiers(havaianas)
    if disq:
        print("\nHARD DISQUALIFIERS:")
        for d in disq:
            print(f"  X {d}")
    signals = identify_positive_signals(havaianas)
    if signals:
        print("\nPOSITIVE SIGNALS:")
        for s in signals:
            print(f"  > {s}")

    # Test: Deliveroo (Retention play)
    print("\n" + "=" * 60)
    print("TEST: Deliveroo (Retention play)")
    print("=" * 60)
    deliveroo = {
        "revenue": "£1.98B",
        "employees": "3700",
        "vertical": "Food Delivery",
        "tech_stack": "Braze, Snowflake, AWS, Segment",
        "complexity": "Multi-market, 10+ countries",
        "deal_size": "£55k/month",
        "region": "UK, Europe, Singapore, Hong Kong, UAE",
        "stack_confidence": "confirmed",
    }
    result = calculate_icp_score(deliveroo)
    print(generate_score_summary(result))

    # Test: Unknown stack penalty
    print("\n" + "=" * 60)
    print("TEST: Unknown Tech Stack (should score 0/9 for stack)")
    print("=" * 60)
    unknown = {
        "revenue": "$2B",
        "employees": "5000",
        "vertical": "QSR",
        "tech_stack": "Braze, Snowflake",  # Even if text says Braze...
        "complexity": "Multi-brand",
        "deal_size": "£60k/month",
        "region": "US, UK",
        "stack_confidence": "inferred",  # ...inferred = 0
    }
    result = calculate_icp_score(unknown)
    print(generate_score_summary(result))
