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
import criteria_store
import hubspot_sync
import pricing
import project_store
import qualify_service
import scope as scope_module
import slack_digest
import sow
import sow_store
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


# ===========================================================================
# v0.4: Project Build — scope intake + pricing + delivery validation
# ===========================================================================

@app.route("/api/scope/library", methods=["GET"])
def api_scope_library():
    """Read-only metadata for the UI."""
    return jsonify({
        "project_types": scope_module.project_types(),
        "criteria": scope_module.criteria_library(),
        "discovery_questions": scope_module.discovery_questions(),
        "objections": scope_module.objection_library(),
        "reference_points": scope_module.reference_points(),
        "team_templates": pricing.list_team_templates(),
        "role_catalogue": pricing.role_catalogue(),
    })


@app.route("/api/scope/projects", methods=["GET"])
def api_scope_projects():
    """List all in-flight projects (for the Project Build view)."""
    only = request.args.get("pending_validation_only", "").lower() in ("1", "true", "yes")
    summaries = project_store.list_pending_validation() if only else project_store.list_summaries()
    return jsonify({"projects": summaries, "count": len(summaries)})


@app.route("/api/scope/<lead_id>", methods=["GET"])
def api_scope_get(lead_id: str):
    project = project_store.load(lead_id)
    if not project:
        return jsonify({"error": "not_found", "lead_id": lead_id}), 404
    return jsonify({
        "project": scope_module.to_dict(project),
        "summary": scope_module.project_summary(project),
    })


@app.route("/api/scope/<lead_id>", methods=["POST", "PUT"])
def api_scope_upsert(lead_id: str):
    body = request.get_json(silent=True) or {}
    company_name = (body.get("company_name") or "").strip()
    project_types = body.get("project_types") or []
    if not company_name:
        return jsonify({"error": "company_name required"}), 400
    if not project_types:
        return jsonify({"error": "project_types required"}), 400

    try:
        existing = project_store.load(lead_id)
        if existing is None:
            project = scope_module.new_project(lead_id, company_name, project_types)
        else:
            # Preserve existing answers when project types stay the same; add
            # empty criteria for newly-added streams.
            project = existing
            project.company_name = company_name
            existing_types = {s.project_type for s in project.streams}
            for pt in project_types:
                if pt not in existing_types:
                    library = scope_module.criteria_library().get(pt, [])
                    project.streams.append(scope_module.ProjectStream(
                        project_type=pt,
                        criteria=[scope_module.CriterionAnswer(key=c["key"]) for c in library],
                    ))
            # Drop streams the AE deselected
            project.streams = [s for s in project.streams if s.project_type in project_types]
            project.touch()

        # Apply criterion-level updates if provided.
        for upd in body.get("criteria_updates") or []:
            scope_module.update_criterion(
                project,
                project_type=upd["project_type"],
                key=upd["key"],
                value=upd.get("value"),
                status=upd.get("status"),
            )

        project_store.save(project)
        audit.log_event("scope_saved", actor=_actor(), lead_id=lead_id,
                        company=company_name,
                        validation_status=project.validation_status)
        return jsonify({
            "project": scope_module.to_dict(project),
            "summary": scope_module.project_summary(project),
        })
    except scope_module.ScopeError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/scope/<lead_id>/transition", methods=["POST"])
def api_scope_transition(lead_id: str):
    body = request.get_json(silent=True) or {}
    action = (body.get("action") or "").strip()
    notes = (body.get("notes") or "").strip()
    project = project_store.load(lead_id)
    if not project:
        return jsonify({"error": "not_found", "lead_id": lead_id}), 404
    try:
        scope_module.transition(project, action, actor=_actor(), notes=notes)
        project_store.save(project)
        audit.log_event("scope_transition", actor=_actor(), lead_id=lead_id,
                        action=action, notes=notes[:200])
        return jsonify({
            "project": scope_module.to_dict(project),
            "summary": scope_module.project_summary(project),
        })
    except scope_module.ScopeError as e:
        return jsonify({"error": str(e)}), 400


# --- Admin: editable criteria library --------------------------------------

@app.route("/api/admin/criteria", methods=["GET"])
def api_admin_criteria_list():
    return jsonify({"library": criteria_store.load()})


@app.route("/api/admin/criteria/<project_type>", methods=["POST"])
def api_admin_criteria_upsert(project_type: str):
    if project_type not in scope_module.PROJECT_TYPES:
        return jsonify({"error": f"unknown project type {project_type}"}), 400
    body = request.get_json(silent=True) or {}
    try:
        saved = criteria_store.upsert_criterion(project_type, body)
        audit.log_event("criteria_upsert", actor=_actor(),
                        project_type=project_type, key=saved["key"])
        return jsonify({"criterion": saved, "library": criteria_store.load()})
    except criteria_store.CriteriaStoreError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/admin/criteria/<project_type>/<key>", methods=["DELETE"])
def api_admin_criteria_delete(project_type: str, key: str):
    if project_type not in scope_module.PROJECT_TYPES:
        return jsonify({"error": f"unknown project type {project_type}"}), 400
    removed = criteria_store.delete_criterion(project_type, key)
    if not removed:
        return jsonify({"error": "not found"}), 404
    audit.log_event("criteria_delete", actor=_actor(),
                    project_type=project_type, key=key)
    return jsonify({"deleted": True, "library": criteria_store.load()})


@app.route("/api/admin/criteria/<project_type>/reorder", methods=["POST"])
def api_admin_criteria_reorder(project_type: str):
    if project_type not in scope_module.PROJECT_TYPES:
        return jsonify({"error": f"unknown project type {project_type}"}), 400
    body = request.get_json(silent=True) or {}
    keys = body.get("keys") or []
    try:
        criteria_store.reorder(project_type, keys)
        audit.log_event("criteria_reorder", actor=_actor(), project_type=project_type)
        return jsonify({"library": criteria_store.load()})
    except criteria_store.CriteriaStoreError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/admin/criteria/<project_type>/reset", methods=["POST"])
def api_admin_criteria_reset(project_type: str):
    if project_type not in scope_module.PROJECT_TYPES:
        return jsonify({"error": f"unknown project type {project_type}"}), 400
    try:
        criteria_store.reset_project_type(project_type)
        audit.log_event("criteria_reset", actor=_actor(), project_type=project_type)
        return jsonify({"library": criteria_store.load()})
    except criteria_store.CriteriaStoreError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/admin/criteria/reset_all", methods=["POST"])
def api_admin_criteria_reset_all():
    criteria_store.reset_all()
    audit.log_event("criteria_reset_all", actor=_actor())
    return jsonify({"library": criteria_store.load()})


@app.route("/api/pricing/preview", methods=["POST"])
def api_pricing_preview():
    """Compute a quote. Either from a stored project or from raw inputs."""
    body = request.get_json(silent=True) or {}
    lead_id = (body.get("lead_id") or "").strip()
    months = int(body.get("months") or 12)
    discount_first_half = float(body.get("discount_first_half_pct", 0.15))
    discount_second_half = float(body.get("discount_second_half_pct", 0.0))
    role_overrides = body.get("role_overrides") or {}

    if lead_id:
        project = project_store.load(lead_id)
        if not project:
            return jsonify({"error": "lead not found", "lead_id": lead_id}), 404
        project_types = [s.project_type for s in project.streams]
        effort_multipliers = scope_module.role_drivers_for_project(project)
    else:
        project_types = body.get("project_types") or []
        effort_multipliers = body.get("effort_multipliers") or {}

    if not project_types:
        return jsonify({"error": "project_types required (either via lead_id or in body)"}), 400

    try:
        quote = pricing.compute_quote(pricing.QuoteInputs(
            project_types=project_types,
            months=months,
            discount_pct_first_half=discount_first_half,
            discount_pct_second_half=discount_second_half,
            role_overrides=role_overrides,
            effort_multipliers=effort_multipliers,
        ))
        if lead_id:
            audit.log_event("pricing_preview", actor=_actor(), lead_id=lead_id,
                            net_usd=quote["totals"]["net_usd"])
        return jsonify(quote)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# --- SOW (Statement of Work) ---------------------------------------------
# Manual trigger only. Each POST snapshots the current state and increments
# the version. Snapshots are immutable; re-clicking creates a new version.

@app.route("/api/sow/<lead_id>", methods=["POST"])
def api_sow_create(lead_id: str):
    body = request.get_json(silent=True) or {}
    months = int(body.get("months") or 12)
    discount_first = float(body.get("discount_first_half_pct", 0.15))
    discount_second = float(body.get("discount_second_half_pct", 0.0))
    try:
        snapshot = sow.build_snapshot(
            lead_id, months=months,
            discount_first_half=discount_first,
            discount_second_half=discount_second,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

    version = sow_store.save(lead_id, snapshot)
    audit.log_event("sow_drafted", actor=_actor(), lead_id=lead_id, version=version,
                    net_usd=snapshot["sections"]["investment"]["totals"]["net_usd"],
                    validation_at_generation=snapshot.get("validation_status_at_generation"))
    return jsonify({
        "version": version,
        "snapshot": snapshot,
        "render_url": f"/api/sow/{lead_id}/v{version}.html",
        "json_url": f"/api/sow/{lead_id}/v{version}.json",
    })


@app.route("/api/sow/<lead_id>", methods=["GET"])
def api_sow_list(lead_id: str):
    return jsonify({"versions": sow_store.list_versions(lead_id)})


@app.route("/api/sow/<lead_id>/v<int:version>.json", methods=["GET"])
def api_sow_get_json(lead_id: str, version: int):
    snapshot = sow_store.load(lead_id, version)
    if snapshot is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(snapshot)


@app.route("/api/sow/<lead_id>/v<int:version>.html", methods=["GET"])
def api_sow_get_html(lead_id: str, version: int):
    snapshot = sow_store.load(lead_id, version)
    if snapshot is None:
        return Response("Not found", status=404)
    html = sow.render_html(snapshot, version)
    return Response(html, mimetype="text/html; charset=utf-8")


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
