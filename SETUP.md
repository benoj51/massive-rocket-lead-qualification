# Massive Rocket Lead Qualification Platform - Setup Guide

## Quick Start (Without Notion)

1. Open `index.html` in your browser
2. Qualify leads - results are calculated locally
3. Export reports as text files

## Setup Notion Integration

### Step 1: Create Notion Integration

1. Go to [https://www.notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Click "New integration"
3. Give it a name (e.g., "Lead Qualification")
4. Select your workspace
5. Click "Submit"
6. Copy the "Internal Integration Token" (starts with `secret_`)

### Step 2: Create Database in Notion

1. Create a new page in Notion
2. Add a database (Table view works best)
3. The server will auto-create columns, or manually add:
   - Company Name (Title)
   - URL (URL)
   - ICP Score (Number)
   - Status (Select: Qualify In, Borderline, Qualify Out)
   - Vertical (Select)
   - Revenue (Text)
   - Employees (Text)
   - Tech Stack (Multi-select)
   - Region (Select)
   - Fit Summary (Text)
   - Next Steps (Text)
   - Qualified Date (Date)
   - Positive Signals (Multi-select)
   - Disqualifiers (Multi-select)
   - Lead Source (Text)

### Step 3: Share Database with Integration

1. Open your database page in Notion
2. Click "Share" in the top right
3. Click "Invite"
4. Find and select your integration
5. Click "Invite"

### Step 4: Get Database ID

1. Open your database in Notion
2. Copy the URL - it looks like:
   `https://www.notion.so/your-workspace/DATABASE_ID?v=...`
3. The DATABASE_ID is the long string before the `?v=`

### Step 5: Configure Environment

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` with your values:
   ```
   NOTION_API_KEY=secret_your_key_here
   NOTION_DATABASE_ID=your_database_id_here
   ```

### Step 6: Install Dependencies & Run Server

```bash
# Install Python dependencies
pip install flask flask-cors notion-client python-dotenv

# Start the server
python server.py
```

### Step 7: Open the Platform

1. Open `index.html` in your browser
2. The "Save to Notion" button should now be active
3. Qualify a lead and click "Save to Notion"

## Troubleshooting

### "Notion not configured" error
- Make sure the server is running (`python server.py`)
- Check that `.env` file exists with valid keys
- Restart the server after changing `.env`

### "Could not find database" error
- Verify the database ID is correct
- Make sure you shared the database with your integration

### CORS errors in browser
- The server must be running on `localhost:5000`
- Make sure you're accessing the HTML file, not the raw file path

## Files Overview

| File | Purpose |
|------|---------|
| `index.html` | Main web interface |
| `styles.css` | UI styling |
| `app.js` | Client-side logic & scoring |
| `server.py` | Flask backend for Notion API |
| `.env` | Your API keys (don't commit!) |
| `.env.example` | Template for environment variables |

## Architecture

```
Browser (index.html + app.js)
         │
         ▼
    Flask Server (server.py)
         │
         ▼
    Notion API
         │
         ▼
    Notion Database
```

The browser cannot call Notion's API directly because:
1. API keys would be exposed in client-side code
2. CORS restrictions prevent direct browser → Notion calls

The Flask server acts as a secure proxy, keeping your API key safe.
