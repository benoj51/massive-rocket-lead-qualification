"""
Massive Rocket Lead Qualification Server.

Flask app powering the team-facing qualification UI. Serves qualify.html and
exposes a small JSON API:

    GET  /                  - qualify.html
    GET  /api/health        - service + integration status
    POST /api/qualify       - run end-to-end qualification (Apollo + scoring)
    POST /api/notion/sync   - push (or update) the result to Notion
    GET  /api/pipeline      - list all leads in the Notion tracker

HubSpot enrichment lives in legacy_hubspot.py for the post-CEO rollout — not
wired into the server today.
"""
from __future__ import annotations

import csv
import hmac
import io
import logging
import os
import traceback

from flask import Flask, Response, jsonify, request
from flask_cors import CORS

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import ai_summary
import apollo
import audit
import hubspot_sync
import qualify_service
import slack_digest
from notion_sync import NotionSync, NotionSyncError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mr.qualify")

app = Flask(__name__, static_folder=None)
CORS(app)

HERE = os.path.dirname(os.path.abspath(__file__))

# Read the UI once at startup so we (a) avoid file-handle leaks under the test
# client and (b) skip a disk read on every page load.
try:
    with open(os.path.join(HERE, "qualify.html"), "r", encoding="utf-8") as _f:
        _QUALIFY_HTML = _f.read()
except OSError:
    _QUALIFY_HTML = "<!doctype html><h1>qualify.html missing</h1>"


# ---- Auth -----------------------------------------------------------------
# Shared-secret gate. If APP_AUTH_TOKEN is set, every /api/* request must
# include either `Authorization: Bearer <token>` or `?token=<token>`. The
# HTML entrypoint stays open so the UI can render the auth prompt.
# Leave APP_AUTH_TOKEN unset in dev to disable.

AUTH_TOKEN = os.environ.get("APP_AUTH_TOKEN", "").strip()


def _request_token() -> str:
    auth_hdr = request.headers.get("Authorization", "")
    if auth_hdr.lower().startswith("bearer "):
        return auth_hdr[7:].strip()
    return request.args.get("token", "").strip()


@app.before_request
def _require_auth():
    if not AUTH_TOKEN:
        return None  # Auth disabled
    # Only gate API surface; HTML + health are open.
    if not request.path.startswith("/api/"):
        return None
    if request.path == "/api/health":
        return None
    if request.method == "OPTIONS":
        return None
    presented = _request_token()
    if not presented or not hmac.compare_digest(presented, AUTH_TOKEN):
        return jsonify({"error": "unauthorized", "code": "auth_required"}), 401
    return None


# ---- Routes ---------------------------------------------------------------

@app.route("/", methods=["GET"])
def index():
    return Response(_QUALIFY_HTML, mimetype="text/html; charset=utf-8")


@app.route("/api/health", methods=["GET"])
def health():
    notion_configured = bool(os.environ.get("NOTION_API_KEY"))
    notion_target = os.environ.get("NOTION_DATA_SOURCE_ID") or os.environ.get("NOTION_DATABASE_ID")
    return jsonify({
        "ok": True,
        "service": "mr-qualification",
        "apollo": apollo.healthcheck(),
        "notion": {
            "configured": notion_configured,
            "data_source_id_set": bool(os.environ.get("NOTION_DATA_SOURCE_ID")),
            "database_id_set": bool(os.environ.get("NOTION_DATABASE_ID")),
            "target_present": bool(notion_target),
            "api_version": os.environ.get("NOTION_API_VERSION", "2025-09-03"),
        },
        "auth": {"required": bool(AUTH_TOKEN)},
        "ai": {"configured": ai_summary.is_configured()},
        "slack": {"configured": slack_digest.is_configured()},
        "hubspot": hubspot_sync.status(),
    })


def _actor() -> str:
    """Best-effort actor identification. Falls back to 'anon'."""
    return (request.headers.get("X-Actor") or "anon").strip()[:64]


@app.route("/api/qualify", methods=["POST"])
def api_qualify():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    url = (body.get("url") or "").strip()
    overrides = body.get("overrides") or {}
    if not name or not url:
        return jsonify({"error": "name and url are required"}), 400
    try:
        result = qualify_service.qualify(name, url, overrides=overrides)
        audit.log_event(
            "qualified",
            actor=_actor(),
            company=name,
            url=url,
            score=result["score"]["normalized_score"],
            status=result["score"]["status"],
            opportunity=result["score"].get("opportunity_type"),
        )
        return jsonify(result)
    except apollo.ApolloError as e:
        log.warning("Apollo failure for %s: %s", name, e)
        audit.log_event("qualify_failed", actor=_actor(), company=name, reason=str(e)[:200])
        return jsonify({"error": f"Apollo error: {e}"}), 502
    except Exception as e:
        log.exception("Qualification crash for %s", name)
        audit.log_event("qualify_crash", actor=_actor(), company=name, reason=str(e)[:200])
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/notion/sync", methods=["POST"])
def api_notion_sync():
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"error": "request body required"}), 400
    company_name = (payload.get("company") or {}).get("name") or "?"
    try:
        sync = NotionSync()
        result = sync.upsert(payload)
        audit.log_event(
            "notion_sync",
            actor=_actor(),
            company=company_name,
            action=result.get("action"),
            page_id=result.get("page_id"),
            page_url=result.get("url"),
        )
        return jsonify(result)
    except (NotionSyncError, ValueError) as e:
        log.warning("Notion sync failure: %s", e)
        audit.log_event("notion_sync_failed", actor=_actor(), company=company_name, reason=str(e)[:200])
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        log.exception("Notion sync crash")
        audit.log_event("notion_sync_crash", actor=_actor(), company=company_name, reason=str(e)[:200])
        return jsonify({"error": str(e)}), 500


@app.route("/api/audit", methods=["GET"])
def api_audit():
    try:
        limit = int(request.args.get("limit", "100"))
    except ValueError:
        limit = 100
    limit = max(1, min(limit, 500))
    since = request.args.get("since")
    rows = audit.read_events(limit=limit, since=since)
    return jsonify({"rows": rows, "count": len(rows), "summary": audit.summarise(rows)})


@app.route("/api/pipeline/export.csv", methods=["GET"])
def api_pipeline_csv():
    try:
        limit = int(request.args.get("limit", "500"))
    except ValueError:
        limit = 500
    try:
        sync = NotionSync()
        rows = sync.list_pipeline(limit=limit)
    except (NotionSyncError, ValueError) as e:
        return jsonify({"error": str(e)}), 502
    buf = io.StringIO()
    cols = ["company", "icp_normalised", "status", "sales_stage", "vertical",
            "opportunity_type", "owner", "company_url", "next_steps", "last_edited"]
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k, "") for k in cols})
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=mr-pipeline.csv"},
    )


@app.route("/api/hubspot/sync", methods=["POST"])
def api_hubspot_sync():
    """HubSpot write-back. Disabled by default — see hubspot_sync.is_enabled()."""
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"error": "request body required"}), 400
    company_name = (payload.get("company") or {}).get("name") or "?"
    if not hubspot_sync.is_enabled():
        # Don't 401/403 here — 503 is the honest signal: feature unavailable.
        audit.log_event("hubspot_sync_blocked", actor=_actor(), company=company_name,
                        reason="HUBSPOT_SYNC_ENABLED!=1 or HUBSPOT_API_KEY missing")
        return jsonify({
            "error": "HubSpot sync is disabled",
            "code": "hubspot_disabled",
            "status": hubspot_sync.status(),
            "how_to_enable": "Set HUBSPOT_API_KEY and HUBSPOT_SYNC_ENABLED=1 in Railway variables, then redeploy. Awaiting CEO approval per the product brief.",
        }), 503
    try:
        sync = hubspot_sync.HubSpotSync()
        result = sync.upsert(payload)
        audit.log_event(
            "hubspot_sync",
            actor=_actor(),
            company=company_name,
            action=result.get("action"),
            company_id=result.get("company_id"),
            props_written=result.get("props_written"),
        )
        return jsonify(result)
    except (hubspot_sync.HubSpotSyncError, hubspot_sync.HubSpotSyncDisabled) as e:
        log.warning("HubSpot sync failure: %s", e)
        audit.log_event("hubspot_sync_failed", actor=_actor(), company=company_name, reason=str(e)[:200])
        return jsonify({"error": str(e)}), 502


@app.route("/api/slack/digest", methods=["GET", "POST"])
def api_slack_digest():
    """Build (and optionally send) the weekly digest.

    GET  ?send=0  -> returns the payload for preview, no Slack call.
    POST ?send=1  -> posts to Slack if SLACK_WEBHOOK_URL is set.
    """
    send_flag = request.args.get("send", "0") == "1" and request.method == "POST"
    try:
        sync = NotionSync()
        rows = sync.list_pipeline(limit=200)
    except (NotionSyncError, ValueError) as e:
        rows = []
        log.warning("Slack digest: Notion read failed: %s", e)
    events = audit.read_events(limit=200)
    payload = slack_digest.build_digest(pipeline_rows=rows, audit_events=events)
    result: dict = {"payload": payload, "slack_configured": slack_digest.is_configured()}
    if send_flag:
        result["send_result"] = slack_digest.send_digest(payload)
        audit.log_event(
            "slack_digest_sent",
            actor=_actor(),
            sent=result["send_result"]["sent"],
            reason=result["send_result"]["reason"],
        )
    return jsonify(result)


@app.route("/api/pipeline", methods=["GET"])
def api_pipeline():
    try:
        limit = int(request.args.get("limit", "50"))
    except ValueError:
        limit = 50
    try:
        sync = NotionSync()
        rows = sync.list_pipeline(limit=limit)
        return jsonify({"rows": rows, "count": len(rows)})
    except (NotionSyncError, ValueError) as e:
        log.warning("Pipeline list failure: %s", e)
        return jsonify({"error": str(e), "rows": []}), 502
    except Exception as e:
        log.exception("Pipeline list crash")
        return jsonify({"error": str(e), "rows": []}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
