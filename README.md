# Massive Rocket Lead Qualification Platform

Automated lead qualification tool that scores potential B2B sales leads against Massive Rocket's Ideal Customer Profile (ICP). Provides scoring, actionable next steps, tailored discovery questions, and stakeholder targeting — via CLI or a web interface.

---

## Table of Contents

- [Quick Start](#quick-start)
- [How It Works](#how-it-works)
- [ICP Scoring Model](#icp-scoring-model)
- [Discovery Questions](#discovery-questions)
- [Web Interface](#web-interface)
- [CLI Reference](#cli-reference)
- [AI Research](#ai-research)
- [Notion Integration](#notion-integration)
- [File Structure](#file-structure)
- [Troubleshooting](#troubleshooting)

---

## Quick Start

### Web Interface (recommended for team use)

1. Open `index.html` in a browser — no build step required.
2. Enter company details in Step 1 (or use AI Research to auto-fill).
3. Confirm in Step 2, then view the full qualification report in Step 3.

### CLI

```bash
# Install dependencies
pip install requests beautifulsoup4

# Basic qualification with known data
python qualify_lead.py "Chipotle" "chipotle.com" \
  --revenue "$9.8B" \
  --employees "115000" \
  --vertical "QSR" \
  --tech-stack "Braze, Snowflake"

# Interactive mode — prompts for each field
python qualify_lead.py "McDonald's" "mcdonalds.com" --interactive

# JSON output for pipeline integrations
python qualify_lead.py "Domino's" "dominos.com" --output json
```

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────────┐
│  INPUT: Company name, URL, revenue, employees, vertical,           │
│         tech stack, complexity, region, source                      │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                    ┌──────▼──────┐
                    │  ICP Scorer  │   8 weighted dimensions → /10 score
                    └──────┬──────┘
                           │
              ┌────────────┼────────────────┐
              ▼            ▼                ▼
    Hard Disqualifiers  Positive       Score Threshold
    (auto qualify-out)  Signals        ≥7.0 = In
                        (fast-track)   5.0–6.9 = Borderline
                                       <5.0 = Out
              │            │                │
              └────────────┼────────────────┘
                           ▼
              ┌─────────────────────────┐
              │  QUALIFICATION REPORT   │
              │  • Score breakdown      │
              │  • Signals & concerns   │
              │  • Discovery questions  │
              │  • Next steps           │
              │  • Stakeholder targets  │
              └─────────────────────────┘
```

---

## ICP Scoring Model

### Scoring Dimensions

| Criterion | Weight | 0 pts | 1 pt | 2 pts | 3 pts (max) |
|-----------|--------|-------|------|-------|--------------|
| **Revenue** | 3x | <$100M | $100M–$500M | $500M–$1B | >$1B |
| **Employees** | 2x | <500 | 500–1,500 | 1,500–3,000 | 3,000+ |
| **Vertical** | 3x | Education, Gov | SaaS, Mfg | Telecom, Media, Healthcare | QSR, Retail, Travel, Fintech, Delivery |
| **Tech Stack** | 3x | No Braze | Braze only | Braze + warehouse | Braze + Snowflake |
| **Complexity** | 2x | Simple | Single brand | Multi-brand or multi-market | Multi-brand + multi-market |
| **Deal Size** | 3x | <£10k/mo | £10k–£30k/mo | £30k–£50k/mo | >£50k/mo |
| **Region** | 1x | Non-English only | APAC/single region | NAM or EMEA | Global / NAM+EMEA |

**Total: 51 weighted points → normalized to a 10-point scale.**

### Qualification Thresholds

| Score | Status | Action |
|-------|--------|--------|
| **≥ 7.0** | Qualify In | Schedule discovery call within 48 hours |
| **5.0 – 6.9** | Borderline | Conduct qualification call to validate data |
| **< 5.0** | Qualify Out | Add to nurture, re-qualify in 6 months |

### Hard Disqualifiers (override score → auto Qualify Out)

- Revenue under $50M
- Employee count under 200
- No Braze and no plans to adopt
- Sales cycle over 18 months
- Competing agency locked in (non-incumbent)
- No executive sponsor access
- Budget cycle over 12 months away
- Non-English speaking market only

### Positive Signals (fast-track indicators)

- Incumbent agency is Merkle or Accenture
- Braze + Snowflake already in stack
- Referred by Braze/Hightouch partner team
- Active RFP in progress
- Budget already allocated
- Executive sponsor identified
- Pain point clearly articulated

---

## Discovery Questions

The platform generates **tailored discovery questions** based on the lead's profile. Questions adapt to:

- **Tech stack maturity** — different questions for leads with no Braze vs. Braze + Snowflake
- **Industry vertical** — QSR, Retail, Fintech, Travel, Telecom, Media, and Healthcare each get targeted questions
- **Organizational complexity** — multi-brand/multi-market leads get data identity and regional compliance questions
- **Qualification status** — borderline leads get budget/decision-process questions

### Question Categories

| Category | Purpose |
|----------|---------|
| **Engagement & Pain Points** | Universal openers to understand motivation and goals |
| **Tech Stack & Infrastructure** | Assess current platform maturity and gaps |
| **Data & Customer Intelligence** | Evaluate data unification and ownership |
| **Budget & Decision Process** | Understand timeline, budget, and buying committee |
| **Industry-Specific** | Vertical-tailored questions (loyalty, churn, compliance, etc.) |
| **Stakeholders & Organization** | Identify key contacts and team structure |

### Example: QSR Lead with Braze Only

```
[Tech Stack & Infrastructure]
  • How is your Braze implementation performing against your goals?
  • What data warehouse or CDP are you using alongside Braze?
  • Are there gaps in your current Braze setup that limit campaign sophistication?

[Industry-Specific]
  • How are you driving loyalty program engagement and repeat purchases?
  • What role does your mobile app play in the customer journey?
  • How are you personalizing offers based on order history and preferences?
```

---

## Web Interface

The web UI is a 3-step wizard that requires no backend to run for basic qualification:

| Step | What Happens |
|------|-------------|
| **Step 1: Enter Company** | Fill in company details manually or use AI Research to auto-fill |
| **Step 2: Confirm Brand** | Review a visual summary of the lead before scoring |
| **Step 3: Results** | View ICP score, breakdown, signals, discovery questions, and next steps |

### Actions available in Step 3

- **Export Report** — Downloads a `.txt` file with full qualification details including discovery questions
- **Save to Notion** — Syncs the lead to your Notion CRM database (requires server)
- **Qualify Another Lead** — Resets the form for a new lead

### Form Validation

The form validates required fields before proceeding. If key fields (Vertical, Region, Revenue, Employees) are empty, you'll get a confirmation prompt — scoring is less accurate without them but you can proceed.

---

## CLI Reference

```
python qualify_lead.py <company_name> <url> [OPTIONS]
```

| Flag | Description | Example |
|------|-------------|---------|
| `--revenue` | Annual revenue | `"$2B"`, `"£500M"` |
| `--employees` | Employee count | `"5000"`, `"10000+"` |
| `--vertical` | Industry vertical | `"QSR"`, `"Retail"`, `"Fintech"` |
| `--tech-stack` | Technology stack | `"Braze, Snowflake, Segment"` |
| `--complexity` | Organizational complexity | `"Multi-brand, Global"` |
| `--region` | Geographic region | `"US"`, `"EMEA"`, `"Global"` |
| `--source` | Lead source | `"Braze referral"`, `"Inbound"` |
| `--incumbent` | Current agency | `"Merkle"`, `"Accenture"` |
| `--interactive` / `-i` | Prompt for each field | — |
| `--output` / `-o` | Output format | `text` (default), `json` |
| `--quiet` / `-q` | Score-only output | — |
| `--sync-notion` | Save to Notion | — |

### Example Output

```
============================================================
QUALIFICATION REPORT: Chipotle
============================================================

ICP SCORE: 8.4/10  ✅ QUALIFY IN
────────────────────────────────────────────────────────────

SCORE BREAKDOWN:
  Revenue         │ >$1B                      │ 9/9 pts
  Employees       │ 3,000+                    │ 6/6 pts
  Vertical        │ Qsr                       │ 9/9 pts
  Tech Stack      │ Braze + Snowflake         │ 9/9 pts
  Complexity      │ Multi-Brand + Multi-Market │ 6/6 pts
  Deal Size       │ >£50k/mo (est.)           │ 9/9 pts
  Region          │ Multi-Region              │ 3/3 pts

✓ POSITIVE SIGNALS:
   • Braze + Snowflake already in stack

💬 DISCOVERY QUESTIONS:

  [Engagement & Pain Points]
    • What prompted you to explore working with an agency partner right now?
    • What does success look like for your CRM/lifecycle marketing in the next 12 months?

  [Tech Stack & Infrastructure]
    • How well integrated is your Braze + data warehouse pipeline today?
    • Are you able to activate real-time behavioral data in your messaging?

  [Industry-Specific]
    • How are you driving loyalty program engagement and repeat purchases?
    • What role does your mobile app play in the customer journey?

📋 RECOMMENDED NEXT STEPS:
   1. Schedule discovery call within 48 hours
   2. Research key stakeholders (CMO, VP Marketing, CRM Lead)
   3. Prepare pain point questions based on vertical
   4. Identify potential Braze/Hightouch connection for warm intro
```

---

## AI Research

The platform includes an optional AI-powered research feature that uses Claude to look up company information.

### Setup

```bash
pip install anthropic

# Set your API key
export ANTHROPIC_API_KEY="your-api-key"

# Start the research server
python research_server.py   # Runs on localhost:5001
```

### What It Does

- Researches the company using web search
- Returns: revenue, employees, vertical, tech stack, regions, complexity
- Includes a confidence level (Low / Medium / High)
- Results can be applied to the form with one click

---

## Notion Integration

Sync qualified leads directly to a Notion database for CRM tracking.

### Setup

1. Create a Notion integration at https://www.notion.so/my-integrations
2. Share your target database with the integration
3. Configure environment:

```bash
cp .env.example .env
# Edit .env with your keys:
# NOTION_API_KEY=your-notion-api-key
# NOTION_DATABASE_ID=your-database-id
```

4. Start the sync server:

```bash
pip install notion-client flask flask-cors
python server.py   # Runs on localhost:5000
```

5. Use "Save to Notion" in the web UI, or `--sync-notion` in CLI.

See [SETUP.md](SETUP.md) for detailed Notion database schema and troubleshooting.

---

## File Structure

```
├── index.html          Web UI — 3-step qualification wizard
├── app.js              Client-side scoring, display, and discovery question logic
├── styles.css          UI styling (responsive, modern design)
├── qualify_lead.py     CLI tool — main entry point
├── config.py           ICP criteria, weights, thresholds, keywords
├── scoring.py          Core scoring engine (parse, score, summarize)
├── research.py         Company research helpers and data extraction
├── research_server.py  Flask API for AI-powered company research
├── server.py           Flask API for Notion sync proxy
├── notion_sync.py      Notion API integration module
├── .env.example        Environment variables template
├── SETUP.md            Notion setup guide
└── README.md           This file
```

### Key Architecture Decisions

- **Dual scoring engines**: Both Python (CLI/server) and JavaScript (browser) implement the same scoring algorithm. Changes to scoring criteria must be updated in both `config.py` and `app.js`.
- **No build step**: The web UI runs from static files — open `index.html` directly.
- **Backend optional**: The web UI works offline for qualification. Servers are only needed for AI Research and Notion sync.

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Research button doesn't work | Start `research_server.py` on port 5001. Check `ANTHROPIC_API_KEY` is set. |
| Notion sync fails | Start `server.py` on port 5000. Check `NOTION_API_KEY` and `NOTION_DATABASE_ID`. |
| Vertical not mapping from research | The research-to-form mapping handles common variations. If a vertical isn't recognized, it defaults to "Other" — select manually. |
| Score seems wrong | Check that revenue/employees are in the expected format (e.g., `$2B`, `5000`). Negative or malformed values are treated as unknown. |
| Form submits with empty fields | The form now warns when key fields are missing. You can proceed, but scores will be less accurate. |
