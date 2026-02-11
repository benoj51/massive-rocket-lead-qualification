"""
Massive Rocket ICP Configuration
Defines scoring criteria, weights, and thresholds for lead qualification.
"""

# ICP Scoring Criteria with weights
ICP_CRITERIA = {
    "revenue": {
        "weight": 3,
        "thresholds": [
            (0, 100_000_000, 0, "<$100M"),
            (100_000_000, 500_000_000, 1, "$100M-$500M"),
            (500_000_000, 1_000_000_000, 2, "$500M-$1B"),
            (1_000_000_000, float('inf'), 3, ">$1B")
        ]
    },
    "employees": {
        "weight": 2,
        "thresholds": [
            (0, 500, 0, "<500"),
            (500, 1500, 1, "500-1,500"),
            (1500, 3000, 2, "1,500-3,000"),
            (3000, float('inf'), 3, "3,000+")
        ]
    },
    "vertical": {
        "weight": 3,
        "scores": {
            "qsr": 3,
            "quick service restaurant": 3,
            "fast food": 3,
            "retail": 3,
            "e-commerce": 3,
            "ecommerce": 3,
            "travel": 3,
            "hospitality": 3,
            "hotel": 3,
            "airline": 3,
            "fintech": 3,
            "financial services": 3,
            "banking": 3,
            "delivery": 3,
            "food delivery": 3,
            "convenience": 3,
            "grocery": 2,
            "telecom": 2,
            "telecommunications": 2,
            "media": 2,
            "entertainment": 2,
            "gaming": 2,
            "healthcare": 2,
            "insurance": 2,
            "smart home": 2,
            "iot": 2,
            "saas": 1,
            "technology": 1,
            "software": 1,
            "manufacturing": 1,
            "automotive": 1,
            "education": 0,
            "government": 0,
            "nonprofit": 0
        },
        "default": 1
    },
    "tech_stack": {
        "weight": 3,
        "scores": {
            "braze_snowflake": 3,
            "braze_warehouse": 2,
            "braze_only": 1,
            "no_braze": 0
        }
    },
    "complexity": {
        "weight": 2,
        "scores": {
            "multi_brand_multi_market": 3,
            "multi_brand": 2,
            "multi_market": 2,
            "single": 1,
            "simple": 0
        }
    },
    "deal_size": {
        "weight": 3,
        "thresholds": [
            (0, 10_000, 0, "<£10k/mo"),
            (10_000, 30_000, 1, "£10k-£30k/mo"),
            (30_000, 50_000, 2, "£30k-£50k/mo"),
            (50_000, float('inf'), 3, ">£50k/mo")
        ]
    },
    "region": {
        "weight": 1,
        "scores": {
            "nam_emea": 3,
            "multi_region": 2,
            "single_region": 1,
            "non_english": 0
        }
    }
}

# Maximum possible weighted score
MAX_WEIGHTED_SCORE = sum(c["weight"] * 3 for c in ICP_CRITERIA.values())  # 51 points

# Qualification thresholds (normalized to 10)
THRESHOLDS = {
    "qualify_in": 7.0,
    "borderline_low": 5.0,
    "qualify_out": 5.0
}

# Hard disqualifiers
HARD_DISQUALIFIERS = [
    "No Braze and no plans to adopt",
    "Revenue under $50M",
    "Employee count under 200",
    "Sales cycle over 18 months",
    "Competing agency already locked in (non-incumbent)",
    "No executive sponsor access",
    "Budget cycle over 12 months away",
    "Non-English speaking market only"
]

# Target tech stack keywords
TECH_KEYWORDS = {
    "braze": ["braze", "braze.com"],
    "snowflake": ["snowflake", "snowflakecomputing"],
    "segment": ["segment", "segment.com", "twilio segment"],
    "hightouch": ["hightouch", "hightouch.io"],
    "cdp": ["cdp", "customer data platform"],
    "data_warehouse": ["data warehouse", "bigquery", "redshift", "databricks", "synapse"],
    "amplitude": ["amplitude"],
    "mixpanel": ["mixpanel"],
    "mparticle": ["mparticle"],
    "rudderstack": ["rudderstack"],
    "census": ["census"]
}

# Target verticals for keyword matching
VERTICAL_KEYWORDS = {
    "qsr": ["quick service", "fast food", "restaurant chain", "qsr"],
    "retail": ["retail", "retailer", "e-commerce", "ecommerce", "online store", "shopping"],
    "travel": ["travel", "airline", "hotel", "hospitality", "booking", "vacation"],
    "fintech": ["fintech", "financial", "banking", "payments", "insurance", "neobank"],
    "delivery": ["delivery", "logistics", "food delivery", "last mile"],
    "convenience": ["convenience store", "c-store", "petrol station", "gas station"],
    "telecom": ["telecom", "telecommunications", "mobile carrier", "wireless"],
    "media": ["media", "streaming", "entertainment", "gaming", "content"],
    "healthcare": ["healthcare", "health tech", "medical", "pharma"],
    "smart_home": ["smart home", "iot", "connected home", "home automation"]
}

# Positive signals for fast-track qualification
POSITIVE_SIGNALS = [
    "Incumbent agency is Merkle or Accenture",
    "Braze + Snowflake already in stack",
    "Referred by Braze/Hightouch partner team",
    "Active RFP in progress",
    "Budget already allocated",
    "Executive sponsor identified",
    "Pain point clearly articulated",
    "Existing Hightouch relationship"
]

# Concern indicators
CONCERN_INDICATORS = [
    "Long-term contract with competing vendor",
    "Recent agency change (last 6 months)",
    "Procurement process over 3 months",
    "Key stakeholder recently left",
    "Budget freeze announced",
    "Merger/acquisition in progress"
]

# Output formatting
QUALIFICATION_STATUS = {
    "qualify_in": "✅ QUALIFY IN",
    "borderline": "⚠️ BORDERLINE",
    "qualify_out": "❌ QUALIFY OUT"
}
