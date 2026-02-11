# Massive Rocket Lead Qualification Tool

Automated lead qualification against Massive Rocket's ICP (Ideal Customer Profile) criteria.

## Quick Start

```bash
# Basic usage
python qualify_lead.py "Company Name" "company-url.com"

# With company data
python qualify_lead.py "Chipotle" "chipotle.com" \
  --revenue "$9.8B" \
  --employees "115000" \
  --vertical "QSR" \
  --tech-stack "Braze, Snowflake"

# Interactive mode
python qualify_lead.py "McDonald's" "mcdonalds.com" --interactive

# JSON output
python qualify_lead.py "Domino's" "dominos.com" --output json
```

## Installation

```bash
pip install requests beautifulsoup4

# For Notion integration (optional)
pip install notion-client
```

## Command Line Options

| Flag | Description |
|------|-------------|
| `--revenue` | Annual revenue (e.g., "$2B", "£500M") |
| `--employees` | Employee count (e.g., "5000") |
| `--vertical` | Industry vertical (e.g., "QSR", "Retail") |
| `--tech-stack` | Technology stack (e.g., "Braze, Snowflake") |
| `--complexity` | Organizational complexity |
| `--region` | Geographic region |
| `--source` | Lead source |
| `--incumbent` | Current agency |
| `--interactive` | Prompt for data interactively |
| `--output` | Output format: `text` or `json` |
| `--quiet` | Minimal output (just score) |
| `--sync-notion` | Sync to Notion database |

## ICP Scoring Criteria

| Criterion | Weight | Max Score |
|-----------|--------|-----------|
| Revenue | 3x | 9 pts |
| Employees | 2x | 6 pts |
| Vertical | 3x | 9 pts |
| Tech Stack | 3x | 9 pts |
| Complexity | 2x | 6 pts |
| Deal Size | 3x | 9 pts |
| Region | 1x | 3 pts |
| **Total** | | **51 pts** |

Normalized to 10-point scale.

## Qualification Thresholds

- **✅ Qualify In**: Score ≥ 7.0
- **⚠️ Borderline**: Score 5.0 - 6.9
- **❌ Qualify Out**: Score < 5.0

## Target Verticals

| Priority | Verticals |
|----------|-----------|
| High (3) | QSR, Retail, Travel & Hospitality, Fintech, Delivery, Convenience |
| Medium (2) | Telecom, Media & Entertainment, Healthcare, Smart Home/IoT |
| Low (1) | SaaS, Technology, Manufacturing |

## Tech Stack Scoring

| Stack | Score |
|-------|-------|
| Braze + Snowflake | 3 (max) |
| Braze + Data Warehouse | 2 |
| Braze only | 1 |
| No Braze | 0 |

## Notion Integration

1. Create integration at https://www.notion.so/my-integrations
2. Share your database with the integration
3. Set environment variables:
   ```bash
   export NOTION_API_KEY="your-key"
   export NOTION_DATABASE_ID="your-database-id"
   ```
4. Run with `--sync-notion` flag

## Files

- `qualify_lead.py` - Main CLI tool
- `config.py` - ICP criteria and weights
- `scoring.py` - Scoring engine
- `research.py` - Web research helpers
- `notion_sync.py` - Notion integration

## Example Output

```
============================================================
QUALIFICATION REPORT: Chipotle
============================================================

ICP SCORE: 8.2/10  ✅ QUALIFY IN
────────────────────────────────────────────────────────────

SCORE BREAKDOWN:
  Revenue         │ >$1B                      │ 9/9 pts
  Employees       │ 3,000+                    │ 6/6 pts
  Vertical        │ Qsr                       │ 9/9 pts
  Tech Stack      │ Braze + Snowflake         │ 9/9 pts
  ...
```

## Positive Signals

These fast-track qualification:
- Incumbent agency is Merkle or Accenture
- Braze + Snowflake already in stack
- Referred by Braze/Hightouch partner team
- Active RFP in progress
- Budget already allocated

## Hard Disqualifiers

Automatic qualify-out regardless of score:
- Revenue under $50M
- Employee count under 200
- No Braze and no plans to adopt
- Non-English speaking market only
