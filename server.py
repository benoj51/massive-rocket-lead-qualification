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

import accounts_graph
import ai_summary
import apollo
import audit
import bant_health
import calls_store
import contacts_store
import criteria_store
import hubspot_sync
import lead_summary_store
import packages
import pricing
import pricing_store
import project_store
import qualify_service
import rate_cards
import roadmap as roadmap_module
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
    # v0.10.0h: explicit no-cache + must-revalidate so browsers always
    # pick up the latest JS/CSS after a Railway deploy. The HTML is one
    # bundled file (~200KB) — re-fetching it on every load is cheap and
    # avoids the "design hasn't changed" complaint after a deploy.
    resp = Response(_QUALIFY_HTML, mimetype="text/html; charset=utf-8")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


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


@app.route("/api/lead/extract", methods=["POST"])
def api_lead_extract():
    """Run Anthropic over notes/transcripts and return MEDDPICC + scope fills."""
    body = request.get_json(silent=True) or {}
    notes = (body.get("notes") or "").strip()
    if not notes:
        return jsonify({"error": "notes required"}), 400
    if not ai_summary.is_configured():
        return jsonify({"error": "AI extraction unavailable (ANTHROPIC_API_KEY not set)"}), 503
    company_name = (body.get("company_name") or "").strip() or None
    current = body.get("current_meddpicc") or {}
    result = ai_summary.extract_from_notes(notes, company_name=company_name,
                                           current_meddpicc=current)
    if result is None:
        return jsonify({"error": "extraction failed; check server logs"}), 502
    audit.log_event("lead_notes_extracted", actor=_actor(),
                    company=company_name or "",
                    meddpicc_filled=len(result.get("meddpicc") or {}),
                    project_scope_set=bool(result.get("project_scope")))
    return jsonify(result)


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


# --- Contacts per lead --------------------------------------------------

@app.route("/api/contacts/<lead_id>", methods=["GET"])
def api_contacts_list(lead_id: str):
    return jsonify({
        "contacts": contacts_store.list_contacts(lead_id),
        "primary": contacts_store.primary_contact(lead_id),
    })


@app.route("/api/contacts/<lead_id>/search", methods=["POST"])
def api_contacts_apollo_search(lead_id: str):
    """Pull fresh contacts from Apollo for an existing lead.

    v0.10.0s: lets the AE re-run people-search from the drawer's
    Contacts panel without having to re-qualify. Uses the lead's
    URL/domain (passed in body) — works even if Apollo's apollo_id
    isn't cached.

    Returns the candidate contacts (NOT auto-saved). The UI shows them
    in a list with checkboxes; the AE picks which ones to commit via
    the existing POST /api/contacts/<lead_id> bulk path.

    Already-saved contacts are flagged via `already_saved: true` so the
    UI can either skip them or show "(saved)" next to the name.
    """
    body = request.get_json(silent=True) or {}
    domain_or_url = (body.get("domain") or body.get("url") or "").strip()
    apollo_id = (body.get("apollo_id") or "").strip() or None
    limit = int(body.get("limit") or 15)
    # v0.10.0t: optional country/region filter — accepts either a list
    # (`person_locations`) or a comma-separated string (`countries`).
    raw_locs = body.get("person_locations") or body.get("countries") or []
    if isinstance(raw_locs, str):
        raw_locs = [s.strip() for s in raw_locs.split(",") if s.strip()]
    locations = [str(l).strip() for l in raw_locs if str(l).strip()] or None
    if not domain_or_url and not apollo_id:
        return jsonify({"error": "domain or apollo_id required"}), 400
    try:
        candidates = apollo.search_people(
            org_id=apollo_id,
            org_domain=domain_or_url,
            person_locations=locations,
            limit=limit,
        )
    except apollo.ApolloError as e:
        log.warning("Contact search failed for %s: %s", lead_id, e)
        return jsonify({"error": f"Apollo error: {e}", "candidates": []}), 502
    except Exception as e:
        log.warning("Contact search crashed for %s: %s", lead_id, e)
        return jsonify({"error": str(e), "candidates": []}), 500

    # Flag candidates that we've already saved so the UI can dedupe.
    existing = contacts_store.list_contacts(lead_id)
    existing_emails = {(c.get("email") or "").lower()
                       for c in existing if c.get("email")}
    existing_linkedin = {(c.get("linkedin_url") or "").lower()
                         for c in existing if c.get("linkedin_url")}
    existing_apollo_ids = {(c.get("id") or "") for c in existing}
    out = []
    for p in candidates:
        already = bool(
            (p.get("email") and p["email"].lower() in existing_emails)
            or (p.get("linkedin_url") and p["linkedin_url"].lower() in existing_linkedin)
            or (p.get("apollo_id") and p["apollo_id"] in existing_apollo_ids)
        )
        out.append({**p, "already_saved": already})
    audit.log_event("contacts_searched", actor=_actor(), lead_id=lead_id,
                    domain=domain_or_url, count=len(out))
    return jsonify({"candidates": out, "count": len(out)})


@app.route("/api/contacts/<lead_id>", methods=["POST"])
def api_contacts_save(lead_id: str):
    """Add or update one contact, or bulk save under {contacts: [...]} body."""
    body = request.get_json(silent=True) or {}
    if "contacts" in body and isinstance(body["contacts"], list):
        saved = contacts_store.save_many(lead_id, body["contacts"])
        audit.log_event("contacts_saved", actor=_actor(), lead_id=lead_id,
                        count=len(saved))
        return jsonify({"saved": saved,
                        "contacts": contacts_store.list_contacts(lead_id)})
    try:
        saved_one = contacts_store.save_contact(lead_id, body)
    except contacts_store.ContactsStoreError as e:
        return jsonify({"error": str(e)}), 400
    audit.log_event("contact_saved", actor=_actor(), lead_id=lead_id,
                    contact_id=saved_one["id"])
    return jsonify({"contact": saved_one,
                    "contacts": contacts_store.list_contacts(lead_id)})


@app.route("/api/contacts/<lead_id>/<contact_id>", methods=["DELETE"])
def api_contacts_delete(lead_id: str, contact_id: str):
    ok = contacts_store.delete_contact(lead_id, contact_id)
    if not ok:
        return jsonify({"error": "not_found"}), 404
    audit.log_event("contact_deleted", actor=_actor(), lead_id=lead_id,
                    contact_id=contact_id)
    return jsonify({"deleted": True,
                    "contacts": contacts_store.list_contacts(lead_id)})


@app.route("/api/contacts/<lead_id>/<contact_id>/primary", methods=["POST"])
def api_contacts_set_primary(lead_id: str, contact_id: str):
    primary = contacts_store.set_primary(lead_id, contact_id)
    if not primary:
        return jsonify({"error": "not_found"}), 404
    audit.log_event("contact_set_primary", actor=_actor(), lead_id=lead_id,
                    contact_id=contact_id)
    return jsonify({"primary": primary,
                    "contacts": contacts_store.list_contacts(lead_id)})


# --- Calls / notes per lead ----------------------------------------------

@app.route("/api/calls/<lead_id>", methods=["GET"])
def api_calls_list(lead_id: str):
    rolling = calls_store.aggregate_extractions(lead_id)
    # v0.10.0j: derive BANT-S health from the rolling MEDDPICC + project scope.
    # Cheap to compute, ships with every drawer load so the BANT strip renders
    # without an extra round trip.
    scope_state = None
    try:
        p = project_store.load(lead_id)
        if p is not None:
            scope_state = {
                "streams": [
                    {"project_type": s.project_type,
                     "validation_status": getattr(s, "validation_status", "draft")}
                    for s in p.streams
                ],
                "project_scope": (rolling or {}).get("project_scope") or "",
            }
    except Exception as e:
        log.warning("scope_state lookup failed for %s: %s", lead_id, e)
    bant = bant_health.derive_bant_health(
        (rolling or {}).get("meddpicc") or {},
        scope_state=scope_state,
    )
    return jsonify({
        "calls": calls_store.list_calls(lead_id),
        "rolling": rolling,
        "bant_health": bant,
    })


@app.route("/api/calls/<lead_id>", methods=["POST"])
def api_calls_add(lead_id: str):
    body = request.get_json(silent=True) or {}
    content = (body.get("content") or "").strip()
    if not content:
        return jsonify({"error": "content required"}), 400
    # Run AI extraction inline so the call record carries it from the start.
    extracted = None
    if ai_summary.is_configured():
        try:
            extracted = ai_summary.extract_from_notes(
                content,
                company_name=(body.get("company_name") or "").strip() or None,
            )
        except Exception as e:
            log.warning("Call extraction failed: %s", e)
            extracted = None
    body["extracted"] = extracted
    try:
        record = calls_store.add_call(lead_id, body)
    except calls_store.CallsStoreError as e:
        return jsonify({"error": str(e)}), 400
    audit.log_event("call_added", actor=_actor(), lead_id=lead_id,
                    call_id=record["id"], type=record["type"],
                    extracted=bool(extracted))

    # v0.10.0p: auto-refresh the lead summary so the AE doesn't have to
    # re-read every previous note. Inline (synchronous) — adds ~2s latency
    # to the save but means the summary tile reflects this call by the
    # time the UI re-renders. Safe to fail: any error here is logged but
    # doesn't break the call save.
    fresh_summary = None
    if ai_summary.is_configured() and extracted is not None:
        try:
            ctx = _gather_lead_context(lead_id)
            synth = ai_summary.synthesise_lead(ctx)
            if synth:
                fresh_summary = lead_summary_store.save(lead_id, synth)
                # Mirror to Notion (best-effort, same pattern as the
                # explicit refresh endpoint).
                try:
                    formatted = _format_summary_for_notion(fresh_summary)
                    NotionSync().update_page(lead_id, {"lead_summary": formatted})
                except Exception as e:
                    log.warning("Notion summary mirror failed in auto-refresh: %s", e)
                audit.log_event("lead_summary_auto_refreshed",
                                actor=_actor(), lead_id=lead_id,
                                trigger="call_added", call_id=record["id"])
        except Exception as e:
            log.warning("Auto-summary refresh failed for %s: %s", lead_id, e)

    return jsonify({
        "call": record,
        "rolling": calls_store.aggregate_extractions(lead_id),
        # New: the freshly-synthesised summary if AI re-ran successfully.
        # UI renders this without an extra GET to /summary.
        "summary": fresh_summary,
    })


@app.route("/api/calls/<lead_id>/<call_id>", methods=["PATCH"])
def api_calls_update(lead_id: str, call_id: str):
    body = request.get_json(silent=True) or {}
    if not body:
        return jsonify({"error": "no edits supplied"}), 400
    updated = calls_store.update_call(lead_id, call_id, body)
    if updated is None:
        return jsonify({"error": "not_found"}), 404
    audit.log_event("call_updated", actor=_actor(), lead_id=lead_id, call_id=call_id,
                    fields=sorted(body.keys()))
    return jsonify({"call": updated})


@app.route("/api/calls/<lead_id>/<call_id>", methods=["DELETE"])
def api_calls_delete(lead_id: str, call_id: str):
    ok = calls_store.delete_call(lead_id, call_id)
    if not ok:
        return jsonify({"error": "not_found"}), 404
    audit.log_event("call_deleted", actor=_actor(), lead_id=lead_id,
                    call_id=call_id)
    return jsonify({"deleted": True})


@app.route("/api/lead/<page_id>", methods=["GET"])
def api_lead_get(page_id: str):
    """Fetch a single lead's full record for the edit drawer.

    Returns the Notion lead plus a `group` block describing parent/child
    relationships from accounts_graph. Child leads get `group.parent`
    populated (slug + company name from the pipeline); parent leads get
    `group.children` populated.
    """
    try:
        sync = NotionSync()
        lead = sync.get_page(page_id)
    except (NotionSyncError, ValueError) as e:
        log.warning("Lead fetch failed: %s", e)
        return jsonify({"error": str(e)}), 502

    group = {"parent": None, "children": []}
    try:
        parent_slug = accounts_graph.parent_of(page_id)
        child_slugs = accounts_graph.children_of(page_id)
        # Resolve slugs → display names via the pipeline (single round-trip).
        all_slugs = set(filter(None, [parent_slug, *child_slugs]))
        name_map: dict[str, dict] = {}
        if all_slugs:
            try:
                rows = sync.list_pipeline(limit=500)
                for r in rows:
                    rid = project_store.slugify(r.get("id") or r.get("company") or "")
                    if rid in all_slugs:
                        name_map[rid] = {
                            "id": r.get("id"),
                            "company": r.get("company"),
                            "icp_normalised": r.get("icp_normalised"),
                            "status": r.get("status"),
                        }
            except Exception as e:
                log.warning("Group name resolution failed: %s", e)
        if parent_slug:
            group["parent"] = name_map.get(parent_slug, {"id": parent_slug, "company": parent_slug})
        group["children"] = [name_map.get(s, {"id": s, "company": s}) for s in child_slugs]
    except Exception as e:
        log.warning("accounts_graph lookup failed for %s: %s", page_id, e)

    return jsonify({"lead": lead, "group": group})


# v0.10.0p: scoring-relevant fields. When any of these change via the
# drawer save, we re-run calculate_icp_score and PATCH the new score
# back to Notion so the ICP pill in the UI stays honest.
_SCORING_FIELDS = {
    "revenue", "employees", "vertical", "tech_stack",
    "complexity", "region", "deal_size", "stack_confidence",
}


@app.route("/api/lead/<page_id>", methods=["PATCH"])
def api_lead_update(page_id: str):
    """Update editable fields on a lead. Body keys match the get_page shape.

    If any scoring-relevant field changed (revenue, employees, vertical,
    tech_stack, complexity, region, deal_size, stack_confidence), re-run
    the ICP score after the Notion update lands and write the new
    icp_normalised back. UI gets the new score in the response so the
    drawer pill updates without a separate fetch.
    """
    body = request.get_json(silent=True) or {}
    if not body:
        return jsonify({"error": "no edits supplied"}), 400
    try:
        sync = NotionSync()
        result = sync.update_page(page_id, body)
        audit.log_event("lead_updated", actor=_actor(), page_id=page_id,
                        fields=sorted([k for k in body.keys() if k != "id"]))

        # Re-score if scoring-relevant fields changed.
        scoring_changed = set(body.keys()) & _SCORING_FIELDS
        if scoring_changed:
            try:
                from scoring import calculate_icp_score
                lead = result.get("lead") or {}
                company_data = {
                    "revenue":          lead.get("revenue"),
                    "employees":        lead.get("employees"),
                    "vertical":         lead.get("vertical"),
                    "tech_stack":       lead.get("tech_stack"),
                    "complexity":       lead.get("complexity"),
                    "region":           lead.get("region"),
                    "deal_size":        lead.get("deal_size"),
                    "stack_confidence": (lead.get("stack_confidence") or "confirmed").lower(),
                }
                new_score = calculate_icp_score(company_data)
                # Write new score + opportunity type back. Use a second
                # PATCH so the first one (user-visible fields) commits
                # first; if scoring write fails, the user's data is safe.
                sync.update_page(page_id, {
                    "icp_normalised": new_score.get("normalized_score"),
                    "icp_total": new_score.get("total_weighted"),
                    "opportunity_type_key": new_score.get("opportunity_type"),
                })
                result["rescored"] = True
                result["new_score"] = {
                    "normalized_score": new_score.get("normalized_score"),
                    "status":           new_score.get("status"),
                    "status_label":     new_score.get("status_label"),
                    "opportunity_type": new_score.get("opportunity_type"),
                    "opportunity_label": new_score.get("opportunity_label"),
                    "changed_fields":   sorted(scoring_changed),
                }
                # Bump the icp_normalised on the lead dict in the response
                # so the UI doesn't have to re-fetch.
                if isinstance(result.get("lead"), dict):
                    result["lead"]["icp_normalised"] = new_score.get("normalized_score")
                audit.log_event("lead_rescored", actor=_actor(), page_id=page_id,
                                new_score=new_score.get("normalized_score"),
                                changed=sorted(scoring_changed))
            except Exception as e:
                log.warning("Re-score after lead update failed: %s", e)
                result["rescore_error"] = str(e)
        return jsonify(result)
    except (NotionSyncError, ValueError) as e:
        log.warning("Lead update failed: %s", e)
        return jsonify({"error": str(e)}), 502


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


@app.route("/api/pricing/rate-cards", methods=["GET"])
def api_pricing_rate_cards():
    """Read-only metadata for the UI dropdowns."""
    return jsonify({
        "currencies": list(rate_cards.CURRENCIES),
        "rate_cards": rate_cards.all_cards(),
        "regions": rate_cards.list_regions(),
        "seniorities": rate_cards.list_seniorities(),
        "staff_aug_rates": rate_cards.STAFF_AUG_RATES,
        "default_blended": {c: rate_cards.RATE_CARD_MR_DEFAULT["rates"][c]
                            for c in rate_cards.CURRENCIES},
    })


@app.route("/api/pricing/packages", methods=["GET"])
def api_pricing_packages():
    return jsonify({"packages": packages.list_packages()})


@app.route("/api/pricing/config/<lead_id>", methods=["GET"])
def api_pricing_config_get(lead_id: str):
    return jsonify({"config": pricing_store.load(lead_id)})


@app.route("/api/pricing/config/<lead_id>", methods=["POST", "PUT"])
def api_pricing_config_save(lead_id: str):
    body = request.get_json(silent=True) or {}
    saved = pricing_store.save(lead_id, body)
    audit.log_event("pricing_config_saved", actor=_actor(), lead_id=lead_id,
                    fields=sorted([k for k in saved.keys() if k != "updated_at"]))
    return jsonify({"config": saved})


@app.route("/api/pricing/preview", methods=["POST"])
def api_pricing_preview():
    """Compute a quote. Either from a stored project or from raw inputs."""
    body = request.get_json(silent=True) or {}
    lead_id = (body.get("lead_id") or "").strip()
    months = int(body.get("months") or 12)
    discount_first_half = float(body.get("discount_first_half_pct", 0.15))
    discount_second_half = float(body.get("discount_second_half_pct", 0.0))
    role_overrides = body.get("role_overrides") or {}
    # v0.8 additions
    currency = (body.get("currency") or "USD").upper()
    rate_card = body.get("rate_card") or "MR Default"
    project_ops_pct = float(body.get("project_ops_pct") or 0.0)
    contingency_pct = float(body.get("contingency_pct") or 0.0)
    role_staffing = body.get("role_staffing") or {}

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
            currency=currency,
            rate_card=rate_card,
            project_ops_pct=project_ops_pct,
            contingency_pct=contingency_pct,
            role_staffing=role_staffing,
        ))
        if lead_id:
            audit.log_event("pricing_preview", actor=_actor(), lead_id=lead_id,
                            net_usd=quote["totals"]["net_usd"])
        return jsonify(quote)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# --- Lead-level Claude synthesis ----------------------------------------

def _gather_lead_context(lead_id: str) -> dict:
    """Pull everything we know about a lead into a single dict for Claude."""
    ctx: dict = {"lead_id": lead_id}
    # Notion-side lead data
    try:
        sync = NotionSync()
        ctx["notion_lead"] = sync.get_page(lead_id)
    except Exception:
        ctx["notion_lead"] = None
    # Scope
    p = project_store.load(lead_id)
    if p:
        ctx["project_summary"] = scope_module.project_summary(p)
        ctx["streams"] = [
            {
                "project_type": s.project_type,
                "criteria": [
                    {"key": c.key, "value": c.value, "status": c.status}
                    for c in s.criteria if (c.value or c.status != "unqualified")
                ],
            }
            for s in p.streams
        ]
    # Rolling MEDDPICC + scope synthesis across calls
    ctx["rolling_extractions"] = calls_store.aggregate_extractions(lead_id)
    # Latest 6 calls (full, including AI-synthesised note + raw content)
    calls = calls_store.list_calls(lead_id)
    ctx["calls"] = [
        {
            "type": c.get("type"),
            "title": c.get("title"),
            "created_at": c.get("created_at"),
            "note": c.get("note") or "",
            "content_excerpt": (c.get("content") or "")[:1500],
            "extracted_meddpicc": (c.get("extracted") or {}).get("meddpicc"),
        }
        for c in calls[:6]
    ]
    ctx["calls_total"] = len(calls)
    # Contacts
    ctx["contacts"] = contacts_store.list_contacts(lead_id)
    # v0.10.0 Phase D: account-group context. If this lead is a child of a
    # parent (or is itself a parent), include sibling-brand state so Claude
    # can write portfolio-aware commentary ("Yum operating companies in
    # pipeline: Pizza Hut closed-won 2024, Taco Bell qualifying...").
    try:
        ctx["group"] = _gather_group_context(lead_id)
    except Exception as e:
        log.warning("Group context build failed for %s: %s", lead_id, e)
        ctx["group"] = None
    return ctx


def _gather_group_context(lead_id: str) -> dict | None:
    """Build the parent/siblings/children context block for Claude.

    Returns:
      For a child: {role: "child", parent: {...}, siblings: [...]}
      For a parent: {role: "parent", children: [...]}
      For a standalone: None
    """
    parent_slug = accounts_graph.parent_of(lead_id)
    own_slug = project_store.slugify(lead_id)
    sync = None
    pipeline: list[dict] = []

    def _ensure_pipeline():
        nonlocal sync, pipeline
        if sync is None:
            sync = NotionSync()
            pipeline = sync.list_pipeline(limit=500)
        return pipeline

    def _row_for(slug: str) -> dict | None:
        for r in _ensure_pipeline():
            if project_store.slugify(r.get("id") or r.get("company") or "") == slug:
                return r
        return None

    def _trim(r: dict) -> dict:
        return {
            "id": r.get("id"),
            "company": r.get("company"),
            "icp_normalised": r.get("icp_normalised"),
            "status": r.get("status"),
            "sales_stage": r.get("sales_stage"),
            "vertical": r.get("vertical"),
            "opportunity_type": r.get("opportunity_type"),
        }

    if parent_slug:
        # This lead is a child. Find the parent + sibling brands.
        parent_row = _row_for(parent_slug)
        sibling_slugs = [s for s in accounts_graph.children_of(parent_slug) if s != own_slug]
        siblings: list[dict] = []
        for s in sibling_slugs:
            r = _row_for(s)
            if r:
                siblings.append(_trim(r))
            else:
                siblings.append({"id": s, "company": s, "_missing": True})
        return {
            "role": "child",
            "parent": _trim(parent_row) if parent_row else {"id": parent_slug, "company": parent_slug},
            "siblings": siblings,
        }

    child_slugs = accounts_graph.children_of(lead_id)
    if child_slugs:
        # This lead is a parent. Pull children for portfolio context.
        children: list[dict] = []
        for s in child_slugs:
            r = _row_for(s)
            if r:
                children.append(_trim(r))
            else:
                children.append({"id": s, "company": s, "_missing": True})
        return {"role": "parent", "children": children}

    return None


@app.route("/api/lead/<lead_id>/summary", methods=["GET"])
def api_lead_summary_get(lead_id: str):
    cached = lead_summary_store.load(lead_id)
    return jsonify({"summary": cached})


@app.route("/api/lead/<lead_id>/summary", methods=["POST"])
def api_lead_summary_refresh(lead_id: str):
    """Run Claude over the lead's full context, cache + return the result.

    v0.10.0f also persists the formatted summary to Notion as a "Lead
    Summary" rich-text property so it survives Railway redeploys and is
    visible to anyone viewing the Notion page. Requires a "Lead Summary"
    column in the Notion DB — if absent, Notion returns 400 and we log
    a warning without failing the local save.
    """
    if not ai_summary.is_configured():
        return jsonify({"error": "AI unavailable (ANTHROPIC_API_KEY not set)"}), 503
    ctx = _gather_lead_context(lead_id)
    result = ai_summary.synthesise_lead(ctx)
    if result is None:
        return jsonify({"error": "Synthesis failed"}), 502
    saved = lead_summary_store.save(lead_id, result)
    notion_synced = False
    try:
        formatted = _format_summary_for_notion(saved)
        sync = NotionSync()
        sync.update_page(lead_id, {"lead_summary": formatted})
        notion_synced = True
    except Exception as e:
        # Most common cause: the Notion DB doesn't have a "Lead Summary"
        # property yet. We don't want to fail the user-visible operation —
        # the cached copy is still valid; the AE just doesn't get the
        # Notion mirror until the column is added.
        log.warning("Notion summary sync skipped for %s: %s", lead_id, e)
    audit.log_event("lead_summary_refreshed", actor=_actor(), lead_id=lead_id,
                    calls_used=len(ctx.get("calls") or []),
                    notion_synced=notion_synced)
    return jsonify({"summary": saved, "notion_synced": notion_synced})


def _format_summary_for_notion(summary: dict) -> str:
    """Turn the structured summary into a single rich-text block.

    Sections are separated by blank lines and prefixed with section
    headers so the Notion text reads cleanly in the property view.
    Truncated to ~1900 chars to fit Notion's per-rich-text-block limit
    (the rich_text helper chunks further if needed).
    """
    parts: list[str] = []
    state = (summary.get("state_of_play") or "").strip()
    if state:
        parts.append(state)
    facts = [f.strip() for f in (summary.get("key_facts") or []) if f]
    if facts:
        parts.append("KEY FACTS:\n" + "\n".join(f"• {f}" for f in facts))
    questions = [q.strip() for q in (summary.get("open_questions") or []) if q]
    if questions:
        parts.append("OPEN QUESTIONS:\n" + "\n".join(f"• {q}" for q in questions))
    next_action = (summary.get("next_action") or "").strip()
    if next_action:
        parts.append(f"NEXT ACTION: {next_action}")
    risks = [r.strip() for r in (summary.get("risks") or []) if r]
    if risks:
        parts.append("RISKS:\n" + "\n".join(f"• {r}" for r in risks))
    generated = summary.get("generated_at")
    if generated:
        parts.append(f"(Generated {generated} by Claude)")
    return "\n\n".join(parts)


# --- Roadmap -------------------------------------------------------------

@app.route("/api/roadmap/<lead_id>", methods=["GET"])
def api_roadmap_get(lead_id: str):
    r = roadmap_module.load(lead_id)
    if r is None:
        return jsonify({"roadmap": None})
    return jsonify({"roadmap": roadmap_module.to_dict(r)})


@app.route("/api/roadmap/<lead_id>", methods=["POST", "PUT"])
def api_roadmap_save(lead_id: str):
    body = request.get_json(silent=True) or {}
    body["lead_id"] = lead_id
    r = roadmap_module.save(lead_id, body)
    audit.log_event("roadmap_saved", actor=_actor(), lead_id=lead_id,
                    milestones=len(r.milestones),
                    extended=len(r.extended_engagement))
    return jsonify({"roadmap": roadmap_module.to_dict(r)})


@app.route("/api/roadmap/<lead_id>/seed-from-package", methods=["POST"])
def api_roadmap_seed_from_package(lead_id: str):
    body = request.get_json(silent=True) or {}
    pkg_key = (body.get("package_key") or "").strip()
    pkg = packages.get_package(pkg_key) if pkg_key else None
    if not pkg:
        return jsonify({"error": f"Unknown package: {pkg_key}"}), 400
    r = roadmap_module.load(lead_id) or roadmap_module.new_roadmap(
        lead_id, months=pkg.get("duration_months") or 12,
        start_date=body.get("start_date", ""),
    )
    roadmap_module.seed_milestones_from_package(r, pkg)
    roadmap_module.save(lead_id, r)
    audit.log_event("roadmap_seeded_from_package", actor=_actor(),
                    lead_id=lead_id, package_key=pkg_key,
                    milestones=len(r.milestones))
    return jsonify({"roadmap": roadmap_module.to_dict(r)})


@app.route("/api/roadmap/<lead_id>/ai-refine", methods=["POST"])
def api_roadmap_ai_refine(lead_id: str):
    if not ai_summary.is_configured():
        return jsonify({"error": "AI unavailable (ANTHROPIC_API_KEY not set)"}), 503
    r = roadmap_module.load(lead_id)
    if r is None:
        return jsonify({"error": "No roadmap to refine — create one first"}), 404
    # Pull context: current milestones, scope, calls.
    project = project_store.load(lead_id)
    scope_dict = None
    project_streams: list[str] = []
    if project is not None:
        scope_dict = {
            "summary": scope_module.project_summary(project),
            "streams": [{"project_type": s.project_type,
                          "criteria": [
                              {"key": c.key, "value": c.value, "status": c.status}
                              for c in s.criteria
                          ]}
                         for s in project.streams],
        }
        project_streams = [s.project_type for s in project.streams]
    calls = calls_store.list_calls(lead_id)
    result = ai_summary.suggest_roadmap(
        total_months=r.months,
        current_milestones=[roadmap_module.to_dict(r)["milestones"]][0] if r.milestones else [],
        scope=scope_dict, calls=calls, project_streams=project_streams,
    )
    if result is None:
        return jsonify({"error": "AI suggestion failed"}), 502
    # Apply the suggested milestones over the current roadmap. We replace
    # the milestone list wholesale — the AE can hit Undo or refine again.
    new_milestones = []
    for m in (result.get("milestones") or [])[:12]:
        new_milestones.append(roadmap_module.Milestone(
            id="",
            workstream=m.get("workstream") or "Cross-cutting",
            title=m.get("title") or "",
            month_offset=m.get("month_offset") or 0,
            duration_months=m.get("duration_months") or 1,
            phase=m.get("phase") or "Execute",
            description=m.get("description") or "",
        ))
    r.milestones = new_milestones
    roadmap_module.save(lead_id, r)
    audit.log_event("roadmap_ai_refined", actor=_actor(), lead_id=lead_id,
                    milestones=len(new_milestones))
    return jsonify({"roadmap": roadmap_module.to_dict(r),
                    "rationale": result.get("rationale") or ""})


@app.route("/api/roadmap/<lead_id>/ai-suggest-extended", methods=["POST"])
def api_roadmap_ai_suggest_extended(lead_id: str):
    if not ai_summary.is_configured():
        return jsonify({"error": "AI unavailable (ANTHROPIC_API_KEY not set)"}), 503
    project = project_store.load(lead_id)
    current_streams = [s.project_type for s in project.streams] if project else []
    current_packages = []  # tracked via roadmap state — empty for now
    calls = calls_store.list_calls(lead_id)
    result = ai_summary.suggest_extended_engagement(
        current_scope_streams=current_streams,
        current_package_keys=current_packages,
        package_catalogue=packages.list_packages(),
        calls=calls,
    )
    if result is None:
        return jsonify({"error": "AI suggestion failed"}), 502
    return jsonify({"items": result.get("items") or []})


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
        # Annotate each row with group membership so the UI can render
        # grouped/flat views without an extra round-trip.
        graph = accounts_graph.full_graph()
        parents_set = set(graph.values())
        for r in rows:
            rid = project_store.slugify(r.get("id") or r.get("company") or "")
            r["parent_account_id"] = graph.get(rid)
            r["is_parent"] = rid in parents_set
        return jsonify({"rows": rows, "count": len(rows)})
    except (NotionSyncError, ValueError) as e:
        log.warning("Pipeline list failure: %s", e)
        return jsonify({"error": str(e), "rows": []}), 502
    except Exception as e:
        log.exception("Pipeline list crash")
        return jsonify({"error": str(e), "rows": []}), 500


# ---------- Account groups (v0.10.0 Phase A) ----------

@app.route("/api/accounts/graph", methods=["GET"])
def api_accounts_graph():
    """Return the full {child_slug: parent_slug} map. Small, cacheable."""
    return jsonify({"graph": accounts_graph.full_graph()})


@app.route("/api/lead/<lead_id>/parent", methods=["PUT"])
def api_lead_set_parent(lead_id: str):
    """Set or clear the parent for this lead.

    Body: {"parent_account_id": "<slug or display name>"} to link,
          {"parent_account_id": null} or empty body to unlink.

    Returns 400 on graph violations (self-ref, one-level-rule).
    """
    body = request.get_json(silent=True) or {}
    parent = body.get("parent_account_id")
    if parent is not None and not str(parent).strip():
        parent = None
    try:
        result = accounts_graph.set_parent(lead_id, parent)
    except accounts_graph.GraphError as e:
        return jsonify({"error": str(e)}), 400
    audit.log_event(
        "account_parent_set" if parent else "account_parent_cleared",
        actor=_actor(), lead_id=lead_id, parent=parent,
    )
    return jsonify(result)


@app.route("/api/lead/<lead_id>/children", methods=["GET"])
def api_lead_children(lead_id: str):
    """List child accounts under this parent, enriched with pipeline metadata."""
    child_slugs = accounts_graph.children_of(lead_id)
    if not child_slugs:
        return jsonify({"children": []})
    try:
        sync = NotionSync()
        rows = sync.list_pipeline(limit=500)
    except (NotionSyncError, ValueError) as e:
        log.warning("Children pipeline lookup failed: %s", e)
        return jsonify({"children": [{"id": s, "company": s} for s in child_slugs]})
    by_slug = {project_store.slugify(r.get("id") or r.get("company") or ""): r for r in rows}
    children = []
    for s in child_slugs:
        r = by_slug.get(s)
        if r:
            children.append({
                "id": r.get("id"),
                "company": r.get("company"),
                "icp_normalised": r.get("icp_normalised"),
                "status": r.get("status"),
                "sales_stage": r.get("sales_stage"),
                "vertical": r.get("vertical"),
            })
        else:
            children.append({"id": s, "company": s, "_missing": True})
    return jsonify({"children": children})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
