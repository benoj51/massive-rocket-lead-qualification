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
import lead_agencies_store
import lead_contact_notes_store
import partner_contact_summary_store
import lead_partner_assignments
import partner_contacts_store
import partner_notes_store
import partners_store
import project_preview
import state_backup
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
    """Best-effort actor identification. Falls back to 'anon'.

    Tolerates being called outside a Flask request context — needed for
    tests that exercise server-internal helpers directly.
    """
    try:
        return (request.headers.get("X-Actor") or "anon").strip()[:64]
    except RuntimeError:
        return "anon"


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
    # v1.0.0b: cascade-delete the contact's notes so they don't leak as orphans.
    lead_contact_notes_store.delete_all_for_contact(lead_id, contact_id)
    audit.log_event("contact_deleted", actor=_actor(), lead_id=lead_id,
                    contact_id=contact_id)
    return jsonify({"deleted": True,
                    "contacts": contacts_store.list_contacts(lead_id)})


@app.route("/api/contacts/<lead_id>/<contact_id>/touch", methods=["POST"])
def api_contacts_touch(lead_id: str, contact_id: str):
    """v1.0.0a: explicit "I touched this contact" action — bumps
    last_touched_at so the cadence clock resets. Mirror of the
    partner-contacts touch endpoint."""
    touched = contacts_store.touch_contact(lead_id, contact_id)
    if not touched:
        return jsonify({"error": "not_found"}), 404
    audit.log_event("contact_touched", actor=_actor(),
                    lead_id=lead_id, contact_id=contact_id)
    return jsonify({"contact": contacts_store.annotate_touch_state(touched)})


# v1.0.0b (Tier 1d): per-lead-contact engagement timeline.
@app.route("/api/contacts/<lead_id>/<contact_id>/notes", methods=["GET"])
def api_lead_contact_notes_list(lead_id: str, contact_id: str):
    return jsonify({"notes": lead_contact_notes_store.list_notes(lead_id, contact_id)})


@app.route("/api/contacts/<lead_id>/<contact_id>/notes", methods=["POST"])
def api_lead_contact_notes_add(lead_id: str, contact_id: str):
    """Add a note. Auto-bumps the contact's `last_touched_at` (same
    pattern as the partner-side: a note IS a touch)."""
    body = request.get_json(silent=True) or {}
    body.setdefault("author", _actor())
    try:
        note = lead_contact_notes_store.add_note(lead_id, contact_id, body)
    except lead_contact_notes_store.LeadContactNotesStoreError as e:
        return jsonify({"error": str(e)}), 400
    touched = contacts_store.touch_contact(lead_id, contact_id)
    audit.log_event("lead_contact_note_added", actor=_actor(),
                    lead_id=lead_id, contact_id=contact_id,
                    note_id=note["id"], touched=bool(touched))
    return jsonify({
        "note": note,
        "notes": lead_contact_notes_store.list_notes(lead_id, contact_id),
        "contact": contacts_store.annotate_touch_state(touched) if touched else None,
    })


@app.route("/api/contacts/<lead_id>/<contact_id>/notes/<note_id>", methods=["DELETE"])
def api_lead_contact_notes_delete(lead_id: str, contact_id: str, note_id: str):
    ok = lead_contact_notes_store.delete_note(lead_id, contact_id, note_id)
    if not ok:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"deleted": True})


# v1.0.0p: incumbent + previous agencies per lead -----------------------------

@app.route("/api/leads/<lead_id>/agencies", methods=["GET"])
def api_lead_agencies_list(lead_id: str):
    """List agencies tracked against this lead — incumbent + previous."""
    return jsonify({
        "agencies": lead_agencies_store.list_agencies(lead_id),
        "types":    lead_agencies_store.AGENCY_TYPES,
    })


@app.route("/api/leads/<lead_id>/agencies", methods=["POST"])
def api_lead_agencies_add(lead_id: str):
    """Create or upsert (when id supplied) an agency entry."""
    body = request.get_json(silent=True) or {}
    try:
        saved = lead_agencies_store.save_agency(lead_id, body)
    except lead_agencies_store.LeadAgenciesStoreError as e:
        return jsonify({"error": str(e)}), 400
    audit.log_event("lead_agency_saved", actor=_actor(),
                    lead_id=lead_id, agency_id=saved["id"],
                    type=saved["type"], name=saved["name"])
    # Mirror to Notion so this survives Railway redeploys.
    _mirror_state_to_notion(lead_id)
    return jsonify({
        "agency":   saved,
        "agencies": lead_agencies_store.list_agencies(lead_id),
    })


@app.route("/api/leads/<lead_id>/agencies/<agency_id>", methods=["PATCH"])
def api_lead_agencies_update(lead_id: str, agency_id: str):
    """Update a specific agency entry by id.

    PATCH semantics:
    - Keys OMITTED from the body are preserved from the existing record.
    - Keys PRESENT in the body — including with value `null` or `""` —
      overwrite the existing value. The store's `_normalise` then
      collapses empty/whitespace/None to None on the optional fields
      (`scope`, `since`, `until`, `notes`), so sending `{"notes": null}`
      OR `{"notes": ""}` are both valid ways to clear that field.
    - `name` and `type` are required by `_normalise`, so sending
      `{"name": null}` raises a 400.
    """
    body = request.get_json(silent=True) or {}
    existing = lead_agencies_store.get_agency(lead_id, agency_id)
    if existing is None:
        return jsonify({"error": "not_found"}), 404
    # v1.0.0s: simplified merge. Earlier code had a tautological filter
    # `if v is not None or k in body` that did nothing — every key
    # iterated from body.items() is by definition in body. Plain merge
    # is the correct + readable behaviour.
    merged = dict(existing)
    merged.update(body)
    merged["id"] = agency_id
    try:
        saved = lead_agencies_store.save_agency(lead_id, merged)
    except lead_agencies_store.LeadAgenciesStoreError as e:
        return jsonify({"error": str(e)}), 400
    audit.log_event("lead_agency_updated", actor=_actor(),
                    lead_id=lead_id, agency_id=agency_id)
    _mirror_state_to_notion(lead_id)
    return jsonify({
        "agency":   saved,
        "agencies": lead_agencies_store.list_agencies(lead_id),
    })


@app.route("/api/leads/<lead_id>/agencies/<agency_id>", methods=["DELETE"])
def api_lead_agencies_delete(lead_id: str, agency_id: str):
    ok = lead_agencies_store.delete_agency(lead_id, agency_id)
    if not ok:
        return jsonify({"error": "not_found"}), 404
    audit.log_event("lead_agency_deleted", actor=_actor(),
                    lead_id=lead_id, agency_id=agency_id)
    _mirror_state_to_notion(lead_id)
    return jsonify({"deleted": True,
                     "agencies": lead_agencies_store.list_agencies(lead_id)})


# v1.0.0c (Tier 2a + 2b): cross-surface contact search + "My contacts".
# Single endpoint that scans BOTH the lead-side contacts and the
# partner-side contacts. Returns a unified result list with `surface`
# tag and `parent_*` enrichment so the UI can render and click-through.

@app.route("/api/contacts/search", methods=["GET"])
def api_contacts_search():
    """Search every contact (lead-side + partner-side) by free-text +
    filters. Designed to power a global ⌘K-style picker.

    Query params (all optional):
      q          — free text matched against name, email, title (case-insensitive)
      surface    — "lead" | "partner" | omit for both
      status     — active | dormant | left (default: any)
      territory  — partner-side only field; matches partner contacts only
      region     — partner-side only field
      industry   — partner-side only field (matches contacts with the
                   industry in their `industries` array)
      owner      — matches `mr_owner` (case-insensitive contains). Enables
                   the "My contacts" workflow when the AE passes their name.
      limit      — int, max results per surface (default 50)
    """
    q = (request.args.get("q") or "").strip().lower()
    surface_filter = (request.args.get("surface") or "").strip().lower() or None
    status_filter = (request.args.get("status") or "").strip().lower() or None
    territory_filter = (request.args.get("territory") or "").strip() or None
    region_filter = (request.args.get("region") or "").strip() or None
    industry_filter = (request.args.get("industry") or "").strip() or None
    owner_filter = (request.args.get("owner") or "").strip().lower() or None
    try:
        limit = max(1, min(int(request.args.get("limit") or 50), 200))
    except ValueError:
        limit = 50

    def _matches_q(c: dict) -> bool:
        if not q:
            return True
        for field in ("name", "email", "title", "country"):
            if q in str(c.get(field) or "").lower():
                return True
        return False

    def _matches_owner(c: dict) -> bool:
        if not owner_filter:
            return True
        return owner_filter in str(c.get("mr_owner") or "").lower()

    def _matches_status(c: dict) -> bool:
        if not status_filter:
            return True
        return (c.get("status") or "active").lower() == status_filter

    lead_hits: list[dict] = []
    partner_hits: list[dict] = []

    # --- Lead-side scan ---
    # Owner filter currently isn't a field on lead contacts (only partner
    # contacts have mr_owner). If owner_filter is set, skip the lead-side
    # scan entirely — they'd all fail the filter anyway.
    # Territory/region/industry are partner-only fields; same skip.
    skip_leads = bool(owner_filter or territory_filter or region_filter or industry_filter)
    if not skip_leads and surface_filter != "partner":
        try:
            lead_dir = contacts_store._store_dir()
            if lead_dir.exists():
                for f in lead_dir.glob("*.json"):
                    lead_slug = f.stem
                    try:
                        import json as _json
                        rows = _json.loads(f.read_text())
                    except (OSError, ValueError):
                        continue
                    if not isinstance(rows, list):
                        continue
                    for r in rows:
                        if not _matches_q(r) or not _matches_status(r):
                            continue
                        contacts_store.annotate_touch_state(r)
                        lead_hits.append({
                            **r,
                            "surface": "lead",
                            "parent_id": lead_slug,
                            "parent_name": lead_slug,  # UI may swap for display name
                        })
                        if len(lead_hits) >= limit:
                            break
                    if len(lead_hits) >= limit:
                        break
        except Exception as e:
            log.warning("Lead search scan failed: %s", e)

    # Enrich lead-side parent_name with the pipeline display name where we can.
    if lead_hits:
        try:
            sync = NotionSync()
            name_by_slug = {project_store.slugify(row.get("id") or row.get("company") or ""):
                             row.get("company") for row in sync.list_pipeline(limit=500)}
            for r in lead_hits:
                disp = name_by_slug.get(r["parent_id"])
                if disp:
                    r["parent_name"] = disp
        except Exception:
            pass

    # --- Partner-side scan ---
    if surface_filter != "lead":
        try:
            partners_by_id = {p["id"]: p for p in partners_store.list_partners()}
            for partner_id in partners_by_id:
                contacts = partner_contacts_store.list_contacts(partner_id)
                for c in contacts:
                    if not _matches_q(c) or not _matches_status(c):
                        continue
                    if not _matches_owner(c):
                        continue
                    # v1.0.0e: territory/region are now lists. Match if
                    # the filter is in EITHER the list (new shape) OR
                    # equals the singular field (legacy shape).
                    if territory_filter:
                        terrs = c.get("territories") or []
                        if territory_filter not in terrs and c.get("territory") != territory_filter:
                            continue
                    if region_filter:
                        regs = c.get("regions") or []
                        if region_filter not in regs and c.get("region") != region_filter:
                            continue
                    if industry_filter and industry_filter not in (c.get("industries") or []):
                        continue
                    partner_hits.append({
                        **c,
                        "surface": "partner",
                        "parent_id": partner_id,
                        "parent_name": partners_by_id[partner_id].get("name") or partner_id,
                    })
                    if len(partner_hits) >= limit:
                        break
                if len(partner_hits) >= limit:
                    break
        except Exception as e:
            log.warning("Partner search scan failed: %s", e)

    # Sort: overdue first within each surface (highest signal),
    # then alpha by name. Caller can sort differently if they want.
    def _sort_key(c: dict):
        return (not c.get("overdue"), (c.get("name") or "").lower())
    lead_hits.sort(key=_sort_key)
    partner_hits.sort(key=_sort_key)
    return jsonify({
        "lead": lead_hits,
        "partner": partner_hits,
        "total": len(lead_hits) + len(partner_hits),
    })


@app.route("/api/contacts/overdue", methods=["GET"])
def api_contacts_overdue():
    """Cross-lead overdue contacts roster. Used by Today/overview surface."""
    rows = contacts_store.overdue_contacts(lead_id=None)
    # Sort most-overdue first.
    rows.sort(key=lambda c: c.get("days_until_due") or 0)
    return jsonify({"overdue": rows, "count": len(rows)})


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

    # v0.10.0x: pre-fill project scope criteria from the notes.
    # If extract_from_notes returned scope_criteria (per-project-type
    # field values), merge them into the lead's project. Only fills
    # criteria that are currently EMPTY — never overwrites AE-confirmed
    # values. Tracks which fields came from AI so the UI can flag them
    # for review.
    scope_prefill_applied: list[dict] = []
    if extracted and isinstance(extracted.get("scope_criteria"), dict):
        try:
            scope_prefill_applied = _apply_scope_prefill(
                lead_id, extracted["scope_criteria"], record["id"]
            )
        except Exception as e:
            log.warning("Scope prefill failed for %s: %s", lead_id, e)

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
                # v1.0.0q: attach most-recent-call metadata before saving
                # so the UI's "Last call: <date>" line stays accurate.
                calls_for_meta = calls_store.list_calls(lead_id)
                if calls_for_meta:
                    latest_c = calls_for_meta[0]
                    synth["most_recent_call_at"]    = latest_c.get("created_at")
                    synth["most_recent_call_type"]  = latest_c.get("type")
                    synth["most_recent_call_title"] = latest_c.get("title")
                    synth["calls_count"]            = len(calls_for_meta)
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

    # v1.0.0f (Tier 3c): contact suggestions. Dedupe AI-extracted names
    # against existing lead contacts so the UI only offers genuinely
    # new ones. Match is case-insensitive on name OR email.
    contact_suggestions: list[dict] = []
    if extracted and isinstance(extracted.get("contacts_mentioned"), list):
        try:
            existing = contacts_store.list_contacts(lead_id)
            existing_names = {(c.get("name") or "").strip().lower()
                              for c in existing if c.get("name")}
            existing_emails = {(c.get("email") or "").strip().lower()
                               for c in existing if c.get("email")}
            for m in extracted["contacts_mentioned"]:
                if not isinstance(m, dict):
                    continue
                name = (m.get("name") or "").strip()
                if not name:
                    continue
                if name.lower() in existing_names:
                    continue
                email = (m.get("email") or "").strip()
                if email and email.lower() in existing_emails:
                    continue
                # Skip MR-side and partner-side people — they don't belong
                # in the LEAD's contact list. Surface only prospect-side
                # and unknown (AE can confirm).
                role = (m.get("role") or "unknown").lower()
                if role in ("mr-side", "partner-side"):
                    continue
                contact_suggestions.append({
                    "name": name,
                    "title": m.get("title"),
                    "email": email or None,
                    "role": role,
                })
        except Exception as e:
            log.warning("Contact suggestion dedupe failed for %s: %s", lead_id, e)

    # v1.0.0g: mirror full state to Notion after every call save — the
    # call is the highest-pain loss case if cache disappears. Best-effort.
    _mirror_state_to_notion(lead_id)

    return jsonify({
        "call": record,
        "rolling": calls_store.aggregate_extractions(lead_id),
        # New: the freshly-synthesised summary if AI re-ran successfully.
        # UI renders this without an extra GET to /summary.
        "summary": fresh_summary,
        # v0.10.0x: list of {project_type, key, value} the AI auto-filled
        # in the project_store from this note. Empty list when nothing
        # was auto-filled. UI uses this to show a "✨ AI pre-filled N
        # criteria" toast + visual hint on the Project Build view.
        "scope_prefill": scope_prefill_applied,
        # v1.0.0f: new contacts the AI noticed in the notes that aren't
        # already in the lead's contact list. UI offers a one-click
        # "Add these" panel.
        "contact_suggestions": contact_suggestions,
    })


# v0.10.0x: helper to merge AI-extracted scope criteria into the lead's
# project. Lives in server because it ties together extracted data
# (from ai_summary) with the project_store mutation.
def _apply_scope_prefill(lead_id: str, scope_criteria: dict, source_call_id: str) -> list[dict]:
    """Merge AI-extracted scope criteria into the lead's project.

    Rules:
      1. Only writes to criteria that are currently empty. Never
         overwrites AE-confirmed values.
      2. Only writes to streams that EXIST on the project. If a project
         type was extracted but no matching stream exists, we skip it
         (don't auto-add streams — that's the AE's decision).
      3. Adds `ai_suggested: true` + `ai_source_call_id` to the criterion
         so the UI can show "✨ AI" badges and the AE can audit later.

    Returns a list of {project_type, key, value} for each field actually
    written. Empty list when nothing changed (no project, no matching
    streams, all criteria already filled).
    """
    project = project_store.load(lead_id)
    if project is None:
        return []
    applied: list[dict] = []
    changed = False
    for pt, fields in (scope_criteria or {}).items():
        if not isinstance(fields, dict):
            continue
        # Find the matching stream on the project (skip if not present).
        stream = next((s for s in project.streams if s.project_type == pt), None)
        if stream is None:
            continue
        # Build a key→criterion lookup so we can match efficiently.
        crit_by_key = {c.key: c for c in stream.criteria}
        for k, v in fields.items():
            crit = crit_by_key.get(k)
            if crit is None:
                continue  # AI suggested a key we don't have in the library
            if (crit.value or "").strip():
                continue  # AE has already filled this — never overwrite
            # Write the value + audit metadata
            crit.value = str(v).strip()
            # Annotate on the dataclass — these dynamic attrs survive to_dict
            # because project_store serialises whatever the dataclass holds.
            try:
                setattr(crit, "ai_suggested", True)
                setattr(crit, "ai_source_call_id", source_call_id)
            except Exception:
                pass  # dataclass may be frozen on some versions; we accept the loss
            applied.append({
                "project_type": pt,
                "key": k,
                "value": str(v).strip(),
            })
            changed = True
    if changed:
        project_store.save(project)
        audit.log_event("scope_prefilled_from_notes", actor=_actor(),
                        lead_id=lead_id, source_call_id=source_call_id,
                        count=len(applied),
                        fields=[a["key"] for a in applied])
    return applied


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


def _rescore_lead_from_notion(sync: "NotionSync", page_id: str) -> dict:
    """Pull the lead's current Notion values, recompute ICP, write back.

    Returns: {normalized_score, status, status_label, opportunity_type,
              opportunity_label, lead}. Raises NotionSyncError on Notion failure
              or Exception on scoring failure (caller decides how to surface).
    """
    from scoring import calculate_icp_score
    lead = sync.get_page(page_id) or {}
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
    sync.update_page(page_id, {
        "icp_normalised": new_score.get("normalized_score"),
        "icp_total": new_score.get("total_weighted"),
        "opportunity_type_key": new_score.get("opportunity_type"),
    })
    # Patch the lead dict so callers can return a fresh snapshot.
    lead["icp_normalised"] = new_score.get("normalized_score")
    return {
        "normalized_score":  new_score.get("normalized_score"),
        "total_weighted":    new_score.get("total_weighted"),
        "status":            new_score.get("status"),
        "status_label":      new_score.get("status_label"),
        "opportunity_type":  new_score.get("opportunity_type"),
        "opportunity_label": new_score.get("opportunity_label"),
        "lead":              lead,
    }


@app.route("/api/lead/<page_id>/rescore", methods=["POST"])
def api_lead_rescore(page_id: str):
    """v0.10.0w: explicit rescore endpoint — recomputes ICP from the
    lead's current Notion state without any edits.

    Use case: AE has touched up fields in Notion directly, or wants
    to refresh the score after the scoring weights changed, without
    needing to PATCH a field just to trigger the rescore side-effect.
    """
    try:
        sync = NotionSync()
        result = _rescore_lead_from_notion(sync, page_id)
        audit.log_event("lead_rescored", actor=_actor(), page_id=page_id,
                        trigger="manual",
                        new_score=result.get("normalized_score"))
        return jsonify({
            "rescored": True,
            "new_score": result,
            "lead": result.get("lead"),
        })
    except (NotionSyncError, ValueError) as e:
        log.warning("Rescore failed for %s: %s", page_id, e)
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        log.exception("Rescore crashed for %s", page_id)
        return jsonify({"error": str(e)}), 500


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
        # v1.0.0g: durable backup after project save.
        _mirror_state_to_notion(lead_id)
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
            # v1.0.0z: who told us this. Empty for internal notes.
            "partner_source": c.get("partner_source") or None,
        }
        for c in calls[:6]
    ]
    ctx["calls_total"] = len(calls)
    # Contacts
    ctx["contacts"] = contacts_store.list_contacts(lead_id)
    # v1.0.0p: agencies (incumbent + previous) — gives Claude the
    # displacement angle ("VML runs Braze today, fired Razorfish in
    # 2022 over data-quality issues").
    ctx["agencies"] = lead_agencies_store.list_agencies(lead_id)
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
    # v1.0.0q: attach the most-recent-call metadata so the UI can show
    # "Last call: <date>" prominently. calls_store.list_calls returns
    # newest-first.
    calls_for_meta = calls_store.list_calls(lead_id)
    if calls_for_meta:
        latest = calls_for_meta[0]
        result["most_recent_call_at"]   = latest.get("created_at")
        result["most_recent_call_type"] = latest.get("type")
        result["most_recent_call_title"] = latest.get("title")
        result["calls_count"]           = len(calls_for_meta)
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


# v0.10.0v: Project briefing preview ----------------------------------------
# Renders the full current Project Build state as a single printable HTML
# document. Same modal-preview UX as SOW, but earlier in the cycle — an
# internal briefing the AE shares with the delivery team or stakeholders
# without drafting a formal SOW.

def _gather_project_preview_snapshot(lead_id: str) -> dict:
    """Build the snapshot project_preview.render_html expects."""
    from datetime import datetime, timezone

    ctx: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    # Lead identity (Notion-side)
    try:
        sync = NotionSync()
        lead = sync.get_page(lead_id)
        ctx["lead"] = lead or {}
        ctx["company_name"] = (lead or {}).get("company") or lead_id
    except Exception:
        ctx["lead"] = {}
        ctx["company_name"] = lead_id

    # Cached AI summary
    cached_summary = lead_summary_store.load(lead_id)
    ctx["summary"] = cached_summary or None

    # BANT health from rolling MEDDPICC + scope
    rolling = calls_store.aggregate_extractions(lead_id)
    scope_state_for_bant = None
    p = project_store.load(lead_id)
    if p is not None:
        scope_state_for_bant = {
            "streams": [
                {"project_type": s.project_type,
                 "validation_status": getattr(s, "validation_status", "draft")}
                for s in p.streams
            ],
            "project_scope": (rolling or {}).get("project_scope") or "",
        }
    ctx["bant_health"] = bant_health.derive_bant_health(
        (rolling or {}).get("meddpicc") or {},
        scope_state=scope_state_for_bant,
    )

    # Scope (criteria with values)
    if p is not None:
        ctx["scope"] = {
            "project_types": [s.project_type for s in p.streams],
            "streams": [
                {
                    "project_type": s.project_type,
                    "validation_status": getattr(s, "validation_status", "draft"),
                    "criteria": [
                        {"key": c.key, "label": getattr(c, "label", c.key),
                         "value": c.value, "health": getattr(c, "health", None)}
                        for c in s.criteria
                    ],
                }
                for s in p.streams
            ],
        }
    else:
        ctx["scope"] = None

    # Pricing snapshot (best-effort — uses pricing_store if any saved config)
    try:
        pricing_cfg = pricing_store.load(lead_id) if pricing_store else None
        if pricing_cfg and p is not None:
            from pricing import compute_quote, QuoteInputs
            quote = compute_quote(QuoteInputs(
                project_types=[s.project_type for s in p.streams],
                months=int(pricing_cfg.get("months", 12)),
                discount_pct_first_half=float(pricing_cfg.get("discount_first_half_pct", 0.15) or 0),
                discount_pct_second_half=float(pricing_cfg.get("discount_second_half_pct", 0.0) or 0),
                role_overrides=pricing_cfg.get("role_overrides") or {},
                effort_multipliers=scope_module.role_drivers_for_project(p),
                currency=(pricing_cfg.get("currency") or "USD").upper(),
                rate_card=pricing_cfg.get("rate_card") or "MR Default",
                project_ops_pct=float(pricing_cfg.get("project_ops_pct") or 0),
                contingency_pct=float(pricing_cfg.get("contingency_pct") or 0),
                role_staffing=pricing_cfg.get("role_staffing") or {},
            ))
            totals = quote.get("totals") or {}
            ctx["pricing"] = {
                "currency": pricing_cfg.get("currency") or "USD",
                "rate_card": pricing_cfg.get("rate_card") or "MR Default",
                "months": pricing_cfg.get("months", 12),
                "totals": {
                    "gross": totals.get("gross_usd") or totals.get("gross"),
                    "net":   totals.get("net_usd")   or totals.get("net"),
                    "discount": totals.get("discount_usd") or totals.get("discount"),
                },
                "phase_breakdown": quote.get("phase_breakdown") or [],
                "team_breakdown": quote.get("team_breakdown") or [],
            }
        else:
            ctx["pricing"] = None
    except Exception as e:
        log.warning("Pricing render for project preview failed: %s", e)
        ctx["pricing"] = None

    # Roadmap
    try:
        rm = roadmap_module.load(lead_id) if roadmap_module else None
        if rm is not None:
            d = roadmap_module.to_dict(rm)
            ctx["roadmap"] = {
                "start_date": d.get("start_date"),
                "end_date":   d.get("end_date"),
                "milestones": d.get("milestones") or [],
                "extended_items": d.get("extended_items") or [],
            }
        else:
            ctx["roadmap"] = None
    except Exception as e:
        log.warning("Roadmap render for project preview failed: %s", e)
        ctx["roadmap"] = None

    return ctx


@app.route("/api/project/<lead_id>/preview.html", methods=["GET"])
def api_project_preview_html(lead_id: str):
    """Full project briefing as printable HTML — scope + BANT + pricing
    + roadmap + AI summary, all in one document. Drives the in-platform
    Preview modal (same one SOWs use)."""
    try:
        snapshot = _gather_project_preview_snapshot(lead_id)
        html = project_preview.render_html(snapshot)
        audit.log_event("project_preview_rendered",
                        actor=_actor(), lead_id=lead_id)
        return Response(html, mimetype="text/html; charset=utf-8")
    except Exception as e:
        log.exception("Project preview render failed: %s", e)
        return Response(f"<h1>Preview failed</h1><pre>{e}</pre>",
                        status=500, mimetype="text/html; charset=utf-8")


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


# --- Partners CRM (v0.10.0y) ----------------------------------------------
# New top-level surface for the Partnerships team to manage partner orgs +
# their contacts. Distinct from leads (orgs we sell TO). Partner contacts
# carry territory / region / country / industries metadata for portfolio
# views, plus a reports_to link the UI can use later for an org chart.

@app.route("/api/partners/enums", methods=["GET"])
def api_partners_enums():
    """Enum lists the UI uses to populate dropdowns. v1.0.0ac: the
    editable lists (industries / territories / regions / statuses +
    the new sentiment/tier/seniority) now come from enum_config_store
    so the Settings panel can edit them without a redeploy. partner_types
    + note_types remain hardcoded — they're tightly coupled to backend
    logic, not display-only enums.
    """
    import enum_config_store
    cfg = enum_config_store.load()
    return jsonify({
        "partner_types":      partners_store.PARTNER_TYPES,
        "territories":        cfg["territories"],
        "regions":            cfg["regions"],
        "industries":         cfg["industries"],
        "statuses":           cfg["statuses"],
        "partner_sentiments": cfg["partner_sentiments"],
        "tiers":              cfg["tiers"],
        "seniorities":        cfg["seniorities"],
        "note_types":         partner_notes_store.NOTE_TYPES,
    })


# v1.0.0ac: editable enum configuration endpoint. The Settings panel
# uses these to add/remove/reorder dropdown options across the platform.
@app.route("/api/settings/enums", methods=["GET"])
def api_settings_enums_get():
    """Return the current effective enum lists (user overrides +
    in-code defaults filling gaps)."""
    import enum_config_store
    return jsonify(enum_config_store.load())


@app.route("/api/settings/enums", methods=["PATCH"])
def api_settings_enums_update():
    """Update one or more enum lists. Body shape:
        { "industries": ["QSR", "Gaming", ...], "tiers": [...] }
    Unknown keys ignored; empty list resets to in-code default."""
    import enum_config_store
    body = request.get_json(silent=True) or {}
    updated = enum_config_store.save(body)
    audit.log_event("enum_config_updated", actor=_actor(),
                    keys=sorted(body.keys()))
    return jsonify(updated)


@app.route("/api/settings/enums/<key>/reset", methods=["POST"])
def api_settings_enums_reset(key: str):
    """Reset a single enum key to its in-code default. The "undo my mess"
    escape hatch in the settings UI."""
    import enum_config_store
    try:
        updated = enum_config_store.reset_key(key)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    audit.log_event("enum_config_reset", actor=_actor(), key=key)
    return jsonify(updated)


# v1.0.0o: MR owners — single source of truth for the people the UI
# offers in every owner / mr_owner dropdown.
@app.route("/api/owners", methods=["GET"])
def api_owners():
    """Return the list of MR owners (lead owner + partner-contact
    `mr_owner`). Includes role + region + email for richer dropdowns."""
    import mr_owners
    return jsonify({"owners": mr_owners.list_owners(active_only=True)})


@app.route("/api/partners", methods=["GET"])
def api_partners_list():
    rows = partners_store.list_partners()
    # Enrich each partner with contact count so the index view can show it.
    for r in rows:
        try:
            r["contacts_count"] = len(partner_contacts_store.list_contacts(r["id"]))
        except Exception:
            r["contacts_count"] = 0
    return jsonify({"partners": rows, "count": len(rows)})


@app.route("/api/partners", methods=["POST"])
def api_partners_create():
    body = request.get_json(silent=True) or {}
    try:
        saved = partners_store.save_partner(body)
    except partners_store.PartnersStoreError as e:
        return jsonify({"error": str(e)}), 400
    audit.log_event("partner_saved", actor=_actor(),
                    partner_id=saved["id"], name=saved["name"])
    return jsonify({"partner": saved}), 201


@app.route("/api/partners/<partner_id>", methods=["GET"])
def api_partners_get(partner_id: str):
    p = partners_store.get_partner(partner_id)
    if not p:
        return jsonify({"error": "not_found"}), 404
    p["contacts"] = partner_contacts_store.list_contacts(p["id"])
    return jsonify({"partner": p})


@app.route("/api/partners/<partner_id>", methods=["PATCH"])
def api_partners_update(partner_id: str):
    body = request.get_json(silent=True) or {}
    existing = partners_store.get_partner(partner_id)
    if not existing:
        return jsonify({"error": "not_found"}), 404
    merged = {**existing, **body, "id": existing["id"]}
    try:
        saved = partners_store.save_partner(merged)
    except partners_store.PartnersStoreError as e:
        return jsonify({"error": str(e)}), 400
    audit.log_event("partner_updated", actor=_actor(),
                    partner_id=saved["id"],
                    fields=sorted([k for k in body.keys() if k != "id"]))
    return jsonify({"partner": saved})


@app.route("/api/partners/<partner_id>", methods=["DELETE"])
def api_partners_delete(partner_id: str):
    contacts = partner_contacts_store.list_contacts(partner_id)
    if contacts:
        return jsonify({"error": f"Partner has {len(contacts)} contacts. "
                                  "Delete or reassign them first."}), 409
    ok = partners_store.delete_partner(partner_id)
    if not ok:
        return jsonify({"error": "not_found"}), 404
    audit.log_event("partner_deleted", actor=_actor(), partner_id=partner_id)
    return jsonify({"deleted": True})


# ----- partner contacts ----------------------------------------------------

@app.route("/api/partners/<partner_id>/contacts", methods=["GET"])
def api_partner_contacts_list(partner_id: str):
    contacts = partner_contacts_store.list_contacts(partner_id)
    return jsonify({"contacts": contacts, "count": len(contacts)})


@app.route("/api/partners/<partner_id>/contacts", methods=["POST"])
def api_partner_contacts_save(partner_id: str):
    body = request.get_json(silent=True) or {}
    # Bulk path: {contacts: [...]}
    if "contacts" in body and isinstance(body["contacts"], list):
        saved = []
        for c in body["contacts"]:
            try:
                saved.append(partner_contacts_store.save_contact(partner_id, c))
            except partner_contacts_store.PartnerContactsStoreError:
                continue
        audit.log_event("partner_contacts_saved", actor=_actor(),
                        partner_id=partner_id, count=len(saved))
        return jsonify({"saved": saved,
                        "contacts": partner_contacts_store.list_contacts(partner_id)})
    try:
        saved_one = partner_contacts_store.save_contact(partner_id, body)
    except partner_contacts_store.PartnerContactsStoreError as e:
        return jsonify({"error": str(e)}), 400
    audit.log_event("partner_contact_saved", actor=_actor(),
                    partner_id=partner_id, contact_id=saved_one["id"])
    return jsonify({"contact": saved_one,
                    "contacts": partner_contacts_store.list_contacts(partner_id)})


@app.route("/api/partners/<partner_id>/contacts/<contact_id>", methods=["PATCH"])
def api_partner_contacts_update(partner_id: str, contact_id: str):
    existing = partner_contacts_store.get_contact(partner_id, contact_id)
    if not existing:
        return jsonify({"error": "not_found"}), 404
    body = request.get_json(silent=True) or {}
    merged = {**existing, **body, "id": contact_id, "partner_id": existing["partner_id"]}
    try:
        saved = partner_contacts_store.save_contact(partner_id, merged)
    except partner_contacts_store.PartnerContactsStoreError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"contact": saved})


@app.route("/api/partners/<partner_id>/contacts/<contact_id>", methods=["DELETE"])
def api_partner_contacts_delete(partner_id: str, contact_id: str):
    ok = partner_contacts_store.delete_contact(partner_id, contact_id)
    if not ok:
        return jsonify({"error": "not_found"}), 404
    # Cascade-delete notes so they don't leak as orphans.
    partner_notes_store.delete_all_for_contact(partner_id, contact_id)
    audit.log_event("partner_contact_deleted", actor=_actor(),
                    partner_id=partner_id, contact_id=contact_id)
    return jsonify({"deleted": True})


# ----- partner contact notes ----------------------------------------------

@app.route("/api/partners/<partner_id>/contacts/<contact_id>/notes", methods=["GET"])
def api_partner_notes_list(partner_id: str, contact_id: str):
    return jsonify({"notes": partner_notes_store.list_notes(partner_id, contact_id)})


@app.route("/api/partners/<partner_id>/contacts/<contact_id>/notes", methods=["POST"])
def api_partner_notes_add(partner_id: str, contact_id: str):
    body = request.get_json(silent=True) or {}
    body.setdefault("author", _actor())
    try:
        note = partner_notes_store.add_note(partner_id, contact_id, body)
    except partner_notes_store.PartnerNotesStoreError as e:
        return jsonify({"error": str(e)}), 400
    # v0.10.0z: a note IS a touch — bump last_touched_at so the cadence
    # clock resets. AE doesn't need a separate "log a touch" action.
    touched = partner_contacts_store.touch_contact(partner_id, contact_id)
    audit.log_event("partner_note_added", actor=_actor(),
                    partner_id=partner_id, contact_id=contact_id,
                    note_id=note["id"], touched=bool(touched))
    # v1.0.0m: re-run the partner-contact conversation synthesis after
    # every note save, so the summary panel reflects the latest add.
    # Best-effort — failure is logged, never blocks the user-visible save.
    fresh_summary = _refresh_partner_contact_summary(partner_id, contact_id)
    return jsonify({
        "note": note,
        "notes": partner_notes_store.list_notes(partner_id, contact_id),
        # Returning the freshly-bumped contact so the UI can update the
        # "Last touch" cell in-place without another fetch.
        "contact": partner_contacts_store.annotate_touch_state(touched) if touched else None,
        "summary": fresh_summary,
    })


def _refresh_partner_contact_summary(partner_id: str, contact_id: str):
    """Build the payload + run Claude + cache. Returns the summary dict
    or None if AI is unconfigured / errored. Wrapped here so the
    add-note path + the explicit refresh endpoint share one
    implementation."""
    try:
        import ai_summary
        contact = partner_contacts_store.get_contact(partner_id, contact_id)
        if contact is None:
            return None
        partner = partners_store.get_partner(partner_id)
        notes = partner_notes_store.list_notes(partner_id, contact_id)
        if not notes:
            # No notes to synthesise. Clear any stale cached summary.
            partner_contact_summary_store.delete(partner_id, contact_id)
            return None
        # The notes list is already ordered newest-first by the store.
        # We pass them as-is and flag the head as the most recent so the
        # prompt can lean on it for the `summary` field.
        notes_for_prompt = []
        for i, n in enumerate(notes):
            entry = dict(n)
            entry["is_most_recent"] = (i == 0)
            notes_for_prompt.append(entry)
        payload = {
            "partner": {
                "id": partner.get("id") if partner else partner_id,
                "name": (partner or {}).get("name") or "",
                "type": (partner or {}).get("type") or "",
            },
            "contact": {
                "id": contact.get("id"),
                "name": contact.get("name"),
                "title": contact.get("title"),
                "email": contact.get("email"),
                "territories": contact.get("territories") or [],
                "regions": contact.get("regions") or [],
                "country": contact.get("country"),
                "industries": contact.get("industries") or [],
                "mr_owner": contact.get("mr_owner"),
            },
            "notes": notes_for_prompt,
        }
        summary = ai_summary.synthesise_partner_contact_conversation(payload)
        if summary is None:
            return None
        # v1.0.0q: attach the most-recent-note metadata so the UI can
        # render "Last call: <date>" instead of the synthesis-generation
        # timestamp. notes[0] is newest because list_notes sorts desc.
        latest = notes[0]
        summary["most_recent_note_at"]   = latest.get("created_at")
        summary["most_recent_note_type"] = latest.get("type")
        summary["notes_count"]           = len(notes)
        saved = partner_contact_summary_store.save(partner_id, contact_id, summary)
        return saved
    except Exception as e:
        log.warning("Partner-contact summary refresh failed for %s/%s: %s",
                     partner_id, contact_id, e)
        return None


@app.route("/api/partners/<partner_id>/contacts/<contact_id>/summary",
            methods=["GET"])
def api_partner_contact_summary_get(partner_id: str, contact_id: str):
    """Return the cached partner-contact synthesis. The UI calls this
    when opening the notes modal to render the summary panel without
    spending tokens on every open."""
    summary = partner_contact_summary_store.load(partner_id, contact_id)
    return jsonify({"summary": summary})


@app.route("/api/partners/<partner_id>/contacts/<contact_id>/summary",
            methods=["POST"])
def api_partner_contact_summary_refresh(partner_id: str, contact_id: str):
    """Force a fresh synthesis run. Used by the ✨ Refresh button in the
    notes modal — useful if the AE wants to re-synthesise after editing
    notes manually, or when AI was off when the last note was added."""
    summary = _refresh_partner_contact_summary(partner_id, contact_id)
    if summary is None:
        return jsonify({"summary": None,
                         "error": "AI is off or synthesis failed — set "
                                  "ANTHROPIC_API_KEY in the environment."}), 200
    return jsonify({"summary": summary})


# v0.10.0z: overdue contacts roster — Today/overview surface.
@app.route("/api/partners/overdue", methods=["GET"])
def api_partners_overdue():
    """Across-partner overdue contacts. Optional ?owner= filters to MR
    owner (so each AE can see their own list)."""
    owner = (request.args.get("owner") or "").strip()
    rows = partner_contacts_store.overdue_contacts(partner_id=None)
    if owner:
        rows = [c for c in rows if (c.get("mr_owner") or "").lower() == owner.lower()]
    # Sort most-overdue first so the worst offenders are at the top.
    rows.sort(key=lambda c: c.get("days_until_due") or 0)
    # Enrich with partner name for the UI list.
    partners_by_id = {p["id"]: p for p in partners_store.list_partners()}
    for r in rows:
        pid = r.get("partner_id")
        r["partner_name"] = (partners_by_id.get(pid) or {}).get("name") or pid
    return jsonify({"overdue": rows, "count": len(rows)})


@app.route("/api/partners/<partner_id>/contacts/<contact_id>/touch", methods=["POST"])
def api_partner_contact_touch(partner_id: str, contact_id: str):
    """Explicit 'log a touch' without a note. AE clicks 'mark as touched'
    after an off-platform interaction (Slack DM, conference chat, etc.)."""
    touched = partner_contacts_store.touch_contact(partner_id, contact_id)
    if not touched:
        return jsonify({"error": "not_found"}), 404
    audit.log_event("partner_contact_touched", actor=_actor(),
                    partner_id=partner_id, contact_id=contact_id)
    return jsonify({"contact": partner_contacts_store.annotate_touch_state(touched)})


@app.route("/api/partners/<partner_id>/contacts/<contact_id>/notes/<note_id>", methods=["DELETE"])
def api_partner_notes_delete(partner_id: str, contact_id: str, note_id: str):
    ok = partner_notes_store.delete_note(partner_id, contact_id, note_id)
    if not ok:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"deleted": True})


# v1.0.0z: rollup — every lead-side call/note across the whole pipeline
# whose partner_source matches this partner contact. Surfaces "every
# piece of intel Marina has contributed" on her contact card so Ben
# can see her cumulative value.
@app.route("/api/partners/<partner_id>/contacts/<contact_id>/sourced-calls",
            methods=["GET"])
def api_partner_contact_sourced_calls(partner_id: str, contact_id: str):
    rows = calls_store.list_calls_sourced_from(
        partner_id=partner_id, contact_id=contact_id,
    )
    return jsonify({"calls": rows, "count": len(rows)})


# --- Lead ↔ Partner-contact assignments (v0.11.0) -------------------------
# Links a partner contact (Marina at Braze) to a lead (Yum Brands) so the
# AE knows who the right partner-side person is for the account.

@app.route("/api/lead/<lead_id>/partner-contacts", methods=["GET"])
def api_lead_partner_contacts(lead_id: str):
    """Return assigned partner contacts for a lead, enriched with the
    full partner + contact records so the UI can render without a
    bunch of follow-up fetches."""
    raw = lead_partner_assignments.list_for_lead(lead_id)
    if not raw:
        return jsonify({"assignments": []})
    # Cache partners by id to avoid repeat reads.
    partners_by_id = {p["id"]: p for p in partners_store.list_partners()}
    enriched: list[dict] = []
    for r in raw:
        pid = r.get("partner_id")
        cid = r.get("contact_id")
        partner = partners_by_id.get(pid) or {}
        contact = partner_contacts_store.get_contact(pid, cid) if pid and cid else None
        if contact:
            partner_contacts_store.annotate_touch_state(contact)
        enriched.append({
            **r,
            "partner_name": partner.get("name") or pid,
            "partner_url": partner.get("url"),
            "partner_type": partner.get("type"),
            "contact": contact,  # may be None if the contact was deleted
        })
    return jsonify({"assignments": enriched, "count": len(enriched)})


@app.route("/api/lead/<lead_id>/partner-contacts", methods=["POST"])
def api_lead_assign_partner_contact(lead_id: str):
    """Assign one or many partner contacts to a lead.

    Body (single):
      {partner_id, contact_id, note?}

    Body (bulk):
      {assignments: [{partner_id, contact_id, note?}, ...]}
    """
    body = request.get_json(silent=True) or {}
    bulk = body.get("assignments")
    by = _actor()
    saved: list[dict] = []
    try:
        if isinstance(bulk, list):
            for a in bulk:
                pid = (a or {}).get("partner_id")
                cid = (a or {}).get("contact_id")
                if not pid or not cid:
                    continue
                saved.append(lead_partner_assignments.assign(
                    lead_id, pid, cid,
                    assigned_by=by, note=(a.get("note") or None),
                ))
        else:
            pid = body.get("partner_id")
            cid = body.get("contact_id")
            if not pid or not cid:
                return jsonify({"error": "partner_id and contact_id required"}), 400
            saved.append(lead_partner_assignments.assign(
                lead_id, pid, cid,
                assigned_by=by, note=body.get("note"),
            ))
    except lead_partner_assignments.AssignmentsStoreError as e:
        return jsonify({"error": str(e)}), 400
    audit.log_event("partner_contact_assigned", actor=by,
                    lead_id=lead_id, count=len(saved))
    return jsonify({"saved": saved, "count": len(saved)})


@app.route("/api/lead/<lead_id>/partner-contacts/<partner_id>/<contact_id>",
           methods=["DELETE"])
def api_lead_unassign_partner_contact(lead_id: str, partner_id: str, contact_id: str):
    ok = lead_partner_assignments.unassign(lead_id, partner_id, contact_id)
    if not ok:
        return jsonify({"error": "not_found"}), 404
    audit.log_event("partner_contact_unassigned", actor=_actor(),
                    lead_id=lead_id, partner_id=partner_id,
                    contact_id=contact_id)
    return jsonify({"removed": True})


# Reverse lookup: which leads is a partner-contact assigned to?
@app.route("/api/partners/<partner_id>/contacts/<contact_id>/assigned-leads",
           methods=["GET"])
def api_partner_contact_assigned_leads(partner_id: str, contact_id: str):
    rows = lead_partner_assignments.list_for_contact(partner_id, contact_id)
    # Best-effort lead-name lookup from the pipeline.
    name_by_slug: dict[str, str] = {}
    try:
        sync = NotionSync()
        for row in sync.list_pipeline(limit=500):
            slug = project_store.slugify(row.get("id") or row.get("company") or "")
            if slug:
                name_by_slug[slug] = row.get("company") or slug
    except Exception:
        pass
    for r in rows:
        r["lead_name"] = name_by_slug.get(r.get("lead_id") or "", r.get("lead_id"))
    return jsonify({"leads": rows, "count": len(rows)})


# v1.0.0g: durable state backup / restore -----------------------------------
# Railway's filesystem is ephemeral — every deploy wipes cache/. The
# defence is to mirror every critical write to a "State Backup" rich-text
# property on the lead's Notion page. Recoverable via /restore.

# v1.0.0i: ring buffer of recent mirror attempts. Surfaced via
# /api/diagnostics/health so silent failures stop being silent.
# Bounded so it can't grow forever.
import collections as _collections
_BACKUP_HEALTH: _collections.deque = _collections.deque(maxlen=20)
_BACKUP_PROPERTY_READY: dict = {"checked": False, "existed": False,
                                 "created": False, "error": None}


# v1.0.0s: tracks whether we've attempted the lazy ensure-properties
# retry yet. Without this, every mirror call would re-attempt the
# Notion schema check, masking real errors with retry noise.
_BACKUP_LAZY_RETRY_DONE = False


def _maybe_lazy_retry_ensure_properties():
    """If the boot-time self-heal errored (e.g. Notion was unreachable
    on first import), try the schema check ONCE here, just before the
    first real mirror attempt. After that we don't retry — repeated
    failures need human attention via the diagnostics endpoint, not
    silent retry loops.
    """
    global _BACKUP_LAZY_RETRY_DONE, _BACKUP_PROPERTY_READY
    if _BACKUP_LAZY_RETRY_DONE:
        return
    if _BACKUP_PROPERTY_READY.get("error") is None:
        # Boot self-heal succeeded — nothing to retry.
        _BACKUP_LAZY_RETRY_DONE = True
        return
    _BACKUP_LAZY_RETRY_DONE = True
    try:
        sync = NotionSync()
        result = sync.ensure_properties({
            "State Backup":              {"rich_text": {}},
            "Expected Close Date":       {"date": {}},
            "Deal Value (Monthly GBP)":  {"number": {"format": "pound"}},
        })
        _BACKUP_PROPERTY_READY = result
        if result.get("created"):
            log.info("Lazy ensure_properties retry created: %s",
                      ", ".join(result["created"]))
    except Exception as e:
        log.warning("Lazy ensure_properties retry failed: %s", e)


def _mirror_state_to_notion(lead_id: str) -> bool:
    """Pull the lead's full local state and write the chunked backup blob
    to its Notion page. Best-effort — failure is logged, not raised, so
    a Notion outage never blocks the user-visible save.

    v1.0.0i: records the attempt in _BACKUP_HEALTH so the diagnostic
    surface can show recent successes/failures. A streak of failures
    here usually means the "State Backup" property is missing — the
    boot-time self-heal should have created it, but if Notion creds
    changed or DB swapped, we need visibility.

    v1.0.0s: if the boot self-heal errored (Notion unreachable on first
    import), this function lazy-retries the ensure-properties call once
    before the first mirror attempt. Guarded by _BACKUP_LAZY_RETRY_DONE.
    """
    from datetime import datetime, timezone
    # v1.0.0s: one-shot retry of ensure_properties if boot self-heal
    # failed. Cheap (single GET + maybe one PATCH) and idempotent.
    _maybe_lazy_retry_ensure_properties()
    attempt = {
        "lead_id": lead_id,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "ok": False,
        "error": None,
        "bytes": 0,
        "chunks": 0,
    }
    try:
        payload = state_backup.gather(lead_id)
        blob = state_backup.encode(payload)
        chunks = state_backup.chunk_for_notion(blob)
        attempt["bytes"] = len(blob)
        attempt["chunks"] = len(chunks)
        sync = NotionSync()
        sync.update_page(lead_id, {"state_backup_chunks": chunks})
        attempt["ok"] = True
        _BACKUP_HEALTH.append(attempt)
        return True
    except Exception as e:
        attempt["error"] = str(e)[:300]
        _BACKUP_HEALTH.append(attempt)
        log.warning("State backup mirror failed for %s: %s", lead_id, e)
        return False


@app.route("/api/lead/<page_id>/backup", methods=["GET"])
def api_lead_backup(page_id: str):
    """Return the lead's full state as a JSON download. Useful as a
    pre-deploy safety net (Ben can save this locally before pushing)."""
    try:
        payload = state_backup.gather(page_id)
        return jsonify({"payload": payload, "encoded": state_backup.encode(payload)})
    except Exception as e:
        log.exception("Backup gather failed for %s", page_id)
        return jsonify({"error": str(e)}), 500


@app.route("/api/lead/<page_id>/backup/mirror", methods=["POST"])
def api_lead_backup_mirror(page_id: str):
    """Explicit 'save backup to Notion now' button. Same logic as the
    auto-mirror on writes, surfaced as a manual action for paranoia /
    after-the-fact safety."""
    ok = _mirror_state_to_notion(page_id)
    if not ok:
        return jsonify({"error": "mirror failed — see server log"}), 502
    audit.log_event("state_backup_mirrored", actor=_actor(), page_id=page_id,
                    trigger="manual")
    return jsonify({"mirrored": True})


@app.route("/api/lead/<page_id>/restore", methods=["POST"])
def api_lead_restore(page_id: str):
    """Restore from the Notion state-backup property. Triggered by the
    AE when they notice local cache is empty (post-redeploy)."""
    try:
        sync = NotionSync()
        page = sync.get_page(page_id)
        blob = (page or {}).get("state_backup") or ""
        if not blob:
            return jsonify({"error": "no backup found on this lead's Notion page",
                             "hint": "save the lead via the drawer first so an "
                                      "auto-mirror runs, or POST /backup/mirror"}), 404
        payload = state_backup.decode(blob)
        summary = state_backup.apply_backup(page_id, payload)
        audit.log_event("state_backup_restored", actor=_actor(),
                        page_id=page_id, summary=summary)
        return jsonify({"restored": True, "summary": summary,
                         "captured_at": payload.get("captured_at")})
    except (NotionSyncError, ValueError) as e:
        log.warning("Restore failed for %s: %s", page_id, e)
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        log.exception("Restore crashed for %s", page_id)
        return jsonify({"error": str(e)}), 500


# v1.0.0i: diagnostics + boot-time self-heal of the Notion backup property.

@app.route("/api/diagnostics/health", methods=["GET"])
def api_diagnostics_health():
    """Surface the state-of-the-state-backup system. The UI polls this to
    decide whether to show the "cache wipe likely" banner."""
    from datetime import datetime, timezone
    import calls_store

    cache_dir = os.path.join(HERE, "cache")
    cache_exists = os.path.isdir(cache_dir)
    cache_file_count = 0
    leads_with_calls = 0
    if cache_exists:
        try:
            for root, _, files in os.walk(cache_dir):
                cache_file_count += len(files)
        except OSError:
            pass
        try:
            calls_root = os.path.join(cache_dir, "calls")
            if os.path.isdir(calls_root):
                leads_with_calls = sum(
                    1 for f in os.listdir(calls_root) if f.endswith(".json")
                )
        except OSError:
            pass

    # Mirror health — last 20 attempts.
    recent = list(_BACKUP_HEALTH)
    n_attempts = len(recent)
    n_ok = sum(1 for a in recent if a.get("ok"))
    n_fail = n_attempts - n_ok
    last_error = next(
        (a.get("error") for a in reversed(recent) if not a.get("ok")), None
    )

    # Heuristic: a fresh container with empty cache + no successful
    # mirrors yet is a likely cache-wipe scenario.
    cache_wipe_suspected = (
        leads_with_calls == 0 and n_ok == 0
        # ...unless this is a fresh install with nothing to mirror yet
        and cache_file_count <= 2  # may have a few seed files
    )

    return jsonify({
        "version": "1.0.0i",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "cache": {
            "dir_exists": cache_exists,
            "dir_path": cache_dir,
            "file_count": cache_file_count,
            "leads_with_calls": leads_with_calls,
            "wipe_suspected": cache_wipe_suspected,
        },
        "notion_backup_property": _BACKUP_PROPERTY_READY,
        "mirror_health": {
            "attempts_tracked": n_attempts,
            "successes": n_ok,
            "failures": n_fail,
            "last_error": last_error,
            "recent": recent[-5:],  # last 5 attempts with full detail
        },
        "volume_mount_status": {
            "mount_path": "/app/cache",
            "is_mounted": _is_path_on_volume(cache_dir),
            "note": (
                "Mount a persistent Railway volume on /app/cache to make "
                "this permanent. See RAILWAY_VOLUME_MOUNT.md."
            ),
        },
        "command_centre_seed": _COMMAND_CENTRE_SEED_STATUS,
    })


def _is_path_on_volume(path: str) -> bool:
    """Heuristic: on Railway, the volume mount shows up as a separate
    device (different st_dev) from the container root. False if we
    can't determine for any reason (treat as safe-default 'not mounted')."""
    try:
        root_dev = os.stat("/").st_dev
        path_dev = os.stat(path).st_dev
        return root_dev != path_dev
    except OSError:
        return False


@app.route("/api/lead/<page_id>/notion-history", methods=["GET"])
def api_lead_notion_history(page_id: str):
    """v1.0.0i: best-effort recovery surface for PRE-backup data loss.

    Returns the page's current Notion-side text-bearing properties
    (Fit Summary, Next Steps, Positive Signals, Lead Summary, MEDDICC
    Notes). Pairs with a UI hint to open the Notion page directly and
    use Notion's built-in page history (⋯ → Page history) to scroll
    back through revisions of those fields — which may contain
    AI-synthesised traces of notes that lived in cache/ before v1.0.0g.
    """
    try:
        sync = NotionSync()
        return jsonify(sync.get_page_history(page_id))
    except (NotionSyncError, ValueError) as e:
        log.warning("Notion history fetch failed for %s: %s", page_id, e)
        return jsonify({"error": str(e)}), 502


def _boot_self_heal_backup_property():
    """Best-effort: at app startup, ensure the Notion DB has the
    properties we depend on:
      - "State Backup" (v1.0.0g — durable mirror lifeline)
      - "Expected Close Date" (v1.0.0n — forecasting)
      - "Deal Value (Monthly GBP)" (v1.0.0n — forecasting)

    All created in a single batched PATCH. Status captured into the
    module global so /api/diagnostics/health can surface it.

    Never raises — a startup self-heal must never crash the app.
    """
    global _BACKUP_PROPERTY_READY
    try:
        sync = NotionSync()
        result = sync.ensure_properties({
            "State Backup":              {"rich_text": {}},
            "Expected Close Date":       {"date": {}},
            "Deal Value (Monthly GBP)":  {"number": {"format": "pound"}},
        })
        _BACKUP_PROPERTY_READY = result
        if result.get("created"):
            log.info("Created Notion properties on boot: %s",
                      ", ".join(result["created"]))
        if result.get("error"):
            log.warning("Boot self-heal of Notion properties failed: %s",
                         result["error"])
    except Exception as e:
        _BACKUP_PROPERTY_READY = {"checked": True, "existed": [],
                                    "created": [], "error": str(e)}
        log.warning("Boot self-heal threw: %s", e)


# v1.0.0j: auto-seed the Command Centre partners on first boot. Only
# runs if the Braze partner doesn't already exist (so re-deploys are
# no-ops, and user-deleted contacts don't get magically recreated).
# Captures the seed status into a module-level so /api/diagnostics
# and the manual /api/admin/seed endpoint can both report on it.
_COMMAND_CENTRE_SEED_STATUS: dict = {"attempted": False, "ran": False,
                                       "skipped_reason": None,
                                       "summary": None, "error": None}


def _boot_auto_seed_command_centre():
    """Idempotent first-boot seed of Braze + Hightouch partner records.
    Runs only when the Braze partner is absent — so re-deploys skip,
    and any user-deleted contacts STAY deleted across boots.
    """
    global _COMMAND_CENTRE_SEED_STATUS
    _COMMAND_CENTRE_SEED_STATUS["attempted"] = True
    try:
        import partners_store
        if partners_store.get_partner("braze") is not None:
            _COMMAND_CENTRE_SEED_STATUS["skipped_reason"] = (
                "Braze partner already exists — seed considered already-run. "
                "Hit POST /api/admin/seed/command-centre to force a re-run."
            )
            log.info("Skipping Command Centre auto-seed (Braze partner exists).")
            return
        import seed_command_centre_partners
        summary = seed_command_centre_partners.seed()
        _COMMAND_CENTRE_SEED_STATUS["ran"] = True
        _COMMAND_CENTRE_SEED_STATUS["summary"] = {
            "partners": len(summary["partners_seeded"]),
            "contacts": len(summary["contacts_seeded"]),
            "skipped": len(summary["contacts_skipped"]),
        }
        log.info("Auto-seeded Command Centre: %d partners + %d contacts",
                  len(summary["partners_seeded"]),
                  len(summary["contacts_seeded"]))
    except Exception as e:
        _COMMAND_CENTRE_SEED_STATUS["error"] = str(e)
        log.warning("Command Centre auto-seed failed: %s", e)


@app.route("/api/admin/seed/command-centre", methods=["POST"])
def api_admin_seed_command_centre():
    """Force re-run the Command Centre seed. Idempotent — upserts by
    stable id, won't duplicate rows. Returns the full summary so the
    user can verify exactly what landed."""
    try:
        import seed_command_centre_partners
        summary = seed_command_centre_partners.seed()
        global _COMMAND_CENTRE_SEED_STATUS
        _COMMAND_CENTRE_SEED_STATUS = {
            "attempted": True,
            "ran": True,
            "skipped_reason": None,
            "summary": {
                "partners": len(summary["partners_seeded"]),
                "contacts": len(summary["contacts_seeded"]),
                "skipped": len(summary["contacts_skipped"]),
            },
            "error": None,
        }
        audit.log_event("command_centre_reseeded", actor=_actor(),
                        partners=len(summary["partners_seeded"]),
                        contacts=len(summary["contacts_seeded"]))
        return jsonify({
            "ok": True,
            "partners": [p["name"] for p in summary["partners_seeded"]],
            "contacts_created": len(summary["contacts_seeded"]),
            "contacts_skipped": summary["contacts_skipped"],
        })
    except Exception as e:
        log.exception("Manual Command Centre seed failed")
        return jsonify({"error": str(e)}), 500


# v1.0.0t: Dashboard endpoint ----------------------------------------------

@app.route("/api/dashboard", methods=["GET"])
def api_dashboard():
    """Manager dashboard: touch/call counts per MR owner + per partner
    over a configurable time window. Optionally scoped to a single owner.

    Query params:
      window — days to aggregate over (default 7; clamped 1..365)
      owner  — filter to a single mr_owner name (case-insensitive)
    """
    import dashboard
    try:
        window = max(1, min(365, int(request.args.get("window", "7"))))
    except ValueError:
        window = 7
    owner_filter = (request.args.get("owner") or "").strip() or None

    # Pipeline rows fetched best-effort; if Notion is unavailable we
    # still return partner-side stats so the dashboard isn't blank.
    pipeline_rows: list[dict] = []
    try:
        sync = NotionSync()
        pipeline_rows = sync.list_pipeline(limit=500)
    except (NotionSyncError, ValueError) as e:
        log.warning("Dashboard: pipeline fetch failed (continuing without lead stats): %s", e)
    try:
        payload = dashboard.build_dashboard(
            window_days=window,
            owner_filter=owner_filter,
            pipeline_rows=pipeline_rows,
        )
        return jsonify(payload)
    except Exception as e:
        log.exception("Dashboard build failed")
        return jsonify({"error": str(e)}), 500


# v1.0.0n: Forecasting endpoints ------------------------------------------

@app.route("/api/forecast", methods=["GET"])
def api_forecast():
    """Quarterly bookings forecast across every active lead, sliced by
    owner / partner-source / vertical / region. Caller can also pass
    ?horizon=4 to control how many quarters to project.

    The pipeline list is fetched fresh from Notion every time — this
    endpoint is cheap (one Notion query + pure-Python aggregation) and
    Ben hits it from the Forecast nav so we want it always-current.
    """
    import forecast
    try:
        horizon = max(1, min(8, int(request.args.get("horizon", "4"))))
    except ValueError:
        horizon = 4
    try:
        sync = NotionSync()
        # Pull a generous slab so we capture the long tail. The
        # forecast logic filters out disqualified/on-hold/closed-lost.
        rows = sync.list_pipeline(limit=500)
    except (NotionSyncError, ValueError) as e:
        log.warning("Forecast: pipeline fetch failed: %s", e)
        return jsonify({"error": str(e)}), 502
    try:
        payload = forecast.build_forecast(rows, horizon_quarters=horizon)
        return jsonify(payload)
    except Exception as e:
        log.exception("Forecast build failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/forecast/config", methods=["GET"])
def api_forecast_config_get():
    """Return the current forecast config (stage probabilities + target)."""
    import forecast_config_store
    return jsonify(forecast_config_store.load())


@app.route("/api/forecast/config", methods=["PATCH"])
def api_forecast_config_update():
    """Update stage probabilities and/or the quarterly target. Body:
        { "stage_probabilities": {"Discovery": 0.30, ...},
          "quarterly_target_gbp": 750000 }
    """
    import forecast_config_store
    body = request.get_json(silent=True) or {}
    updated = forecast_config_store.save(body)
    audit.log_event("forecast_config_updated", actor=_actor(),
                    keys=sorted(body.keys()))
    return jsonify(updated)


# Run the self-heal at import time so it executes whether we're
# launched via `python server.py` or via gunicorn (Railway). Guarded so
# tests + the CLI don't trigger Notion calls when creds are absent.
if os.environ.get("NOTION_API_KEY") and not os.environ.get("SKIP_NOTION_BOOT"):
    _boot_self_heal_backup_property()

# v1.0.0j: auto-seed on boot (cheap — local file writes only, no Notion
# calls). Gated by SKIP_COMMAND_CENTRE_SEED so tests can opt out.
if not os.environ.get("SKIP_COMMAND_CENTRE_SEED"):
    _boot_auto_seed_command_centre()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
