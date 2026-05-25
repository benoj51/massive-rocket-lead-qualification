"""
Massive Rocket ICP Configuration
Defines scoring criteria, weights, and thresholds for lead qualification.

Updated 7 April 2026: Recalibrated vertical tiers to MR delivery depth
and win rate. Strict tech stack scoring (0 for unknown/speculated).
Added opportunity type classification.
"""

# ═══════════════════════════════════════════════════════════════
# ICP SCORING CRITERIA
# ═══════════════════════════════════════════════════════════════
# Each criterion produces a weighted score out of its max.
# Total max = 51 points, normalised to 10-point scale.
#
# IMPORTANT: Vertical and Tech Stack now use direct weighted
# scores (out of weight*3) to support non-integer tiers.
# ═══════════════════════════════════════════════════════════════

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
        # Vertical scoring uses DIRECT WEIGHTED scores (out of 9)
        # calibrated to MR's actual delivery depth and win rate.
        # Tier 1 (9/9): QSR, Roadside Convenience (Shell, Murphy USA, etc.)
        # Tier 2 (7/9): Delivery, C-store / Convenience
        # Tier 3 (6/9): Retail, Travel & Hospitality
        # Tier 4 (5/9): Fintech, Telecom
        # Tier 5 (3/9): Everything else
        "tiers": {
            # Tier 1: 9/9 -- MR's deepest expertise, highest win rate
            "qsr": 9,
            "quick service restaurant": 9,
            "fast food": 9,
            "roadside convenience": 9,
            "fuel retail": 9,
            "petrol station": 9,
            "gas station": 9,
            "truck stop": 9,
            # Tier 2: 7/9 -- strong delivery track record
            "delivery": 7,
            "food delivery": 7,
            "last mile": 7,
            "c-store": 7,
            "convenience store": 7,
            "convenience": 7,
            "grocery": 7,
            # Tier 3: 6/9 -- proven capability, competitive market
            "retail": 6,
            "e-commerce": 6,
            "ecommerce": 6,
            "travel": 6,
            "hospitality": 6,
            "travel & hospitality": 6,
            "hotel": 6,
            "airline": 6,
            # Tier 4: 5/9 -- capable but less differentiated
            "fintech": 5,
            "financial services": 5,
            "banking": 5,
            "telecom": 5,
            "telecommunications": 5,
            # Tier 5: 3/9 -- outside core ICP
            "media": 3,
            "entertainment": 3,
            "gaming": 3,
            "healthcare": 3,
            "insurance": 3,
            "smart home": 3,
            "iot": 3,
            "saas": 3,
            "technology": 3,
            "software": 3,
            "manufacturing": 3,
            "automotive": 3,
            "education": 3,
            "government": 3,
            "nonprofit": 3,
        },
        "default": 3  # Unknown vertical = Tier 5
    },
    "tech_stack": {
        "weight": 3,
        # Tech stack scoring uses DIRECT WEIGHTED scores (out of 9).
        # STRICT RULE: Unknown/speculated tech stack = 0/9.
        # Must be CONFIRMED data, not inferred from job ads or guesses.
        #
        # Opportunity types map to scores:
        # Retention (Braze + Snowflake confirmed):    9/9
        # Retention Light (Braze + other warehouse):  7/9
        # Migration (SFMC/DBX + warehouse, no Braze): 5/9
        # Augmentation (Braze only, no warehouse):    4/9
        # Greenfield (no relevant CEP/CDP):           2/9
        # Unknown/Speculated:                         0/9
        "opportunity_scores": {
            "retention": 9,         # Braze + Snowflake confirmed
            "retention_light": 7,   # Braze + other warehouse confirmed
            "migration": 5,         # Competitor stack (SFMC, DBX etc.) + warehouse
            "augmentation": 4,      # Braze only, no warehouse
            "greenfield": 2,        # No relevant marketing stack
            "unknown": 0,           # Not confirmed -- NEVER speculate
        },
        # Competitor stacks that indicate migration opportunity
        "competitor_ceps": [
            "salesforce marketing cloud", "sfmc", "exacttarget",
            "adobe campaign", "adobe experience platform", "aep",
            "oracle responsys", "oracle eloqua",
            "iterable", "klaviyo", "customer.io", "airship",
            "leanplum", "onesignal", "pushwoosh",
        ],
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

# Qualification thresholds (normalised to 10)
THRESHOLDS = {
    "qualify_in": 7.0,
    "borderline_low": 5.0,
    "qualify_out": 5.0
}

# ═══════════════════════════════════════════════════════════════
# OPPORTUNITY TYPES
# ═══════════════════════════════════════════════════════════════

OPPORTUNITY_TYPES = {
    "retention": {
        "label": "Retention",
        "description": "Braze already in stack. Help them extract more value.",
        "play": "Optimisation, personalisation uplift, Hightouch CDP layer"
    },
    "migration": {
        "label": "Migration",
        "description": "Competitor CEP in stack. Migrate to Braze.",
        "play": "Migration roadmap, Braze implementation, data layer"
    },
    "greenfield": {
        "label": "Greenfield",
        "description": "No CEP/CDP in place. Net new implementation.",
        "play": "Full Braze + Hightouch implementation from scratch"
    },
    "augmentation": {
        "label": "Augmentation",
        "description": "Braze in stack but needs added services.",
        "play": "Hightouch CDP, analytics, advanced use cases"
    }
}

# ═══════════════════════════════════════════════════════════════
# HARD DISQUALIFIERS
# ═══════════════════════════════════════════════════════════════

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

# ═══════════════════════════════════════════════════════════════
# TECH STACK KEYWORDS
# ═══════════════════════════════════════════════════════════════

TECH_KEYWORDS = {
    "braze": ["braze", "braze.com"],
    "snowflake": ["snowflake", "snowflakecomputing"],
    "segment": ["segment", "segment.com", "twilio segment"],
    "hightouch": ["hightouch", "hightouch.io"],
    "cdp": ["cdp", "customer data platform"],
    "data_warehouse": ["data warehouse", "bigquery", "redshift", "databricks", "synapse"],
    "competitor_cep": [
        "salesforce marketing cloud", "sfmc", "exacttarget",
        "adobe campaign", "adobe experience platform",
        "oracle responsys", "iterable", "klaviyo", "customer.io",
    ],
    "amplitude": ["amplitude"],
    "mixpanel": ["mixpanel"],
    "mparticle": ["mparticle"],
    "rudderstack": ["rudderstack"],
    "census": ["census"]
}

# ═══════════════════════════════════════════════════════════════
# VERTICAL KEYWORDS (for text detection)
# ═══════════════════════════════════════════════════════════════

VERTICAL_KEYWORDS = {
    "qsr": ["quick service", "fast food", "restaurant chain", "qsr", "burger", "pizza chain"],
    "roadside_convenience": [
        "fuel retail", "gas station", "petrol station", "truck stop",
        "roadside", "fuel stop", "travel center", "travel centre",
        "murphy usa", "shell", "bp", "exxon", "chevron", "pilot flying j",
        "circle k", "wawa", "sheetz", "buc-ee",
    ],
    "delivery": ["delivery", "logistics", "food delivery", "last mile", "on-demand"],
    "convenience": ["convenience store", "c-store", "corner shop", "mini mart"],
    "retail": ["retail", "retailer", "e-commerce", "ecommerce", "online store", "shopping"],
    "travel": ["travel", "airline", "hotel", "hospitality", "booking", "vacation", "resort"],
    "fintech": ["fintech", "financial", "banking", "payments", "insurance", "neobank"],
    "telecom": ["telecom", "telecommunications", "mobile carrier", "wireless"],
    "media": ["media", "streaming", "entertainment", "gaming", "content"],
    "healthcare": ["healthcare", "health tech", "medical", "pharma"],
    "smart_home": ["smart home", "iot", "connected home", "home automation"]
}

# ═══════════════════════════════════════════════════════════════
# SIGNALS
# ═══════════════════════════════════════════════════════════════

POSITIVE_SIGNALS = [
    "Incumbent agency is Merkle or Accenture",
    "Braze + Snowflake already in stack (confirmed)",
    "Referred by Braze/Hightouch partner team",
    "Active RFP in progress",
    "Budget already allocated",
    "Executive sponsor identified",
    "Pain point clearly articulated",
    "Existing Hightouch relationship"
]

CONCERN_INDICATORS = [
    "Long-term contract with competing vendor",
    "Recent agency change (last 6 months)",
    "Procurement process over 3 months",
    "Key stakeholder recently left",
    "Budget freeze announced",
    "Merger/acquisition in progress",
    "Tech stack unconfirmed (scored as 0)"
]

# ═══════════════════════════════════════════════════════════════
# PARTNER TIERS
# ═══════════════════════════════════════════════════════════════

PARTNER_TIERS = {
    "tier_1": ["braze", "hightouch"],
    "tier_2": ["snowflake"],
    "ancillary": ["voucherify", "mparticle", "segment", "bigquery", "aws", "azure"]
}

# ═══════════════════════════════════════════════════════════════
# SALES STAGES
# ═══════════════════════════════════════════════════════════════

SALES_STAGES = [
    "Intro Call",
    "Discovery",
    "Technical Fit",
    "Proposal",
    "Negotiation",
    "Legal/Procurement",
    "Verbal Commit",
    "Signature",
    # v1.0.0ca: terminal stages. Closed Won triggers Promote-to-Live
    # on save; Closed Lost prompts for a reason + auto-flips status
    # to "Nurture" so the lead leaves the active pipeline view but
    # stays visible for periodic touches.
    "Closed Won",
    "Closed Lost",
]

# v1.0.0ca: top-level lead-lifecycle statuses (Notion "Status" select).
# Separate from `sales_stage` — status is "where in the lifecycle",
# sales_stage is "how far along the deal motion".
#
# - Nurture: closed-lost-but-we-want-to-stay-warm (auto-set when
#   sales_stage flips to "Closed Lost"; manual move back to active
#   is allowed)
# - Rejected: we decided not to pursue. Out of every active surface.
#   Distinct from Disqualified (which is an ICP signal, not a
#   relationship decision).
LEAD_STATUSES = [
    "New",
    "Researching",
    "Qualified",
    "Disqualified",
    "On Hold",
    "Nurture",
    "Rejected",
]

# Output formatting
QUALIFICATION_STATUS = {
    "qualify_in": "QUALIFY IN",
    "borderline": "BORDERLINE",
    "qualify_out": "QUALIFY OUT"
}

# ═══════════════════════════════════════════════════════════════
# CONTEXT QUESTIONS (asked before research)
# ═══════════════════════════════════════════════════════════════

CONTEXT_QUESTIONS = [
    {
        "key": "partner_source",
        "question": "Which partner sourced this deal?",
        "options": ["Braze", "Hightouch", "Snowflake", "Cold outreach", "Inbound", "Other"]
    },
    {
        "key": "known_stack",
        "question": "What do we already know about their tech stack?",
        "options": [
            "Confirmed Braze + Snowflake",
            "Confirmed Braze + other warehouse",
            "Confirmed Braze only",
            "Confirmed competitor CEP (SFMC, DBX, etc.)",
            "Nothing confirmed",
        ]
    },
    {
        "key": "stack_confidence",
        "question": "How confident is the stack data?",
        "options": ["Confirmed (partner/prospect told us)", "Inferred (job ads, tech detection)", "Unknown"]
    },
    {
        "key": "partner_relationship",
        "question": "Prospect's relationship with the sourcing partner?",
        "options": ["Active customer", "In evaluation", "Lapsed", "No relationship", "Unknown"]
    }
]
