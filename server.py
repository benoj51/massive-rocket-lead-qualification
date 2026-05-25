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
import json
import logging
import os
from typing import Any

from flask import Flask, Response, jsonify, request
from flask_cors import CORS

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import accounts_graph
import activity
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
import engagement
import engagement_snapshots_store
import hubspot_sync
import account_news
import account_news_store
import account_watchlist_store
import expansion_targets_store
import filter_presets_store
import live_project_okrs_store
import live_projects_store
import lead_summary_store
import notifications_store
import packages
import todos_store
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

# v1.0.0bz: cap request body size. Without this, an authenticated
# abuser (or hijacked session) can DoS the Railway dyno or fill the
# persistent volume by POSTing multi-MB JSON. 4MB is generous for
# every legitimate flow (CSV import + Jeff conversations) without
# leaving the door open for resource exhaustion.
app.config["MAX_CONTENT_LENGTH"] = int(
    os.environ.get("MAX_CONTENT_LENGTH", str(4 * 1024 * 1024)))

# v1.0.0bz: pin CORS to the production origin(s) by default. The old
# `CORS(app)` allowed any origin to read responses — fine for local
# dev, sloppy for production. Set `CORS_ORIGINS` env var (comma-
# separated) to override; falling back to `*` for the local dev case
# only when explicitly enabled so production never silently goes wide.
_cors_origins_raw = os.environ.get("CORS_ORIGINS", "").strip()
if _cors_origins_raw:
    _cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]
    CORS(app, origins=_cors_origins)
elif os.environ.get("CORS_ALLOW_ANY") == "1":
    # Explicit opt-in for local dev only.
    CORS(app)
else:
    # Production default: same-origin only (Flask-CORS without a
    # configured origin list still adds permissive headers, so install
    # the extension with an empty allowlist — no cross-origin access).
    CORS(app, origins=[])

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
# include `Authorization: Bearer <token>`. The HTML entrypoint stays open
# so the UI can render the auth prompt.
# Leave APP_AUTH_TOKEN unset in dev to disable.
#
# v1.0.0bz: removed the `?token=<token>` query-string fallback. Query
# strings end up in: webserver access logs, browser history, the
# Referer header (so any outbound link from the app leaks the token
# to the third party), and shoulder-surfing screenshots. The header
# path is the only safe surface for a long-lived shared secret.
# AUTH_TOKEN_ALLOW_QUERY=1 keeps the old behaviour for any tooling
# that hasn't migrated yet — set it explicitly to opt back in.

AUTH_TOKEN = os.environ.get("APP_AUTH_TOKEN", "").strip()
AUTH_ALLOW_QUERY_TOKEN = os.environ.get("AUTH_TOKEN_ALLOW_QUERY") == "1"


def _request_token() -> str:
    auth_hdr = request.headers.get("Authorization", "")
    if auth_hdr.lower().startswith("bearer "):
        return auth_hdr[7:].strip()
    if AUTH_ALLOW_QUERY_TOKEN:
        return request.args.get("token", "").strip()
    return ""


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


def _compose_live_project_name(company: str | None,
                                 opportunity_type: str | None,
                                 *, fallback: str = "(unnamed)") -> str:
    """v1.0.0by: live project naming convention.

    Format: "<company> — <opportunity type>"
    e.g. "Shell North America — CRM Build"

    Why: the Live Projects list previously showed bare company names,
    so when the same anchor account had multiple workstreams over
    time ("Shell — CRM Build" finishes, then "Shell — Retention"
    starts) every row read identically. Appending the opportunity
    type gives each row a unique, scannable identity.

    Falls back gracefully:
    - No opp_type / "Unknown" → bare company name
    - No company → fallback (typically the lead_id)
    - Both missing → fallback
    """
    company = (company or "").strip()
    ot = (opportunity_type or "").strip()
    if ot and ot.lower() != "unknown":
        if company:
            return f"{company} — {ot}"
        return ot
    return company or fallback


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
        # v1.0.0bz: don't ship the traceback to the client — file paths
        # and stack frames are an information-disclosure gift for
        # follow-on attacks. The full trace stays in `log.exception` +
        # audit; the client just gets the short error message.
        log.exception("Qualification crash for %s", name)
        audit.log_event("qualify_crash", actor=_actor(), company=name,
                        reason=str(e)[:200])
        return jsonify({"error": str(e)}), 500


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


# v1.0.0as: account engagement timeline -----------------------------------
# Unified reverse-chronological feed of every touchpoint on an account:
# per-contact stakeholder notes, lead-level calls, and the last-touched
# timestamp on each contact. Powers the new Timeline view in the lead
# drawer's Account section.

@app.route("/api/lead/<lead_id>/engagement-timeline", methods=["GET"])
def api_lead_engagement_timeline(lead_id: str):
    """Return a unified timeline of engagement events for an account.

    Sources merged:
      - lead_contact_notes (per-contact stakeholder notes)
      - calls_store (lead-level call/meeting notes)
      - contacts_store.last_touched_at (one entry per contact)

    Query:
      limit (default 100, clamped 1..500)

    Returned shape (each item):
      {
        "ts":            "2026-05-23T..."  # iso8601
        "kind":          "note" | "call" | "touch"
        "title":         "<short label, e.g. 'Discovery #2' or 'Note'>"
        "actor":         "<author/MR owner if known>"
        "contact_id":    str | None
        "contact_name":  str | None
        "preview":       "<first 240 chars of content>"
        "raw_id":        original row id (so the UI can link back)
      }
    """
    try:
        limit = max(1, min(500, int(request.args.get("limit", "100"))))
    except ValueError:
        limit = 100

    contacts = contacts_store.list_contacts(lead_id)
    contact_by_id = {c["id"]: c for c in contacts}

    items: list[dict] = []

    # 1) Per-contact notes — pulled per contact (cheap, files are small).
    for c in contacts:
        try:
            notes = lead_contact_notes_store.list_notes(lead_id, c["id"])
        except Exception:
            notes = []
        for n in notes:
            content = (n.get("content") or "").strip()
            items.append({
                "ts":           n.get("created_at"),
                "kind":         "note",
                "title":        (n.get("type") or "note").title(),
                "actor":        n.get("author"),
                "contact_id":   c["id"],
                "contact_name": c.get("name"),
                "preview":      content[:240] + ("…" if len(content) > 240 else ""),
                "raw_id":       n.get("id"),
            })

    # 2) Lead-level calls. Map any `partner_source` to a hint, but the
    #    main attribution is the call author. partner_source links to
    #    a partner contact, not a lead contact, so it doesn't tie to
    #    contact_by_id here — left as None.
    try:
        calls = calls_store.list_calls(lead_id)
    except Exception:
        calls = []
    for k in calls:
        content = (k.get("content") or "").strip()
        # Some calls reference an attendee from the contacts roster.
        # Best-effort match by name so the timeline cluster groups
        # calls under the contact they were with.
        attendees = k.get("attendees") or []
        match_id = None
        match_name = None
        if attendees:
            first = (attendees[0] or "").strip().lower()
            for c in contacts:
                if (c.get("name") or "").strip().lower() == first:
                    match_id = c["id"]
                    match_name = c.get("name")
                    break
        items.append({
            "ts":           k.get("created_at"),
            "kind":         "call",
            "title":        k.get("title") or (k.get("type") or "call").title(),
            "actor":        (k.get("attendees") or [None])[0] if attendees else None,
            "contact_id":   match_id,
            "contact_name": match_name,
            "preview":      content[:240] + ("…" if len(content) > 240 else ""),
            "raw_id":       k.get("id"),
        })

    # 3) Last-touch timestamps. One entry per contact whose
    #    last_touched_at differs from its note timestamps (cheap
    #    de-dup: a touch fired from "add note" already shows up as
    #    a note; we only surface the touch if it's the only signal).
    #    Notes use microsecond precision, contacts use second precision —
    #    compare at second-level so the dedup actually catches the
    #    auto-touch fired by the note-add endpoint.
    def _to_second(ts: str) -> str:
        # "2026-05-23T19:45:00.123456Z" → "2026-05-23T19:45:00"
        return (ts or "").split(".")[0].rstrip("Z")
    note_ts_by_contact: dict[str | None, set[str]] = {}
    for n in items:
        if n["kind"] != "note":
            continue
        cid = n.get("contact_id")
        note_ts_by_contact.setdefault(cid, set()).add(_to_second(n["ts"]))
    for c in contacts:
        ts = c.get("last_touched_at")
        if not ts:
            continue
        # Skip when this contact already has a note at the same second
        # (the note-add endpoint auto-fires a touch — they're the same
        # event from the user's perspective).
        if _to_second(ts) in note_ts_by_contact.get(c["id"], set()):
            continue
        items.append({
            "ts":           ts,
            "kind":         "touch",
            "title":        "Touched",
            "actor":        None,
            "contact_id":   c["id"],
            "contact_name": c.get("name"),
            "preview":      "",
            "raw_id":       None,
        })

    # Sort newest first, drop entries with no timestamp (can't place them).
    items = [i for i in items if i.get("ts")]
    items.sort(key=lambda i: i["ts"], reverse=True)
    items = items[:limit]

    return jsonify({
        "items": items,
        "stats": {
            "total":   len(items),
            "notes":   sum(1 for i in items if i["kind"] == "note"),
            "calls":   sum(1 for i in items if i["kind"] == "call"),
            "touches": sum(1 for i in items if i["kind"] == "touch"),
            "contacts_with_engagement": len(
                {i["contact_id"] for i in items if i.get("contact_id")}
            ),
            "contacts_total": len(contacts),
        },
    })


# v1.0.0at: account engagement score --------------------------------------
# Pulls the contact roster + every note + every call for the lead, runs
# them through engagement.compute_engagement_score, returns the score
# + band + signals breakdown so the UI can render "why this number" on
# hover. Same shape as the engagement-timeline stats so the surfaces
# stay consistent.

def _compute_engagement_for_lead(lead_id: str, *,
                                    record_snapshot: bool = True,
                                    include_trend: bool = True) -> dict:
    """Internal helper: pull contacts + events for one lead and run
    the scorer. Returns the same shape as /engagement-score (with
    the lead_id embedded so the batch endpoint can route results).

    v1.0.0bc: also records today's snapshot, computes a 7-day delta
    (returned as `trend`), and fires an `engagement_dropped`
    notification when the band downgrades since the previous snapshot.
    Toggleable via flags for tests + paths that don't want side effects.
    """
    contacts = [contacts_store.annotate_touch_state(dict(c))
                for c in contacts_store.list_contacts(lead_id)]
    event_isos: list[str] = []
    for c in contacts:
        try:
            for n in lead_contact_notes_store.list_notes(lead_id, c["id"]):
                if n.get("created_at"):
                    event_isos.append(n["created_at"])
        except Exception:
            continue
    try:
        for k in calls_store.list_calls(lead_id):
            if k.get("created_at"):
                event_isos.append(k["created_at"])
    except Exception:
        pass
    result = engagement.compute_engagement_score(
        contacts=contacts, recent_event_isos=event_isos)
    result["lead_id"] = lead_id

    if record_snapshot:
        try:
            # Peek at the previous snapshot BEFORE recording today's so
            # the band-drop check compares against the right baseline.
            from datetime import datetime, timezone
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            prev = engagement_snapshots_store.previous_snapshot(
                lead_id, before_date=today)
            # Check if today's snapshot already exists — drives the
            # notification dedup below so we only fire ONCE on the day
            # of the drop, not on every score recomputation today.
            already_recorded_today = any(
                s.get("date") == today
                for s in engagement_snapshots_store.history(lead_id, limit=5)
            )
            engagement_snapshots_store.record(lead_id, result)
            # Fire notification on a band downgrade. We only notify when
            # the band actually got WORSE — score moves within a band
            # are noise. And only on the FIRST recording of today so the
            # bell doesn't ping every time the user opens the lead.
            if (not already_recorded_today and prev and
                    engagement_snapshots_store.band_downgraded(
                        prev.get("band"), result.get("band"))):
                try:
                    # Find the lead's owner (best-effort via Notion).
                    owner = None
                    try:
                        lead = NotionSync().get_page(lead_id) or {}
                        owner = (lead.get("owner") or "").strip() or None
                        company = lead.get("company") or lead_id
                    except Exception:
                        company = lead_id
                    if owner:
                        notifications_store.notify_assignment(
                            owner,
                            kind="engagement_dropped",
                            title=f"{company} dropped to {result.get('band')}",
                            body=(f"Engagement fell from {prev.get('score')} "
                                    f"({prev.get('band')}) to {result.get('score')} "
                                    f"({result.get('band')}) since "
                                    f"{prev.get('date')}."),
                            link={"kind": "lead", "lead_id": lead_id},
                            actor=None,
                        )
                except Exception as e:
                    log.warning("Engagement-drop notify failed: %s", e)
        except Exception as e:
            log.warning("Engagement snapshot for %s failed: %s", lead_id, e)

    if include_trend:
        try:
            result["trend"] = engagement_snapshots_store.delta(
                lead_id, days_ago=7)
        except Exception as e:
            log.warning("Engagement delta for %s failed: %s", lead_id, e)
            result["trend"] = None

    return result


# v1.0.0au: batch engagement-score endpoint --------------------------------
# The pipeline view needs 50+ scores at once. Per-lead round-trips
# would dominate the page load; this batches them in a single call.

@app.route("/api/engagement-scores", methods=["GET"])
def api_engagement_scores_batch():
    """Compute engagement scores for many leads at once.

    Query: lead_ids — comma-separated list of lead/page ids (max 200).

    Returns:
      { scores: { lead_id_1: {score, band}, lead_id_2: {...}, ... } }

    Only score + band are returned per lead (the full signal breakdown
    would balloon the response for a 50-row pipeline). UI calls the
    single-lead endpoint for the tooltip when the user opens a drawer.
    """
    raw = (request.args.get("lead_ids") or "").strip()
    if not raw:
        return jsonify({"scores": {}})
    ids = [x.strip() for x in raw.split(",") if x.strip()]
    if len(ids) > 200:
        ids = ids[:200]
    scores: dict[str, dict] = {}
    for lid in ids:
        try:
            r = _compute_engagement_for_lead(lid)
            # v1.0.0bc: include trend direction so Pipeline column +
            # Home chips can show ↑/↓/→ without a second fetch.
            trend = r.get("trend") or {}
            scores[lid] = {
                "score": r["score"], "band": r["band"],
                "trend_direction": trend.get("direction"),
                "trend_delta":     trend.get("delta"),
            }
        except Exception as e:
            # Log but don't fail the whole batch — one bad lead
            # shouldn't blank out the whole pipeline.
            log.warning("Batch engagement score failed for %s: %s", lid, e)
            scores[lid] = {"score": None, "band": None,
                            "error": str(e)[:120]}
    return jsonify({"scores": scores})


@app.route("/api/lead/<lead_id>/engagement-score", methods=["GET"])
def api_lead_engagement_score(lead_id: str):
    """Compute the engagement score for one account. Returns the full
    {score, band, signals} so the drawer tooltip can show the
    breakdown. Delegates to the shared helper used by the batch
    endpoint above — single source of truth for the score math."""
    return jsonify(_compute_engagement_for_lead(lead_id))


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

    # v1.0.0bb: auto-merge tech_stack mentions into the lead's Notion
    # `Tech Stack` field. Append-only, case-insensitive dedup. Pulls the
    # current value, compares each AI mention, PATCHes only when there's
    # something new to add. Best-effort — Notion outage doesn't block
    # the call save.
    tech_stack_appended: list[str] = []
    if extracted and isinstance(extracted.get("tech_stack_mentioned"), list):
        new_tools = [t for t in extracted["tech_stack_mentioned"]
                     if isinstance(t, str) and t.strip()]
        if new_tools:
            try:
                sync = NotionSync()
                current = sync.get_page(lead_id) or {}
                existing_raw = (current.get("tech_stack") or "").strip()
                # Split on common separators; lowercase for compare.
                existing_set = {
                    s.strip().lower()
                    for chunk in existing_raw.replace("\n", ",").split(",")
                    for s in [chunk] if s.strip()
                }
                to_add = [t.strip() for t in new_tools
                          if t.strip().lower() not in existing_set]
                if to_add:
                    merged = (existing_raw + ", " if existing_raw else "") + ", ".join(to_add)
                    try:
                        sync.update_page(lead_id, {"tech_stack": merged})
                        tech_stack_appended = to_add
                        audit.log_event("lead_tech_stack_auto_appended",
                                        actor=_actor(), lead_id=lead_id,
                                        added=to_add,
                                        source_call_id=record["id"])
                    except Exception as e:
                        log.warning("Tech stack PATCH failed: %s", e)
            except Exception as e:
                log.warning("Tech stack auto-merge failed (skipped): %s", e)

    # v1.0.0bb: auto-link competitive agencies mentioned in the call.
    # Each agency lands as type=competitor with source=call_extracted.
    # Dedup case-insensitively against existing entries — don't add
    # "WPP" again if there's already a "wpp" row of any type. AE can
    # re-categorise (competitor → incumbent) later via the agencies UI.
    agencies_auto_added: list[dict] = []
    if extracted and isinstance(extracted.get("competitive_agencies"), list):
        for ag in extracted["competitive_agencies"]:
            try:
                name = (ag.get("name") or "").strip()
                if not name:
                    continue
                if lead_agencies_store.get_by_name(lead_id, name):
                    continue  # already tracked
                context = ag.get("context") or ""
                ag_type = lead_agencies_store.TYPE_COMPETITOR
                if context == "previously evaluated":
                    ag_type = lead_agencies_store.TYPE_PREVIOUS
                saved = lead_agencies_store.save_agency(lead_id, {
                    "name":           name,
                    "type":           ag_type,
                    "source":         "call_extracted",
                    "source_call_id": record["id"],
                    "notes":          (f"Mentioned: {context}" if context
                                          else "Mentioned in call"),
                })
                agencies_auto_added.append(saved)
                audit.log_event("lead_agency_auto_added",
                                actor=_actor(), lead_id=lead_id,
                                agency_id=saved["id"], name=name,
                                source_call_id=record["id"])
            except Exception as e:
                log.warning("Auto-add agency %r failed: %s",
                              ag.get("name"), e)

    # v0.10.0p: auto-refresh the lead summary so the AE doesn't have to
    # re-read every previous note. Inline (synchronous) — adds ~2s latency
    # to the save but means the summary tile reflects this call by the
    # time the UI re-renders. Safe to fail: any error here is logged but
    # doesn't break the call save.
    # v1.0.0bh: was gated on `extracted is not None`. That gate caused
    # partner-sourced notes (and any other note where the extraction
    # call timed out / hit a transient API error / returned malformed
    # JSON) to silently SKIP the summary refresh. The user's complaint:
    # "Added notes which were given by a partner on Shell but the notes
    # were not synthesised as they should be." Synthesis pulls from the
    # FULL call history (not just this one call's extraction), so it
    # has no dependency on this single extract succeeding.
    fresh_summary = None
    summary_refresh_error: str | None = None
    if ai_summary.is_configured():
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
            else:
                # synth came back None — AI call probably failed.
                # Surface it so the UI can toast something honest.
                summary_refresh_error = (
                    "AI synthesis returned no result — click Refresh on "
                    "the lead summary to retry.")
        except Exception as e:
            log.warning("Auto-summary refresh failed for %s: %s", lead_id, e)
            summary_refresh_error = f"AI summary refresh failed: {str(e)[:200]}"

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
        # v1.0.0bb: what got auto-added from the call. UI uses these for
        # confirmation toasts (e.g. "Added WPP + Razorfish to agencies").
        "agencies_auto_added":  agencies_auto_added,
        "tech_stack_appended":  tech_stack_appended,
        # v1.0.0bh: when the summary refresh failed (transient API
        # error, malformed JSON, etc), surface it so the UI can toast
        # honestly instead of silently looking like nothing happened.
        "summary_refresh_error": summary_refresh_error,
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
    # v1.0.0al: capture the old owner so we can detect a change after
    # the Notion write lands. Done BEFORE update_page so we compare
    # like-for-like.
    old_owner_for_notify = None
    if "owner" in body:
        try:
            sync_peek = NotionSync()
            prev = sync_peek.get_page(page_id) or {}
            old_owner_for_notify = (prev.get("owner") or "").strip() or None
        except Exception as e:
            log.warning("notify_assignment (lead) owner-peek failed: %s", e)
    try:
        sync = NotionSync()
        result = sync.update_page(page_id, body)
        # v1.0.0bp: surface dropped properties in the audit trail too —
        # if a Save silently lost a field, we want a permanent record.
        audit_fields = {"fields": sorted([k for k in body.keys() if k != "id"])}
        if result.get("dropped_props"):
            audit_fields["dropped_props"] = result["dropped_props"]
        audit.log_event("lead_updated", actor=_actor(), page_id=page_id,
                        **audit_fields)
        # v1.0.0al: fire an "assigned to you" notification if owner
        # changed. Guarded — never blocks the save on a notify error.
        try:
            new_lead = result.get("lead") or {}
            new_owner = (new_lead.get("owner") or "").strip()
            actor = _actor()
            if new_owner and new_owner != (old_owner_for_notify or "") and new_owner != actor:
                company = new_lead.get("company") or page_id
                body_lines = []
                if old_owner_for_notify:
                    body_lines.append(f"Reassigned from {old_owner_for_notify}")
                if actor:
                    body_lines.append(f"by {actor}")
                notifications_store.notify_assignment(
                    new_owner,
                    kind="assigned_lead",
                    title=f"You were assigned {company}",
                    body=" ".join(body_lines),
                    link={"kind": "lead", "lead_id": page_id},
                    actor=actor or None,
                )
        except Exception as e:
            log.warning("notify_assignment (lead) fire failed: %s", e)

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


# v1.0.0bz: CSV-injection guard. Excel + Google Sheets evaluate cells
# starting with =, +, -, @, tab, or CR as formulas. A lead named
# `=cmd|'/c calc'!A1` would execute when an analyst opens the export.
# Prepending a single quote neutralises this without altering the
# visible value (Excel hides the leading quote when rendering).
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value) -> str:
    s = "" if value is None else str(value)
    if s and s[0] in _CSV_FORMULA_PREFIXES:
        return "'" + s
    return s


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
        writer.writerow({k: _csv_safe(r.get(k, "")) for k in cols})
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


# v1.0.0ai: dry-run preview — render the SOW against current state
# WITHOUT saving a version. Lets the AE iterate (fix TBC values,
# tweak scope, edit pricing) before committing a version, and see
# brief-compliance warnings live.
@app.route("/api/sow/<lead_id>/preview", methods=["GET", "POST"])
def api_sow_preview(lead_id: str):
    """Render a SOW from current state without persisting a version.
    Accepts the same body shape as /api/sow/<lead_id> POST so the AE
    can pass MSA date / start date / currency overrides."""
    body = request.get_json(silent=True) or {}
    try:
        snapshot = sow.build_snapshot(
            lead_id,
            months=int(body.get("months", 12)),
            msa_date=body.get("msa_date") or None,
            start_date=body.get("start_date") or None,
            currency=body.get("currency") or None,
            company_legal_name=body.get("company_legal_name") or None,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    accept = (request.headers.get("Accept") or "").lower()
    if "application/json" in accept:
        return jsonify({"snapshot": snapshot,
                         "compliance": snapshot.get("compliance")})
    # Default: render the HTML so the preview modal can show it directly.
    # "Preview" tag in the toolbar so the AE knows it's not a saved version.
    html = sow.render_html(snapshot, version=0)
    return Response(html, mimetype="text/html; charset=utf-8")


@app.route("/api/sow/<lead_id>/compliance", methods=["GET"])
def api_sow_compliance(lead_id: str):
    """JSON-only compliance check for the current state. Same data as
    `/preview` but lighter — used by the Project Build view to surface
    warnings inline without rendering the full HTML."""
    try:
        snapshot = sow.build_snapshot(lead_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(snapshot.get("compliance", {}))


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
# v1.0.0bq: list is now writable. /api/owners stays read-only +
# active-only (it's used by every dropdown — no admin context).
# /api/settings/users below is the admin surface — exposes all
# owners (active + inactive) + CRUD.
@app.route("/api/owners", methods=["GET"])
def api_owners():
    """Return the list of MR owners (lead owner + partner-contact
    `mr_owner`). Includes role + region + email for richer dropdowns."""
    import mr_owners
    return jsonify({"owners": mr_owners.list_owners(active_only=True)})


# v1.0.0bq: settings → users CRUD. The Settings view in the UI
# reads + mutates this endpoint. We deliberately surface inactive
# owners too so an admin can re-activate someone who left and
# came back, without losing the historical lead.owner = "Old Name"
# resolutions that depend on the row sticking around.
@app.route("/api/settings/users", methods=["GET"])
def api_settings_users_list():
    import mr_owners_store
    owners = mr_owners_store.list_owners(active_only=False)
    return jsonify({"users": owners, "count": len(owners)})


@app.route("/api/settings/users", methods=["POST"])
def api_settings_users_create():
    import mr_owners_store
    body = request.get_json(silent=True) or {}
    try:
        owner = mr_owners_store.create_owner(body)
    except mr_owners_store.MrOwnersStoreError as e:
        return jsonify({"error": str(e)}), 400
    audit.log_event("settings_user_created", actor=_actor(),
                    user_id=owner["id"], name=owner["name"])
    return jsonify({"user": owner}), 201


@app.route("/api/settings/users/<user_id>", methods=["PATCH"])
def api_settings_users_update(user_id: str):
    import mr_owners_store
    body = request.get_json(silent=True) or {}
    try:
        owner = mr_owners_store.update_owner(user_id, **body)
    except mr_owners_store.MrOwnersStoreError as e:
        return jsonify({"error": str(e)}), 400
    if owner is None:
        return jsonify({"error": "not_found"}), 404
    audit.log_event("settings_user_updated", actor=_actor(),
                    user_id=user_id, fields=sorted(body.keys()))
    return jsonify({"user": owner})


@app.route("/api/settings/users/<user_id>", methods=["DELETE"])
def api_settings_users_delete(user_id: str):
    """Hard delete. UI offers Deactivate as the primary action
    because historical references (lead.owner = "Old Name") need
    the row to keep resolving. This endpoint exists for the
    "added by mistake, never assigned to anything" case."""
    import mr_owners_store
    ok = mr_owners_store.delete_owner(user_id)
    if not ok:
        return jsonify({"error": "not_found"}), 404
    audit.log_event("settings_user_deleted", actor=_actor(),
                    user_id=user_id)
    return jsonify({"deleted": True})


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


# v1.0.0cb: explicit allowlist on partner / partner-contact PATCH bodies.
# Previously `{**existing, **body}` accepted arbitrary keys, so a client
# could submit (e.g.) `created_at`, `partner_id`, `id` and have them
# silently merge into the stored record. Only _normalise was the line of
# defense, and not every field passes through it. The allowlist makes
# trust-boundary intent explicit: server says exactly what's editable.
_PARTNER_PATCH_FIELDS = frozenset({
    "name", "type", "tier", "regions", "industries", "website",
    "owner", "status", "notes", "logo_url",
})
_PARTNER_CONTACT_PATCH_FIELDS = frozenset({
    "name", "title", "email", "linkedin_url", "phone",
    "territories", "territory", "regions", "region",
    "country", "industries", "mr_owner", "reports_to_id",
    "status", "partner_sentiment", "tier", "seniority",
    "tags", "cadence_days", "last_touched_at",
})


def _filter_body(body: dict, allowed: frozenset) -> dict:
    return {k: v for k, v in (body or {}).items() if k in allowed}


@app.route("/api/partners/<partner_id>", methods=["PATCH"])
def api_partners_update(partner_id: str):
    body = _filter_body(request.get_json(silent=True) or {},
                         _PARTNER_PATCH_FIELDS)
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
    # v1.0.0cb: explicit allowlist — see _filter_body above.
    body = _filter_body(request.get_json(silent=True) or {},
                         _PARTNER_CONTACT_PATCH_FIELDS)
    merged = {**existing, **body, "id": contact_id, "partner_id": existing["partner_id"]}
    try:
        saved = partner_contacts_store.save_contact(partner_id, merged)
    except partner_contacts_store.PartnerContactsStoreError as e:
        return jsonify({"error": str(e)}), 400
    # v1.0.0al: notify the new owner if mr_owner changed. Wrapped in
    # try/except so a notifications glitch never blocks the save —
    # notifications are a convenience layer, not a correctness one.
    try:
        old_owner = (existing.get("mr_owner") or "").strip()
        new_owner = (saved.get("mr_owner") or "").strip()
        actor = _actor()
        if new_owner and new_owner != old_owner and new_owner != actor:
            partner = partners_store.get_partner(partner_id) or {}
            partner_name = partner.get("name") or partner_id
            contact_name = saved.get("name") or "(unnamed)"
            body_lines = []
            if old_owner:
                body_lines.append(f"Reassigned from {old_owner}")
            if actor:
                body_lines.append(f"by {actor}")
            notifications_store.notify_assignment(
                new_owner,
                kind="assigned_partner_contact",
                title=f"You were assigned {contact_name} ({partner_name})",
                body=" ".join(body_lines),
                link={"kind": "partner_contact",
                       "partner_id": partner_id,
                       "contact_id": contact_id},
                actor=actor or None,
            )
    except Exception as e:
        log.warning("notify_assignment (partner contact) failed: %s", e)
    return jsonify({"contact": saved})


# v1.0.0ax: bulk update endpoint for partner contacts.
# After v1.0.0ac added tier/sentiment/seniority, existing contacts often
# need batch field updates. One-at-a-time edits are painful; this lets
# the UI select N rows + apply the same field changes in a single call.
#
# Allow-listed field set is narrow on purpose: free-text fields (name,
# email, title) make no sense to bulk-set, and we don't want a misclick
# to wipe 50 names. Only the dimensions you'd realistically want to
# set across a batch are accepted.

_BULK_PARTNER_CONTACT_FIELDS = frozenset({
    "mr_owner",          # reassign owner
    "tier",              # batch-tier
    "partner_sentiment", # bulk sentiment update
    "seniority",         # rare but cheap
    "status",            # mark a batch as dormant / left after re-org
    "cadence_days",      # tighten/loosen touch cadence for a segment
})


@app.route("/api/partners/<partner_id>/contacts/bulk-update", methods=["POST"])
def api_partner_contacts_bulk_update(partner_id: str):
    """Apply the same field updates to many contacts at once.

    Body:
      {
        "contact_ids": ["id1", "id2", ...],   # required, max 200
        "updates":     {"mr_owner": "Ben"},   # required, allow-listed fields only
      }

    Returns:
      {
        "updated":  int,             # count successfully saved
        "errors":   [{contact_id, error}, ...],
        "notified": int,             # how many assigned_partner_contact notifications fired
      }

    Honours the same notification contract as the single-PATCH endpoint —
    a bulk reassign fires one notification per newly-owned contact,
    which is what you want when the new owner opens the bell and sees
    each one they've inherited.
    """
    body = request.get_json(silent=True) or {}
    contact_ids = body.get("contact_ids") or []
    updates = body.get("updates") or {}
    if not isinstance(contact_ids, list) or not contact_ids:
        return jsonify({"error": "contact_ids (non-empty list) required"}), 400
    if len(contact_ids) > 200:
        return jsonify({"error": "max 200 contacts per call"}), 400
    if not isinstance(updates, dict) or not updates:
        return jsonify({"error": "updates (non-empty object) required"}), 400
    bad = set(updates.keys()) - _BULK_PARTNER_CONTACT_FIELDS
    if bad:
        return jsonify({
            "error": f"fields not allowed in bulk update: {sorted(bad)}. "
                     f"Allowed: {sorted(_BULK_PARTNER_CONTACT_FIELDS)}",
        }), 400

    actor = _actor()
    partner = partners_store.get_partner(partner_id) or {}
    partner_name = partner.get("name") or partner_id

    updated = 0
    errors: list[dict] = []
    notified = 0
    new_owner = (updates.get("mr_owner") or "").strip() or None

    for cid in contact_ids:
        existing = partner_contacts_store.get_contact(partner_id, cid)
        if not existing:
            errors.append({"contact_id": cid, "error": "not_found"})
            continue
        merged = {**existing, **updates, "id": cid,
                  "partner_id": existing["partner_id"]}
        try:
            saved = partner_contacts_store.save_contact(partner_id, merged)
        except partner_contacts_store.PartnerContactsStoreError as e:
            errors.append({"contact_id": cid, "error": str(e)[:200]})
            continue
        updated += 1
        # Fire a per-contact reassign notification when mr_owner actually
        # changed for THIS contact. Skip if the contact already had this
        # owner (idempotent bulk-set is common — don't spam).
        if new_owner and new_owner != actor:
            old_owner = (existing.get("mr_owner") or "").strip()
            if old_owner != new_owner:
                try:
                    notifications_store.notify_assignment(
                        new_owner,
                        kind="assigned_partner_contact",
                        title=f"You were assigned {saved.get('name') or '(unnamed)'} ({partner_name})",
                        body=(f"Bulk-reassigned from {old_owner}" if old_owner
                                else "Bulk-assigned") + (f" by {actor}" if actor else ""),
                        link={"kind": "partner_contact",
                                "partner_id": partner_id,
                                "contact_id": cid},
                        actor=actor or None,
                    )
                    notified += 1
                except Exception as e:
                    log.warning("Bulk notify_assignment failed for %s: %s",
                                  cid, e)

    audit.log_event("partner_contacts_bulk_updated",
                    actor=actor, partner_id=partner_id,
                    n_updated=updated, n_errors=len(errors),
                    fields=sorted(updates.keys()))
    return jsonify({
        "updated":  updated,
        "errors":   errors,
        "notified": notified,
    })


# v1.0.0bv: CSV import for partner contacts.
# After v1.0.0bt added inline editing, the next-most-painful workflow
# was adding contacts in bulk — Ben kept hand-typing rosters of 6+
# new EMEA / APAC people. CSV import closes that gap.
#
# Design notes:
# - Single endpoint with dry_run=true so the UI can preview before
#   writing. Same parser, same matching, same merge logic both passes.
# - Header names are normalised (lowercased, underscores) with
#   common synonyms (`linkedin`, `linkedin_url` → `linkedin_url`).
# - Multi-tag columns (regions, territories, industries, tags) accept
#   comma, pipe, or semicolon as the in-cell separator — Excel
#   exports vary.
# - Duplicate handling is UPDATE: match an existing contact by name
#   (case-insensitive) OR email and PATCH only the fields the CSV
#   carries values for. Empty CSV cells don't clobber existing data —
#   so "update titles in bulk" works without losing other state.

_CSV_HEADER_SYNONYMS = {
    "name":            "name",
    "full_name":       "name",
    "contact":         "name",
    "email":           "email",
    "email_address":   "email",
    "title":           "title",
    "role":            "title",
    "job_title":       "title",
    "country":         "country",
    "city":            "_city",  # stashed in tags — no first-class field
    "region":          "regions",
    "regions":         "regions",
    "territory":       "territories",
    "territories":     "territories",
    "industry":        "industries",
    "industries":      "industries",
    "tier":            "tier",
    "sentiment":       "partner_sentiment",
    "partner_sentiment": "partner_sentiment",
    "seniority":       "seniority",
    "mr_owner":        "mr_owner",
    "owner":           "mr_owner",
    "linkedin":        "linkedin_url",
    "linkedin_url":    "linkedin_url",
    "linkedinurl":     "linkedin_url",
    "phone":           "phone",
    "status":          "status",
    "cadence_days":    "cadence_days",
    "cadence":         "cadence_days",
    "tags":            "tags",
    "notes":           "_notes",  # tag-only for now (no per-row note creation)
}

_MULTI_TAG_FIELDS = {"regions", "territories", "industries", "tags"}


def _csv_normalise_header(h: str) -> str:
    """`MR Owner` → `mr_owner` → resolved via the synonym table."""
    key = (h or "").strip().lower().replace(" ", "_").replace("-", "_")
    return _CSV_HEADER_SYNONYMS.get(key, "")


def _csv_split_multi(value: str) -> list[str]:
    """Multi-tag cells: split on comma / pipe / semicolon."""
    import re as _re
    if not value:
        return []
    parts = _re.split(r"[,|;]\s*", str(value))
    return [p.strip() for p in parts if p.strip()]


@app.route("/api/partners/<partner_id>/contacts/import-csv", methods=["POST"])
def api_partner_contacts_import_csv(partner_id: str):
    """Parse a CSV string + preview (dry_run=true) or commit the import.

    Body:
      { "csv": "<string>", "dry_run": true|false }

    Returns:
      {
        "rows": [
          {"row": 2, "action": "add"|"update"|"error",
           "contact": {...}, "matched_id": "..."|None, "reason": "..."|None},
          ...
        ],
        "summary": {"total": N, "would_add": N, "would_update": N,
                     "errored": N, "committed": bool},
      }
    """
    import csv as _csv
    import io as _io

    body = request.get_json(silent=True) or {}
    csv_text = body.get("csv") or ""
    dry_run = bool(body.get("dry_run", True))
    if not csv_text.strip():
        return jsonify({"error": "csv body required"}), 400

    # Verify the partner exists; we still parse on a missing partner
    # so the user gets the validation feedback either way.
    partner = partners_store.get_partner(partner_id)
    if not partner:
        return jsonify({"error": "partner_not_found"}), 404

    # Parse — be tolerant of BOMs (Excel exports) + trailing whitespace.
    try:
        reader = _csv.DictReader(_io.StringIO(csv_text.lstrip("﻿")))
        raw_rows = list(reader)
    except Exception as e:
        return jsonify({"error": f"csv parse failed: {e}"}), 400
    headers = reader.fieldnames or []
    if not headers:
        return jsonify({"error": "no headers detected"}), 400

    # Map raw → normalised header. Unknown headers are kept in a
    # warnings list so the UI can flag typos.
    header_map: dict[str, str] = {}
    unknown_headers: list[str] = []
    for h in headers:
        norm = _csv_normalise_header(h)
        if norm:
            header_map[h] = norm
        else:
            unknown_headers.append(h)

    # Snapshot existing roster ONCE so name/email matching is O(N).
    existing = partner_contacts_store.list_contacts(partner_id)
    by_name = {(c.get("name") or "").strip().lower(): c
                for c in existing if c.get("name")}
    by_email = {(c.get("email") or "").strip().lower(): c
                 for c in existing if c.get("email")}

    rows_out: list[dict] = []
    counts = {"add": 0, "update": 0, "error": 0}

    for idx, raw in enumerate(raw_rows, start=2):  # row 1 = header
        # Build the canonical payload from this row.
        payload: dict = {}
        city_extra: str | None = None
        for raw_h, norm in header_map.items():
            value = (raw.get(raw_h) or "").strip()
            if not value:
                continue  # empty cell — don't clobber existing on update
            if norm == "_city":
                city_extra = value
                continue
            if norm == "_notes":
                # No per-row note creation in v1 — log + skip cleanly.
                continue
            if norm in _MULTI_TAG_FIELDS:
                payload[norm] = _csv_split_multi(value)
            else:
                payload[norm] = value
        # City lives in tags so the info survives the schema gap.
        if city_extra:
            payload.setdefault("tags", []).append(city_extra)

        name = (payload.get("name") or "").strip()
        email = (payload.get("email") or "").strip().lower()
        if not name and not email:
            rows_out.append({
                "row":     idx,
                "action":  "error",
                "reason":  "row needs at least a name or email",
                "contact": payload,
            })
            counts["error"] += 1
            continue

        # Match against existing roster.
        matched = None
        if name:
            matched = by_name.get(name.lower())
        if not matched and email:
            matched = by_email.get(email)

        if matched:
            # Build the merged payload: existing fields + CSV values
            # (CSV wins where non-empty, which is guaranteed since we
            # skip empty cells above).
            merged = {**matched, **payload, "id": matched["id"],
                       "partner_id": matched["partner_id"]}
            try:
                if dry_run:
                    contact = partner_contacts_store._normalise(partner_id, merged)
                else:
                    contact = partner_contacts_store.save_contact(partner_id, merged)
            except partner_contacts_store.PartnerContactsStoreError as e:
                rows_out.append({
                    "row":     idx,
                    "action":  "error",
                    "reason":  str(e),
                    "contact": payload,
                })
                counts["error"] += 1
                continue
            rows_out.append({
                "row":        idx,
                "action":     "update",
                "matched_id": matched["id"],
                "contact":    contact,
            })
            counts["update"] += 1
        else:
            try:
                if dry_run:
                    contact = partner_contacts_store._normalise(partner_id, payload)
                else:
                    contact = partner_contacts_store.save_contact(partner_id, payload)
                    # Index immediately so a CSV that lists "Jane" twice
                    # doesn't add two rows.
                    nm = (contact.get("name") or "").strip().lower()
                    em = (contact.get("email") or "").strip().lower()
                    if nm: by_name[nm] = contact
                    if em: by_email[em] = contact
            except partner_contacts_store.PartnerContactsStoreError as e:
                rows_out.append({
                    "row":     idx,
                    "action":  "error",
                    "reason":  str(e),
                    "contact": payload,
                })
                counts["error"] += 1
                continue
            rows_out.append({
                "row":     idx,
                "action":  "add",
                "contact": contact,
            })
            counts["add"] += 1

    if not dry_run:
        audit.log_event("partner_contacts_csv_import", actor=_actor(),
                         partner_id=partner_id,
                         added=counts["add"], updated=counts["update"],
                         errored=counts["error"])

    return jsonify({
        "rows":    rows_out,
        "summary": {
            "total":           len(raw_rows),
            "would_add":       counts["add"],
            "would_update":    counts["update"],
            "errored":         counts["error"],
            "committed":       (not dry_run),
            "unknown_headers": unknown_headers,
        },
    })


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
            # v1.0.0aq: keep the lazy retry list in sync with the boot
            # self-heal so the recovery path creates the same set.
            "Partner Source":            {"select": {}},
            "Sourced For":               {"multi_select": {}},
            # v1.0.0ca: Close Reason — captured when sales_stage flips
            # to "Closed Lost" or status flips to "Rejected".
            "Close Reason":              {"rich_text": {}},
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
      - "Partner Source" (v1.0.0z — note-source attribution)
      - "Sourced For" (v1.0.0z — multi-partner attribution)

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
            # v1.0.0aq: Ben hit "Sourced For is not a property" on save
            # because his DB pre-dated v1.0.0z. Added here so any DB
            # without these columns gets them on next boot.
            "Partner Source":            {"select": {}},
            "Sourced For":               {"multi_select": {}},
            # v1.0.0ca: Close Reason — captured when sales_stage flips
            # to "Closed Lost" or status flips to "Rejected".
            "Close Reason":              {"rich_text": {}},
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


# v1.0.0ah: Personal Home endpoint -----------------------------------------
# Powers the new Home view — the role-aware landing page each user
# sees first. Wraps the dashboard aggregator with owner-scoped KPIs +
# a few extras tuned to who's looking.

@app.route("/api/home", methods=["GET"])
def api_home():
    """Personal-book snapshot for the named MR owner.

    Query: owner (required) — the MR owner's name. Returns:
      - owner: { name, role, region, email }
      - kpis: { touches_30d, partner_contacts_owned,
                partner_contacts_overdue, leads_active, leads_total }
      - overdue_contacts: top 5 partner contacts owned + overdue
      - active_leads: top 5 leads owned (by recency)
      - team_snapshot: small team-aggregated block for context
      - role_extras: role-specific extras (e.g. marketing gets
        new_leads_week)
    """
    import dashboard
    import mr_owners

    owner_name = (request.args.get("owner") or "").strip()
    if not owner_name:
        return jsonify({"error": "owner query param required"}), 400
    owner = mr_owners.get_owner(owner_name)
    if owner is None:
        return jsonify({"error": f"unknown owner: {owner_name}"}), 404

    # Pull pipeline once — used for both the owner-scoped view + the
    # team snapshot. Best-effort if Notion is down.
    pipeline_rows: list[dict] = []
    try:
        pipeline_rows = NotionSync().list_pipeline(limit=500)
    except Exception as e:
        log.warning("Home: pipeline fetch failed (continuing): %s", e)

    # Owner-scoped dashboard payload (30-day window — matches Dashboard
    # default).
    scoped = dashboard.build_dashboard(
        window_days=30,
        owner_filter=owner_name,
        pipeline_rows=pipeline_rows,
    )
    owner_bucket = next(
        (b for b in scoped["by_owner"] if b["name"] == owner_name),
        None,
    )

    # Overdue partner contacts owned by this user — sorted by most
    # days overdue first so the top 5 are the worst offenders.
    overdue_owned = [
        partner_contacts_store.annotate_touch_state(dict(c))
        for c in partner_contacts_store.list_all_contacts()
        if (c.get("mr_owner") or "").lower() == owner_name.lower()
        and (c.get("status") or "active") == "active"
    ]
    overdue_owned = [c for c in overdue_owned if c.get("overdue")]
    overdue_owned.sort(key=lambda c: c.get("days_until_due") or 0)
    # Enrich with partner name for the click-through label.
    partner_name_by_id = {p["id"]: p["name"] for p in partners_store.list_partners()}
    overdue_top = [{
        "id":          c.get("id"),
        "name":        c.get("name"),
        "title":       c.get("title"),
        "partner_id":  c.get("partner_id"),
        "partner_name": partner_name_by_id.get(c.get("partner_id"), c.get("partner_id")),
        "days_overdue": abs(c.get("days_until_due") or 0),
        "cadence_days": c.get("cadence_days"),
        "last_touched_at": c.get("last_touched_at"),
    } for c in overdue_owned[:5]]

    # Active leads owned by this user — last_edited descending so the
    # freshest activity surfaces first.
    leads_owned = [
        r for r in pipeline_rows
        if (r.get("owner") or "").lower() == owner_name.lower()
        and (r.get("status") or "") not in {"Disqualified", "On Hold", "Closed Lost", "Nurture", "Rejected"}
    ]
    leads_owned.sort(key=lambda r: r.get("last_edited") or "", reverse=True)
    active_leads_top = [{
        "id":            r.get("id"),
        "company":       r.get("company"),
        "status":        r.get("status"),
        "sales_stage":   r.get("sales_stage"),
        "icp_normalised": r.get("icp_normalised"),
        "next_steps":    (r.get("next_steps") or "").split("\n")[0][:120],
        "last_edited":   r.get("last_edited"),
    } for r in leads_owned[:5]]

    # v1.0.0av: at-risk leads — the AE's owned active leads with cold
    # or weak engagement (<50). Sorted ascending by score so the
    # coldest float to the top. Limited to 5 to keep the Home card
    # focused on "what should I rescue today", not an audit dump.
    # Capped scan at the first 40 active leads (recency-sorted above)
    # so the I/O fan-out stays bounded — heavy books still see their
    # most-recent at-risk accounts without scanning ancient ones.
    at_risk_leads: list[dict] = []
    try:
        for r in leads_owned[:40]:
            lid = r.get("id")
            if not lid:
                continue
            try:
                eng = _compute_engagement_for_lead(lid)
            except Exception as e:
                log.warning("Home at_risk score for %s failed: %s", lid, e)
                continue
            score = eng.get("score", 0)
            band = eng.get("band", "cold")
            if score >= 50:
                continue
            sig = eng.get("signals") or {}
            at_risk_leads.append({
                "id":               lid,
                "company":          r.get("company"),
                "status":           r.get("status"),
                "engagement_score": score,
                "engagement_band":  band,
                "icp_normalised":   r.get("icp_normalised"),
                "days_since_touch": sig.get("days_since_touch"),
                "overdue_count":    sig.get("overdue_count", 0),
            })
        at_risk_leads.sort(key=lambda x: x["engagement_score"])
        at_risk_leads = at_risk_leads[:5]
    except Exception as e:
        log.warning("Home at_risk_leads computation failed: %s", e)

    # Team snapshot — un-scoped totals across the same window so a
    # user can compare their book vs the team.
    team = dashboard.build_dashboard(
        window_days=30,
        owner_filter=None,
        pipeline_rows=pipeline_rows,
    )
    team_snapshot = {
        "touches":            team["totals"]["touches"],
        "active_contacts":    team["coverage"]["active_contacts"],
        "overdue":            team["coverage"]["overdue"],
        "compliance_pct":     team["coverage"]["compliance_pct"],
    }

    # Role-aware extras — small block tailored to who's looking. Roles
    # bucketed by keyword match against the owner.role string so a
    # rename ("AE → AM") doesn't break this.
    role_lower = (owner.get("role") or "").lower()
    role_extras: dict = {}
    if "ceo" in role_lower or "director of growth" in role_lower:
        # Exec lens: pipeline coverage, team activity totals.
        role_extras["exec"] = {
            "team_touches_30d": team["totals"]["touches"],
            "team_active_leads_owned": sum(
                b.get("leads_active", 0) for b in team["by_owner"]
            ),
            "team_overdue_contacts": team["coverage"]["overdue"],
        }
    elif "marketing" in role_lower:
        # Marketing lens: how many new leads this window, qualified
        # rate. new_leads here uses the same proxy as the team
        # dashboard.
        role_extras["marketing"] = {
            "new_leads_30d": team["totals"]["new_leads"],
            "qualified_count": sum(
                1 for r in pipeline_rows
                if (r.get("status") or "") == "Qualified"
            ),
            "total_in_pipeline": sum(
                1 for r in pipeline_rows
                if (r.get("status") or "") not in {"Disqualified", "On Hold", "Closed Lost", "Nurture", "Rejected"}
            ),
        }

    # v1.0.0al: surface recent notifications + unread count on Home so
    # users see assignments without hunting for the bell.
    notifs_recent = notifications_store.list_for(owner_name, limit=5)
    notifs_unread = notifications_store.unread_count(owner_name)

    # v1.0.0bi: surface the user's watched accounts on Home so they
    # see the watch list without a second fetch. Limited to 10 for
    # the card; the full list is on the Watch view (drawer/dedicated).
    watched_top = account_watchlist_store.list_for(owner_name)[:10]
    # Enrich with company name from the already-loaded pipeline_rows
    # (no second Notion call).
    company_by_id = {r.get("id"): r.get("company")
                      for r in pipeline_rows if r.get("id")}
    watched_payload = [{
        **w,
        "company": company_by_id.get(w.get("lead_id")) or w.get("lead_id"),
    } for w in watched_top]

    # v1.0.0am: surface the user's own todos on Home. We send the full
    # list (cheap — typical user has <20) so the UI can render +
    # filter without a second round-trip.
    todos_all = todos_store.list_for(owner_name)
    todos_summary = {
        "items":      todos_all,
        "open_count": sum(1 for t in todos_all if not t.get("done")),
        "total":      len(todos_all),
    }

    # v1.0.0ao: sweep newly-overdue todos and fire bell notifications
    # for each. Runs on every Home load — cheap (single file scan +
    # in-place mark), idempotent (overdue_notified_at gate), and means
    # the user finds out about slipped due-dates the next time they
    # open the app.
    try:
        newly_overdue = todos_store.sweep_overdue_and_mark(owner_name)
        for t in newly_overdue:
            link = t.get("link") or None
            # Don't auto-link to an entity if the todo's link isn't of
            # a navigable kind — the notification's deep-link goes to
            # the linked entity (so the user can act on it) or
            # nowhere (so clicking just marks-read).
            notifications_store.notify_assignment(
                owner_name,
                kind="todo_overdue",
                title=f"Todo overdue: {t.get('text') or '(no text)'}",
                body=(f"Due {t.get('due_date')} — flagged as overdue."),
                link=link if isinstance(link, dict) and link.get("kind") else None,
                actor=None,
            )
        # Refresh todos summary so the just-marked `overdue_notified_at`
        # values land in the payload (UI doesn't read this field today
        # but a future "already-notified" indicator could).
        if newly_overdue:
            todos_all = todos_store.list_for(owner_name)
            todos_summary = {
                "items":      todos_all,
                "open_count": sum(1 for t in todos_all if not t.get("done")),
                "total":      len(todos_all),
            }
    except Exception as e:
        log.warning("Overdue-todo sweep failed (continuing): %s", e)

    return jsonify({
        "owner": {
            "name":   owner["name"],
            "role":   owner["role"],
            "region": owner["region"],
            "email":  owner["email"],
        },
        "kpis": {
            "touches_30d":              owner_bucket["touches"] if owner_bucket else 0,
            "partner_contacts_owned":   owner_bucket["partner_contacts"] if owner_bucket else 0,
            "partner_contacts_overdue": owner_bucket["partner_contacts_overdue"] if owner_bucket else 0,
            "leads_owned":              owner_bucket["leads_owned"] if owner_bucket else 0,
            "leads_active":             owner_bucket["leads_active"] if owner_bucket else 0,
        },
        "overdue_contacts": overdue_top,
        "active_leads":     active_leads_top,
        # v1.0.0av: leads on the AE's book scoring <50 engagement, sorted
        # coldest first. Drives the "Needs attention" Home card.
        "at_risk_leads":    at_risk_leads,
        "team_snapshot":    team_snapshot,
        "role_extras":      role_extras,
        "notifications":    {
            "recent":        notifs_recent,
            "unread_count":  notifs_unread,
        },
        "todos":            todos_summary,
        # v1.0.0bi: watched accounts (top 10).
        "watched_accounts": watched_payload,
        "generated_at":     team["generated_at"],
    })


# v1.0.0bf: morning brief --------------------------------------------------
# A single endpoint that summarises today's notable signals for the user:
# - engagement drops since yesterday (notifications of kind
#   engagement_dropped that the user hasn't read yet)
# - todos due today or overdue
# - new assignments since last brief view (unread assigned_* notifications)
#
# Designed for a top-of-Home card that gives the AE the 30-second
# "what should I look at first" answer when they open the app.

@app.route("/api/home/morning-brief", methods=["GET"])
def api_home_morning_brief():
    """Return the user's morning brief — engagement drops + due todos
    + recent assignments.

    Query:
      owner — required, the user's display name.

    Returns:
      {
        "engagement_drops": [{notification_id, title, body, link, ts}],
        "todos_due_today":  [{id, text, priority, due_date}],
        "todos_overdue":    [{id, text, priority, due_date, days_overdue}],
        "new_assignments":  [{notification_id, title, body, link, ts}],
        "headline":         "<one-line summary or null>",
        "is_empty":         bool,   # True iff there's literally nothing
      }
    """
    owner = (request.args.get("owner") or "").strip()
    if not owner:
        return jsonify({"error": "owner required"}), 400

    # Pull every unread notification once; partition into the two
    # buckets we surface here.
    all_notifs = notifications_store.list_for(owner, limit=200)
    unread = [n for n in all_notifs if not n.get("read_at")]
    drops = [n for n in unread if n.get("type") == "engagement_dropped"]
    assignments = [n for n in unread
                   if n.get("type") in ("assigned_lead",
                                         "assigned_partner_contact")]

    # Strip notification rows to the fields the UI needs (smaller payload,
    # less coupling to the full notification schema).
    def _slim(n: dict) -> dict:
        return {
            "notification_id": n.get("id"),
            "title":           n.get("title"),
            "body":            n.get("body"),
            "link":            n.get("link"),
            "ts":              n.get("created_at"),
        }

    # Todos: split by today / overdue.
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    all_todos = todos_store.list_for(owner)
    due_today: list[dict] = []
    overdue: list[dict] = []
    for t in all_todos:
        if t.get("done"):
            continue
        due = t.get("due_date")
        if not due:
            continue
        if due == today:
            due_today.append({
                "id":        t.get("id"),
                "text":      t.get("text"),
                "priority":  t.get("priority"),
                "due_date":  due,
                "link":      t.get("link"),
            })
        elif due < today:
            try:
                d_then = datetime.fromisoformat(due).date()
                d_now  = datetime.fromisoformat(today).date()
                days_overdue = (d_now - d_then).days
            except (ValueError, TypeError):
                days_overdue = 0
            overdue.append({
                "id":           t.get("id"),
                "text":         t.get("text"),
                "priority":     t.get("priority"),
                "due_date":     due,
                "days_overdue": days_overdue,
                "link":         t.get("link"),
            })

    # Sort lists for predictable rendering — highest urgency first.
    overdue.sort(key=lambda t: -(t.get("days_overdue") or 0))
    due_today.sort(key=lambda t: 0 if t.get("priority") == "high"
                                     else 1 if t.get("priority") == "medium"
                                     else 2)

    parts = []
    if drops:
        parts.append(f"{len(drops)} account{'s' if len(drops) != 1 else ''} dropped engagement")
    if overdue:
        parts.append(f"{len(overdue)} overdue todo{'s' if len(overdue) != 1 else ''}")
    if due_today:
        parts.append(f"{len(due_today)} due today")
    if assignments:
        parts.append(f"{len(assignments)} new assignment{'s' if len(assignments) != 1 else ''}")
    headline = " · ".join(parts) if parts else None

    is_empty = not (drops or due_today or overdue or assignments)

    return jsonify({
        "engagement_drops": [_slim(n) for n in drops[:5]],
        "todos_due_today":  due_today[:10],
        "todos_overdue":    overdue[:10],
        "new_assignments":  [_slim(n) for n in assignments[:5]],
        "headline":         headline,
        "is_empty":         is_empty,
        "generated_at":     datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    })


# v1.0.0al: Notifications API ----------------------------------------------
# Per-user notifications, fired when ownership of an entity changes.
# Bell-icon in the nav reads `unread_count`; the dropdown reads `list`.

@app.route("/api/notifications", methods=["GET"])
def api_notifications_list():
    """List notifications for a recipient. Query params:
      recipient — required, the owner's display name
      unread    — '1' or 'true' to filter to unread-only
      limit     — int (default 50, clamped 1..200)
    """
    recipient = (request.args.get("recipient") or "").strip()
    if not recipient:
        return jsonify({"error": "recipient required"}), 400
    unread_only = (request.args.get("unread") or "").lower() in {"1", "true", "yes"}
    try:
        limit = max(1, min(200, int(request.args.get("limit", "50"))))
    except ValueError:
        limit = 50
    items = notifications_store.list_for(recipient,
                                           unread_only=unread_only,
                                           limit=limit)
    return jsonify({
        "items":        items,
        "unread_count": notifications_store.unread_count(recipient),
    })


@app.route("/api/notifications/unread-count", methods=["GET"])
def api_notifications_unread_count():
    """Lightweight poll endpoint — just the unread count for a recipient."""
    recipient = (request.args.get("recipient") or "").strip()
    if not recipient:
        return jsonify({"error": "recipient required"}), 400
    return jsonify({"unread_count": notifications_store.unread_count(recipient)})


@app.route("/api/notifications/<notification_id>/read", methods=["POST"])
def api_notifications_mark_read(notification_id: str):
    body = request.get_json(silent=True) or {}
    recipient = (body.get("recipient") or request.args.get("recipient") or "").strip()
    if not recipient:
        return jsonify({"error": "recipient required"}), 400
    ok = notifications_store.mark_read(notification_id, recipient=recipient)
    return jsonify({
        "updated":      ok,
        "unread_count": notifications_store.unread_count(recipient),
    })


@app.route("/api/notifications/read-all", methods=["POST"])
def api_notifications_mark_all_read():
    body = request.get_json(silent=True) or {}
    recipient = (body.get("recipient") or request.args.get("recipient") or "").strip()
    if not recipient:
        return jsonify({"error": "recipient required"}), 400
    n = notifications_store.mark_all_read(recipient)
    return jsonify({
        "marked":       n,
        "unread_count": notifications_store.unread_count(recipient),
    })


# v1.0.0ap: Team activity feed --------------------------------------------
# Reads the audit log, runs it through activity.format_events to drop
# the noisy internals + add human-readable summaries, and enriches with
# partner/lead names so links display real labels (not raw ids).

@app.route("/api/activity", methods=["GET"])
def api_activity():
    """Recent team activity for the Home view.

    Query: limit (int, default 20, clamped 1..100).
    Returns a list of pre-formatted display rows. Each row has
    summary, actor, timestamp, optional link. See activity.py for
    the row shape contract.
    """
    try:
        limit = max(1, min(100, int(request.args.get("limit", "20"))))
    except ValueError:
        limit = 20
    # Pull a larger raw window than `limit` so the filter has room to
    # work — many audit events are filtered out by the allowlist.
    raw = audit.read_events(limit=limit * 4)
    # Resolve partner ids → names so the summary reads "renamed Braze",
    # not "renamed braze-uuid". Cheap — single list call.
    try:
        partner_names = {p["id"]: p["name"] for p in partners_store.list_partners()}
    except Exception:
        partner_names = {}
    # Resolve lead page_ids → company names where we can. Notion is
    # the source of truth here; if it's unreachable, fall back to
    # short ids inside the formatter.
    lead_names: dict[str, str] = {}
    try:
        # Only fetch if there's at least one lead-tagged event in the
        # window — saves the round-trip when the feed is partner-only.
        if any((e.get("page_id") or e.get("lead_id")) for e in raw):
            for row in NotionSync().list_pipeline(limit=500):
                if row.get("id") and row.get("company"):
                    lead_names[row["id"]] = row["company"]
    except Exception as e:
        log.warning("Activity feed: lead name lookup failed: %s", e)
    rows = activity.format_events(raw, partner_names=partner_names,
                                    lead_names=lead_names)
    return jsonify({"items": rows[:limit]})


# v1.0.0am: Todos API ------------------------------------------------------
# Per-user scratch list, surfaced on the Home page. Not a delegation
# tool — these are your own todos, not assignable.

@app.route("/api/todos", methods=["GET"])
def api_todos_list():
    """List todos for an owner. Query:
      owner — required, display name
      include_done — '0' to hide completed (default include)
    """
    owner = (request.args.get("owner") or "").strip()
    if not owner:
        return jsonify({"error": "owner required"}), 400
    include_done = (request.args.get("include_done") or "1").lower() not in {"0", "false", "no"}
    items = todos_store.list_for(owner, include_done=include_done)
    return jsonify({"items": items})


@app.route("/api/todos", methods=["POST"])
def api_todos_create():
    body = request.get_json(silent=True) or {}
    owner = (body.get("owner") or "").strip()
    text = (body.get("text") or "").strip()
    if not owner:
        return jsonify({"error": "owner required"}), 400
    if not text:
        return jsonify({"error": "text required"}), 400
    try:
        todo = todos_store.create(owner, text,
                                    priority=body.get("priority"),
                                    due_date=body.get("due_date"),
                                    link=body.get("link"))
    except todos_store.TodosStoreError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"todo": todo}), 201


@app.route("/api/todos/<todo_id>", methods=["PATCH"])
def api_todos_update(todo_id: str):
    body = request.get_json(silent=True) or {}
    owner = (body.pop("owner", None) or request.args.get("owner") or "").strip()
    if not owner:
        return jsonify({"error": "owner required"}), 400
    try:
        todo = todos_store.update(owner, todo_id, **body)
    except todos_store.TodosStoreError as e:
        return jsonify({"error": str(e)}), 400
    if todo is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"todo": todo})


@app.route("/api/todos/<todo_id>/toggle", methods=["POST"])
def api_todos_toggle(todo_id: str):
    body = request.get_json(silent=True) or {}
    owner = (body.get("owner") or request.args.get("owner") or "").strip()
    if not owner:
        return jsonify({"error": "owner required"}), 400
    todo = todos_store.toggle_done(owner, todo_id)
    if todo is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"todo": todo})


@app.route("/api/todos/<todo_id>", methods=["DELETE"])
def api_todos_delete(todo_id: str):
    owner = (request.args.get("owner") or "").strip()
    if not owner:
        return jsonify({"error": "owner required"}), 400
    ok = todos_store.delete(owner, todo_id)
    if not ok:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"deleted": True})


@app.route("/api/todos/clear-completed", methods=["POST"])
def api_todos_clear_completed():
    body = request.get_json(silent=True) or {}
    owner = (body.get("owner") or request.args.get("owner") or "").strip()
    if not owner:
        return jsonify({"error": "owner required"}), 400
    n = todos_store.clear_completed(owner)
    return jsonify({"removed": n})


# v1.0.0ay: Filter presets API --------------------------------------------
# Per-user saved filter combinations. Scoped today to partner_contacts;
# the store accepts a `scope` field so other surfaces (pipeline,
# global search) can opt in later.

@app.route("/api/filter-presets", methods=["GET"])
def api_filter_presets_list():
    """List presets for a user. Query:
      user  — required, display name
      scope — optional, defaults to listing all scopes
    """
    user = (request.args.get("user") or "").strip()
    if not user:
        return jsonify({"error": "user required"}), 400
    scope = (request.args.get("scope") or "").strip() or None
    return jsonify({
        "items": filter_presets_store.list_for(user, scope=scope),
    })


@app.route("/api/filter-presets", methods=["POST"])
def api_filter_presets_create():
    """Save a new preset. Body:
      user, name, filters, scope (optional, default partner_contacts)
    """
    body = request.get_json(silent=True) or {}
    user = (body.get("user") or "").strip()
    name = (body.get("name") or "").strip()
    filters = body.get("filters") or {}
    scope = (body.get("scope") or "partner_contacts").strip()
    if not user:
        return jsonify({"error": "user required"}), 400
    if not name:
        return jsonify({"error": "name required"}), 400
    try:
        preset = filter_presets_store.create(user, name, filters, scope=scope)
    except filter_presets_store.PresetExists as e:
        return jsonify({"error": str(e)}), 409
    except filter_presets_store.FilterPresetsStoreError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"preset": preset}), 201


@app.route("/api/filter-presets/<preset_id>", methods=["PATCH"])
def api_filter_presets_update(preset_id: str):
    body = request.get_json(silent=True) or {}
    user = (body.pop("user", None) or request.args.get("user") or "").strip()
    if not user:
        return jsonify({"error": "user required"}), 400
    try:
        preset = filter_presets_store.update(user, preset_id, **body)
    except filter_presets_store.PresetExists as e:
        return jsonify({"error": str(e)}), 409
    except filter_presets_store.FilterPresetsStoreError as e:
        return jsonify({"error": str(e)}), 400
    if preset is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"preset": preset})


@app.route("/api/filter-presets/<preset_id>", methods=["DELETE"])
def api_filter_presets_delete(preset_id: str):
    user = (request.args.get("user") or "").strip()
    if not user:
        return jsonify({"error": "user required"}), 400
    ok = filter_presets_store.delete(user, preset_id)
    if not ok:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"deleted": True})


# v1.0.0bi: Account watchlist API -----------------------------------------
# Per-user list of leads the team wants to track for relevant news.
# Foundation today; the news fetcher + AI relevance scorer +
# notifications land in v1.0.0bj. This commit ships:
#   - the store + endpoints
#   - the "Watch" toggle on the lead drawer
#   - the "Watched accounts" Home card
# so the watch state is visible end-to-end before news pulling is live.

@app.route("/api/watchlist", methods=["GET"])
def api_watchlist_list():
    """List a user's watched accounts. Query: user (required).

    Enriches each entry with the lead's company name (best-effort via
    Notion pipeline lookup) so the UI doesn't need a second fetch
    just to render labels.
    """
    user = (request.args.get("user") or "").strip()
    if not user:
        return jsonify({"error": "user required"}), 400
    rows = account_watchlist_store.list_for(user)
    # Enrich with company names via the pipeline lookup. Best-effort —
    # if Notion is unreachable, return ids only.
    name_by_id: dict[str, str] = {}
    try:
        for r in NotionSync().list_pipeline(limit=500):
            if r.get("id") and r.get("company"):
                name_by_id[r["id"]] = r["company"]
    except Exception as e:
        log.warning("Watchlist list: pipeline enrich failed: %s", e)
    out = []
    for r in rows:
        lid = r.get("lead_id")
        out.append({
            **r,
            "company": name_by_id.get(lid) or lid,
        })
    return jsonify({"items": out})


@app.route("/api/watchlist/<lead_id>", methods=["POST"])
def api_watchlist_add(lead_id: str):
    """Add a lead to the user's watchlist. Body or query: user."""
    body = request.get_json(silent=True) or {}
    user = (body.get("user") or request.args.get("user") or "").strip()
    if not user:
        return jsonify({"error": "user required"}), 400
    try:
        entry = account_watchlist_store.add(user, lead_id)
    except account_watchlist_store.AccountWatchlistStoreError as e:
        return jsonify({"error": str(e)}), 400
    audit.log_event("watchlist_added", actor=_actor(),
                    lead_id=lead_id, user=user)
    return jsonify({"entry": entry,
                    "watching": True}), 201


@app.route("/api/watchlist/<lead_id>", methods=["DELETE"])
def api_watchlist_remove(lead_id: str):
    """Remove a lead from the user's watchlist."""
    user = (request.args.get("user") or "").strip()
    if not user:
        return jsonify({"error": "user required"}), 400
    ok = account_watchlist_store.remove(user, lead_id)
    if ok:
        audit.log_event("watchlist_removed", actor=_actor(),
                        lead_id=lead_id, user=user)
    return jsonify({"removed": ok, "watching": False})


@app.route("/api/watchlist/<lead_id>/status", methods=["GET"])
def api_watchlist_status(lead_id: str):
    """Cheap is-this-user-watching check. Used by the drawer to
    decide whether the toggle starts on or off."""
    user = (request.args.get("user") or "").strip()
    if not user:
        return jsonify({"error": "user required"}), 400
    return jsonify({"watching": account_watchlist_store.is_watching(user, lead_id)})


# v1.0.0bk: Live Projects API ---------------------------------------------
# Post-sale account management surface. Lead → won → live project →
# OKR tracking + delivery. Distinct from the pre-sale ProjectScope
# (scope.py) which handles SOW/pricing.

@app.route("/api/live-projects", methods=["GET"])
def api_live_projects_list():
    """List live projects. Query: status (optional filter).

    Enriches each row with the lead's company name (best-effort
    Notion lookup) + OKR summary so the index renders without
    further fetches.
    """
    status = (request.args.get("status") or "").strip() or None
    projects = live_projects_store.list_all(status=status)
    # Enrich with company names.
    name_by_id: dict[str, str] = {}
    try:
        for r in NotionSync().list_pipeline(limit=500):
            if r.get("id") and r.get("company"):
                name_by_id[r["id"]] = r["company"]
    except Exception as e:
        log.warning("Live projects list: pipeline enrich failed: %s", e)
    out = []
    for p in projects:
        okrs = live_project_okrs_store.list_for_project(p["id"])
        # Aggregate OKR health across this project's current OKRs.
        total_krs = sum(len(o.get("key_results") or []) for o in okrs)
        agg_summary = {"total_okrs": len(okrs), "total_krs": total_krs}
        if total_krs:
            on_track = sum(
                sum(1 for k in (o.get("key_results") or [])
                    if k.get("status") in ("on_track", "done"))
                for o in okrs)
            agg_summary["health_pct"] = round(100 * on_track / total_krs)
        else:
            agg_summary["health_pct"] = None
        out.append({
            **p,
            "company": name_by_id.get(p.get("lead_id")) or p.get("lead_id"),
            "okr_summary": agg_summary,
        })
    return jsonify({"items": out})


@app.route("/api/live-projects/<project_id>", methods=["GET"])
def api_live_projects_get(project_id: str):
    """Full detail: project + every OKR + per-OKR summary +
    contacts + agencies for the stakeholder map and concurrent-
    agencies surfaces (v1.0.0bl)."""
    project = live_projects_store.get(project_id)
    if not project:
        return jsonify({"error": "not_found"}), 404
    okrs = live_project_okrs_store.list_for_project(project_id)
    okrs_with_summary = [
        {**o, "summary": live_project_okrs_store.summarise(o)}
        for o in okrs
    ]
    # Enrich with the lead's display name.
    lead_id = project.get("lead_id")
    company = lead_id
    try:
        lead = NotionSync().get_page(lead_id) or {}
        company = lead.get("company") or company
    except Exception:
        pass
    # v1.0.0bl: pull contacts (for stakeholder map) + agencies (for
    # concurrent agencies + the broader account picture). Both are
    # already keyed by lead_id so no extra lookup needed.
    contacts = contacts_store.list_contacts(lead_id) if lead_id else []
    agencies = lead_agencies_store.list_agencies(lead_id) if lead_id else []
    return jsonify({
        "project":  {**project, "company": company},
        "okrs":     okrs_with_summary,
        "contacts": contacts,
        "agencies": agencies,
    })


@app.route("/api/live-projects/<project_id>", methods=["PATCH"])
def api_live_projects_update(project_id: str):
    body = request.get_json(silent=True) or {}
    try:
        updated = live_projects_store.update(project_id, **body)
    except live_projects_store.LiveProjectsStoreError as e:
        return jsonify({"error": str(e)}), 400
    if updated is None:
        return jsonify({"error": "not_found"}), 404
    audit.log_event("live_project_updated", actor=_actor(),
                    project_id=project_id,
                    fields=sorted(body.keys()))
    return jsonify({"project": updated})


@app.route("/api/live-projects/<project_id>", methods=["DELETE"])
def api_live_projects_delete(project_id: str):
    """Hard-delete. Use status=archived to preserve history instead."""
    ok = live_projects_store.delete(project_id)
    if not ok:
        return jsonify({"error": "not_found"}), 404
    audit.log_event("live_project_deleted", actor=_actor(),
                    project_id=project_id)
    return jsonify({"deleted": True})


@app.route("/api/lead/<lead_id>/promote-to-live", methods=["POST"])
def api_promote_lead_to_live(lead_id: str):
    """Convert a lead into a live project. Body:
      name    — optional, defaults to lead's company name
      owner   — optional, defaults to lead's current owner
      summary — optional starting summary
      started_at — optional YYYY-MM-DD; defaults to today

    The live project doesn't COPY contacts/agencies/tech_stack —
    it references the lead, so any updates over there flow through
    automatically. One less place for drift.
    """
    body = request.get_json(silent=True) or {}
    # If a live project already exists for this lead, idempotent-return it.
    existing = live_projects_store.get_by_lead(lead_id)
    if existing:
        return jsonify({"project": existing,
                         "created": False,
                         "message": "Lead already has a live project."}), 200
    # Pull lead context for sensible defaults.
    company = None
    lead_owner = None
    opp_type = None
    try:
        lead = NotionSync().get_page(lead_id) or {}
        company = (lead.get("company") or "").strip() or None
        lead_owner = (lead.get("owner") or "").strip() or None
        opp_type = (lead.get("opportunity_type") or "").strip() or None
    except Exception as e:
        log.warning("promote-to-live: lead lookup failed: %s", e)
    # v1.0.0by: name defaults to "<company> — <opportunity type>" so the
    # Live Projects list distinguishes "Shell — CRM Build" from
    # "Shell — Retention" when the same anchor has multiple workstreams
    # over time. UI passes its composed default; if the body omits a
    # name we recompose server-side so the contract is symmetric.
    default_name = _compose_live_project_name(company, opp_type, fallback=lead_id)
    name = (body.get("name") or default_name).strip() or default_name
    owner = (body.get("owner") or lead_owner or _actor() or "").strip() or None
    started_at = (body.get("started_at") or "").strip() or None
    summary = (body.get("summary") or "").strip() or None
    try:
        project = live_projects_store.create(
            lead_id=lead_id, name=name, owner=owner,
            started_at=started_at, summary=summary,
            tags=body.get("tags") or [])
    except live_projects_store.LiveProjectsStoreError as e:
        return jsonify({"error": str(e)}), 400
    audit.log_event("live_project_created", actor=_actor(),
                    project_id=project["id"], lead_id=lead_id,
                    name=name)
    return jsonify({"project": project, "created": True}), 201


# ---- OKRs nested under a project -----------------------------------------

@app.route("/api/live-projects/<project_id>/okrs", methods=["POST"])
def api_okrs_create(project_id: str):
    body = request.get_json(silent=True) or {}
    if not live_projects_store.get(project_id):
        return jsonify({"error": "project not found"}), 404
    try:
        okr = live_project_okrs_store.create(
            project_id=project_id,
            quarter=body.get("quarter") or "",
            objective=body.get("objective") or "",
            key_results=body.get("key_results") or [])
    except live_project_okrs_store.LiveProjectOkrsStoreError as e:
        return jsonify({"error": str(e)}), 400
    audit.log_event("live_project_okr_created", actor=_actor(),
                    project_id=project_id, okr_id=okr["id"],
                    quarter=okr["quarter"])
    return jsonify({"okr": okr}), 201


@app.route("/api/okrs/<okr_id>", methods=["PATCH"])
def api_okrs_update(okr_id: str):
    body = request.get_json(silent=True) or {}
    try:
        updated = live_project_okrs_store.update(okr_id, **body)
    except live_project_okrs_store.LiveProjectOkrsStoreError as e:
        return jsonify({"error": str(e)}), 400
    if updated is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"okr": updated})


@app.route("/api/okrs/<okr_id>", methods=["DELETE"])
def api_okrs_delete(okr_id: str):
    ok = live_project_okrs_store.delete(okr_id)
    if not ok:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"deleted": True})


@app.route("/api/okrs/<okr_id>/key-results", methods=["POST"])
def api_okr_kr_add(okr_id: str):
    body = request.get_json(silent=True) or {}
    try:
        kr = live_project_okrs_store.add_key_result(okr_id, body)
    except live_project_okrs_store.LiveProjectOkrsStoreError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"key_result": kr}), 201


@app.route("/api/okrs/<okr_id>/key-results/<kr_id>", methods=["PATCH"])
def api_okr_kr_update(okr_id: str, kr_id: str):
    body = request.get_json(silent=True) or {}
    try:
        kr = live_project_okrs_store.update_key_result(okr_id, kr_id, **body)
    except live_project_okrs_store.LiveProjectOkrsStoreError as e:
        return jsonify({"error": str(e)}), 400
    if kr is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"key_result": kr})


@app.route("/api/okrs/<okr_id>/key-results/<kr_id>", methods=["DELETE"])
def api_okr_kr_delete(okr_id: str, kr_id: str):
    ok = live_project_okrs_store.delete_key_result(okr_id, kr_id)
    if not ok:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"deleted": True})


# v1.0.0bs: Jeff — in-app pricing + scoping assistant -------------------
# Floating chat panel; backend is one chat endpoint that builds a system
# prompt from jeff_knowledge (live pricing facts + admin-edited best
# practices doc) and calls Claude. Skill level + current view context
# travel with each turn so Jeff can adapt verbosity and target advice.
#
# Why a thin server-side endpoint rather than client→Claude direct:
# we don't want the ANTHROPIC_API_KEY in the browser, and we want the
# system prompt assembly (which pulls from code) to live server-side.

@app.route("/api/jeff/chat", methods=["POST"])
def api_jeff_chat():
    """Chat turn for Jeff.

    Body:
      {
        "messages": [{"role": "user"|"assistant", "content": "..."}, ...],
        "context":  {"view": "build", "lead": {...}, "pricing": {...}},
        "skill":    "beginner" | "intermediate" | "expert",
      }

    Returns:
      {"message": "<assistant reply>"} on success
      {"error": "...", "code": "..."} on failure (with 4xx/5xx status)

    The user-visible failure modes:
      - 503 jeff_disabled: ANTHROPIC_API_KEY not set
      - 400 invalid_request: no messages / messages malformed
      - 502 upstream_error: Anthropic call failed
    """
    import jeff_knowledge

    if not jeff_knowledge.is_configured():
        return jsonify({
            "error": "Jeff is offline — ANTHROPIC_API_KEY isn't set on the server.",
            "code":  "jeff_disabled",
        }), 503

    body = request.get_json(silent=True) or {}
    messages = body.get("messages") or []
    if not isinstance(messages, list) or not messages:
        return jsonify({
            "error": "messages array required",
            "code":  "invalid_request",
        }), 400
    # Normalise + validate. We don't trust the role string from the
    # client — re-derive to "user"/"assistant" only.
    clean: list[dict] = []
    for m in messages[-20:]:  # cap context to last 20 turns
        if not isinstance(m, dict):
            continue
        role = "assistant" if m.get("role") == "assistant" else "user"
        content = str(m.get("content") or "").strip()
        if not content:
            continue
        # Cap individual messages so a runaway paste can't blow context.
        clean.append({"role": role, "content": content[:8000]})
    if not clean:
        return jsonify({
            "error": "no usable message content",
            "code":  "invalid_request",
        }), 400

    skill = (body.get("skill") or "intermediate").lower()
    context = body.get("context") or {}
    if not isinstance(context, dict):
        context = {}

    system = jeff_knowledge.build_system_prompt(skill=skill, context=context)

    try:
        from anthropic import Anthropic
    except ImportError:
        log.error("Jeff chat: anthropic SDK not installed")
        return jsonify({
            "error": "Anthropic SDK not installed on the server.",
            "code":  "jeff_disabled",
        }), 503

    try:
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"].strip())
        # Sonnet for quality — sales tooling, low volume.
        model = os.environ.get("JEFF_MODEL",
                                 os.environ.get("ANTHROPIC_MODEL",
                                                  "claude-sonnet-4-5"))
        resp = client.messages.create(
            model=model,
            max_tokens=1024,
            system=system,
            messages=clean,
        )
        # Anthropic returns content as a list of blocks; concatenate
        # the text ones.
        reply_parts = []
        for block in (resp.content or []):
            if getattr(block, "type", None) == "text":
                reply_parts.append(getattr(block, "text", "") or "")
        reply = "".join(reply_parts).strip() or "(Jeff returned an empty reply.)"
    except Exception as e:
        log.warning("Jeff chat upstream error: %s", e)
        return jsonify({
            "error": f"Jeff couldn't respond: {e}",
            "code":  "upstream_error",
        }), 502

    audit.log_event("jeff_chat", actor=_actor(),
                     skill=skill,
                     view=(context.get("view") or "")[:32],
                     turns=len(clean),
                     reply_chars=len(reply))
    return jsonify({"message": reply})


@app.route("/api/jeff/knowledge", methods=["GET"])
def api_jeff_knowledge_get():
    """Read the admin-editable best-practices doc. Settings UI loads
    this into a textarea for editing."""
    import jeff_knowledge
    body = jeff_knowledge.load_best_practices()
    return jsonify({
        "body":       body,
        "chars":      len(body),
        "configured": jeff_knowledge.is_configured(),
    })


@app.route("/api/jeff/knowledge", methods=["PUT"])
def api_jeff_knowledge_save():
    """Save the admin-editable best-practices doc."""
    import jeff_knowledge
    payload = request.get_json(silent=True) or {}
    body = payload.get("body")
    if not isinstance(body, str):
        return jsonify({"error": "body string required"}), 400
    try:
        jeff_knowledge.save_best_practices(body)
    except OSError as e:
        return jsonify({"error": f"save failed: {e}"}), 500
    audit.log_event("jeff_knowledge_updated", actor=_actor(),
                     chars=len(body))
    return jsonify({"saved": True, "chars": len(body)})


# v1.0.0br: Directory ------------------------------------------------------
# Cross-surface roster. One place to browse every account + every
# contact across all stores (Notion pipeline, expansion targets,
# live projects, lead contacts, partner contacts, agency embedded
# contacts, expansion target embedded contacts).
#
# Why aggregate here instead of normalising upstream: each store has
# different concerns (pipeline drives scoring, partner contacts have
# territory metadata, agency contacts are scoped to the deal context,
# etc.) — they're correctly separate at the storage layer. The
# directory is the read-side view that joins them.

@app.route("/api/directory/accounts", methods=["GET"])
def api_directory_accounts():
    """Every account we have data on, deduped by lead_id where
    possible. Each row tells the UI:

      {
        lead_id:                "<page-id> | <synthetic for orphan target>",
        name:                   "Shell North America",
        kind:                   "lead" | "expansion_target_orphan",
        status:                 "Qualified" | None,
        owner:                  "Ben Ojuolape" | None,
        vertical:               "Energy" | None,
        icp_normalised:         8.5 | None,
        url:                    "https://www.shell.com" | None,
        has_live_project:       True | False,
        live_project_status:    "active" | None,
        expansion_target_count: 3,
        contact_count:          12,
      }

    Notion pipeline failures don't strand the view — we surface
    what's locally cached (live projects + targets) even if Notion
    is unreachable.
    """
    name_filter = (request.args.get("q") or "").strip().lower()
    # Pull everything once. Each `try` is independent so a failure in
    # one source doesn't blank the others.
    leads: list[dict] = []
    try:
        leads = NotionSync().list_pipeline(limit=500)
    except Exception as e:
        log.warning("Directory accounts: Notion pipeline fetch failed: %s", e)
    projects = live_projects_store.list_all()
    targets = expansion_targets_store.list_all()

    # Index by lead_id for fast joins.
    project_by_lead = {p["lead_id"]: p for p in projects if p.get("lead_id")}
    targets_by_anchor: dict[str, int] = {}
    for t in targets:
        a = t.get("anchor_lead_id")
        if a:
            targets_by_anchor[a] = targets_by_anchor.get(a, 0) + 1

    # Per-lead contact count (walk the contacts store directory once,
    # cheaper than N round-trips through list_contacts).
    contact_counts: dict[str, int] = {}
    try:
        d = contacts_store._store_dir()
        if d.exists():
            for f in d.glob("*.json"):
                try:
                    rows = json.loads(f.read_text())
                    if isinstance(rows, list):
                        # File name is the slugified lead_id; we match
                        # against slugified lead ids below.
                        contact_counts[f.stem] = len(rows)
                except (json.JSONDecodeError, OSError):
                    continue
    except Exception as e:
        log.warning("Directory accounts: contact-count scan failed: %s", e)

    def _slug_for(lead_id: str) -> str:
        try:
            return project_store.slugify(lead_id)
        except Exception:
            return lead_id

    items: list[dict] = []
    seen_leads: set[str] = set()
    for lead in leads:
        lid = lead.get("id") or ""
        if not lid:
            continue
        seen_leads.add(lid)
        slug = _slug_for(lid)
        proj = project_by_lead.get(lid)
        items.append({
            "lead_id":                lid,
            "name":                   lead.get("company") or lid,
            "kind":                   "lead",
            "status":                 lead.get("status"),
            "sales_stage":            lead.get("sales_stage"),
            "owner":                  lead.get("owner"),
            "vertical":               lead.get("vertical"),
            "icp_normalised":         lead.get("icp_normalised"),
            "url":                    lead.get("company_url"),
            "last_edited":            lead.get("last_edited"),
            "has_live_project":       bool(proj),
            "live_project_status":    proj.get("status") if proj else None,
            "expansion_target_count": targets_by_anchor.get(lid, 0),
            "contact_count":          contact_counts.get(slug, 0),
        })

    # Orphan rows: expansion target anchors that don't appear in the
    # pipeline. Group them under a synthetic "account" row so the
    # user can still see the work in flight from this anchor.
    for anchor_id, count in targets_by_anchor.items():
        if anchor_id in seen_leads:
            continue
        items.append({
            "lead_id":                anchor_id,
            "name":                   anchor_id,
            "kind":                   "expansion_target_orphan",
            "status":                 None,
            "owner":                  None,
            "vertical":               None,
            "icp_normalised":         None,
            "url":                    None,
            "last_edited":            None,
            "has_live_project":       False,
            "live_project_status":    None,
            "expansion_target_count": count,
            "contact_count":          0,
        })

    if name_filter:
        items = [i for i in items
                  if name_filter in (i["name"] or "").lower()
                  or name_filter in (i.get("vertical") or "").lower()
                  or name_filter in (i.get("owner") or "").lower()]

    items.sort(key=lambda i: (i["name"] or "").lower())
    return jsonify({
        "items":  items,
        "count":  len(items),
        "totals": {
            "leads":               sum(1 for i in items if i["kind"] == "lead"),
            "orphan_targets":      sum(1 for i in items
                                        if i["kind"] == "expansion_target_orphan"),
            "with_live_project":   sum(1 for i in items if i["has_live_project"]),
            "with_expansion":      sum(1 for i in items
                                        if i["expansion_target_count"] > 0),
        },
    })


@app.route("/api/directory/contacts", methods=["GET"])
def api_directory_contacts():
    """Every contact we know across every store, with source attribution
    so the UI can render "Sarah Johnson — Head of Loyalty (via Shell
    lead)" vs "Marina Klusas — AE (Braze partner)" appropriately.

    Sources:
      - lead          → contacts_store (per Notion lead)
      - partner       → partner_contacts_store (partner roster)
      - agency        → lead_agencies_store (embedded in agencies)
      - expansion     → expansion_targets_store (embedded in targets)

    Each item:
      {
        id:             "<source-id>",
        name:           "Sarah Johnson",
        title:          "Head of Loyalty UK",
        email:          "sarah@shell.com",
        phone:          "..." | None,
        source:         "lead" | "partner" | "agency" | "expansion",
        source_company: "Shell" | "Braze" | "Accenture" | "Shell UK",
        source_id:      "<lead-id> | <partner-id> | ...",
        stakeholder_role: "champion" | None,   # lead contacts only
        last_contacted: iso | None,
      }
    """
    q = (request.args.get("q") or "").strip().lower()
    source_filter = (request.args.get("source") or "").strip().lower()
    items: list[dict] = []

    # Pipeline name lookup — used to label lead contacts with the
    # company name rather than just the page_id.
    name_by_lead: dict[str, str] = {}
    try:
        for r in NotionSync().list_pipeline(limit=500):
            if r.get("id") and r.get("company"):
                name_by_lead[r["id"]] = r["company"]
    except Exception as e:
        log.warning("Directory contacts: pipeline name lookup failed: %s", e)

    # 1) Lead contacts — walk the contacts_store directory.
    try:
        d = contacts_store._store_dir()
        if d.exists():
            for f in d.glob("*.json"):
                lead_slug = f.stem
                try:
                    rows = json.loads(f.read_text())
                except (json.JSONDecodeError, OSError):
                    continue
                if not isinstance(rows, list):
                    continue
                # Try to resolve slug back to a human name via the
                # pipeline name map (slugs are a lossy transform but
                # they round-trip on simple names). Fall back to
                # the slug itself.
                company = name_by_lead.get(lead_slug)
                if not company:
                    # Best-effort: pipeline ids may not slug-match;
                    # try direct id lookup too.
                    for k, v in name_by_lead.items():
                        if project_store.slugify(k) == lead_slug:
                            company = v
                            break
                company = company or lead_slug
                for c in rows:
                    items.append({
                        "id":              c.get("id"),
                        "name":            c.get("name"),
                        "title":           c.get("title"),
                        "email":           c.get("email"),
                        "phone":           c.get("phone"),
                        "source":          "lead",
                        "source_company":  company,
                        "source_id":       lead_slug,
                        "stakeholder_role": c.get("stakeholder_role"),
                        "influence":       c.get("influence"),
                        "interest":        c.get("interest"),
                        "last_contacted":  c.get("last_contacted"),
                    })
    except Exception as e:
        log.warning("Directory contacts: lead-contacts scan failed: %s", e)

    # 2) Partner contacts.
    try:
        partner_name_by_id: dict[str, str] = {}
        for p in partners_store.list_partners():
            if p.get("id"):
                partner_name_by_id[p["id"]] = p.get("name") or p["id"]
        for c in partner_contacts_store.list_all_contacts():
            pid = c.get("partner_id") or ""
            items.append({
                "id":              c.get("id"),
                "name":            c.get("name"),
                "title":           c.get("title"),
                "email":           c.get("email"),
                "phone":           c.get("phone"),
                "source":          "partner",
                "source_company":  partner_name_by_id.get(pid, pid),
                "source_id":       pid,
                "stakeholder_role": None,
                "last_contacted":  c.get("last_touched"),
            })
    except Exception as e:
        log.warning("Directory contacts: partner-contacts scan failed: %s", e)

    # 3) Agency embedded contacts — walk lead_agencies_store directory.
    # Slug → company resolution mirrors the lead-contacts path:
    # the on-disk file name is `slugify(lead_id)`, but pipeline lookups
    # are keyed by the raw page_id. We do the slug-back walk so the
    # "via Shell" suffix isn't "via shell_na" garbage.
    def _company_for_slug(slug: str) -> str:
        if slug in name_by_lead:
            return name_by_lead[slug]
        for raw_id, name in name_by_lead.items():
            if project_store.slugify(raw_id) == slug:
                return name
        return slug

    try:
        d = lead_agencies_store._store_dir()
        if d.exists():
            for f in d.glob("*.json"):
                lead_slug = f.stem
                try:
                    agencies = json.loads(f.read_text())
                except (json.JSONDecodeError, OSError):
                    continue
                if not isinstance(agencies, list):
                    continue
                company = _company_for_slug(lead_slug)
                for ag in agencies:
                    ag_name = ag.get("name") or "agency"
                    for c in (ag.get("contacts") or []):
                        if not c.get("name"):
                            continue
                        items.append({
                            "id":              c.get("id"),
                            "name":            c.get("name"),
                            "title":           c.get("title"),
                            "email":           c.get("email"),
                            "phone":           None,
                            "source":          "agency",
                            "source_company":  f"{ag_name} (via {company})",
                            "source_id":       lead_slug,
                            "stakeholder_role": None,
                            "last_contacted":  None,
                        })
    except Exception as e:
        log.warning("Directory contacts: agency-contacts scan failed: %s", e)

    # 4) Expansion target embedded contacts.
    try:
        for t in expansion_targets_store.list_all():
            for c in (t.get("contacts") or []):
                if not c.get("name"):
                    continue
                items.append({
                    "id":              c.get("id"),
                    "name":            c.get("name"),
                    "title":           c.get("title"),
                    "email":           c.get("email"),
                    "phone":           None,
                    "source":          "expansion",
                    "source_company":  t.get("name") or "expansion target",
                    "source_id":       t.get("id"),
                    "stakeholder_role": None,
                    "last_contacted":  None,
                })
    except Exception as e:
        log.warning("Directory contacts: expansion-contacts scan failed: %s", e)

    # Filter + sort.
    if source_filter:
        items = [i for i in items if i["source"] == source_filter]
    if q:
        items = [i for i in items
                  if q in (i.get("name") or "").lower()
                  or q in (i.get("email") or "").lower()
                  or q in (i.get("title") or "").lower()
                  or q in (i.get("source_company") or "").lower()]
    items.sort(key=lambda i: (i.get("name") or "").lower())

    # Totals computed BEFORE filtering so the UI can show "5 of 312"
    # — but since we already filtered, compute totals from the
    # unfiltered set instead. Re-walk is cheap.
    # Simpler: build totals from `items` post-filter (matches what the
    # user sees) + return unfiltered counts in a separate field.
    return jsonify({
        "items":   items,
        "count":   len(items),
        "by_source": {
            "lead":      sum(1 for i in items if i["source"] == "lead"),
            "partner":   sum(1 for i in items if i["source"] == "partner"),
            "agency":    sum(1 for i in items if i["source"] == "agency"),
            "expansion": sum(1 for i in items if i["source"] == "expansion"),
        },
    })


# v1.0.0bo: Account expansion API -----------------------------------------
# Land-and-expand surface. Each "expansion target" sits between
# "known opportunity" and "real lead in pipeline" — captures the
# pre-qualification research + contact mapping anchored to a won
# account. Convert flow promotes a target into the pipeline when
# ready.

@app.route("/api/expansion/overview", methods=["GET"])
def api_expansion_overview():
    """Top-of-view aggregate: every landed account (live project)
    + its expansion targets in one payload. Powers the grouped
    list render on the Expansion view.

    Each row in `anchors`:
      {
        anchor_id:       live project id (None if anchored only by lead),
        lead_id:         the lead this anchor traces back to,
        company:         display name (from Notion),
        project_status:  active|paused|completed (None if anchor has no live project),
        targets:         [expansion_target...],
        target_counts:   {total, by_status: {greenfield: N, ...}}
      }

    Targets whose anchor_lead_id doesn't match any live project (or
    Notion lead) land under a synthetic "Unlinked" anchor at the
    bottom so they stay visible.
    """
    # Pull state: live projects + every target + pipeline rows (for
    # name resolution).
    projects = live_projects_store.list_all()
    targets = expansion_targets_store.list_all()
    name_by_lead: dict[str, str] = {}
    try:
        for r in NotionSync().list_pipeline(limit=500):
            if r.get("id") and r.get("company"):
                name_by_lead[r["id"]] = r["company"]
    except Exception as e:
        log.warning("Expansion overview: pipeline name lookup failed: %s", e)

    # Build the anchor list: every live project becomes one,
    # PLUS any anchor_lead_id referenced by a target that doesn't
    # have a live project (covers "we know we want to expand from
    # this account but haven't promoted it yet").
    anchors_by_lead: dict[str, dict] = {}
    for p in projects:
        lid = p.get("lead_id")
        if not lid:
            continue
        anchors_by_lead[lid] = {
            "anchor_id":      p.get("id"),
            "lead_id":        lid,
            "company":        name_by_lead.get(lid) or lid,
            "project_name":   p.get("name"),
            "project_status": p.get("status"),
            "targets":        [],
            "target_counts":  {"total": 0, "by_status": {}},
        }
    for t in targets:
        lid = t.get("anchor_lead_id")
        if lid and lid not in anchors_by_lead:
            anchors_by_lead[lid] = {
                "anchor_id":      None,
                "lead_id":        lid,
                "company":        name_by_lead.get(lid) or lid,
                "project_name":   None,
                "project_status": None,
                "targets":        [],
                "target_counts":  {"total": 0, "by_status": {}},
            }
        if lid in anchors_by_lead:
            anchors_by_lead[lid]["targets"].append(t)

    # Aggregate counts per anchor.
    for anchor in anchors_by_lead.values():
        anchor["targets"].sort(
            key=lambda x: (
                # Greenfield first (most actionable), then by name
                0 if x.get("status") == "greenfield" else
                1 if x.get("status") in ("researching", "qualifying") else 2,
                (x.get("name") or "").lower(),
            ))
        counts = {"total": len(anchor["targets"]), "by_status": {}}
        for t in anchor["targets"]:
            s = t.get("status", "greenfield")
            counts["by_status"][s] = counts["by_status"].get(s, 0) + 1
        anchor["target_counts"] = counts

    # Sort anchors: ones with targets first (more work to do),
    # then alphabetical.
    anchors = sorted(
        anchors_by_lead.values(),
        key=lambda a: (a["target_counts"]["total"] == 0,
                        (a["company"] or "").lower()))
    return jsonify({
        "anchors":       anchors,
        "totals": {
            "anchors":         len(anchors),
            "targets":         len(targets),
            "greenfield":      sum(1 for t in targets if t.get("status") == "greenfield"),
            "in_progress":     sum(1 for t in targets if t.get("status") in ("researching", "qualifying")),
            "converted":       sum(1 for t in targets if t.get("status") == "converted_to_lead"),
        },
    })


@app.route("/api/expansion-targets", methods=["POST"])
def api_expansion_targets_create():
    body = request.get_json(silent=True) or {}
    try:
        t = expansion_targets_store.create(
            anchor_lead_id=body.get("anchor_lead_id") or "",
            name=body.get("name") or "",
            region=body.get("region") or None,
            vertical=body.get("vertical") or None,
            notes=body.get("notes") or None)
    except expansion_targets_store.ExpansionTargetsStoreError as e:
        return jsonify({"error": str(e)}), 400
    audit.log_event("expansion_target_created", actor=_actor(),
                    target_id=t["id"], anchor_lead_id=t["anchor_lead_id"],
                    name=t["name"])
    return jsonify({"target": t}), 201


@app.route("/api/expansion-targets/<target_id>", methods=["GET"])
def api_expansion_targets_get(target_id: str):
    t = expansion_targets_store.get(target_id)
    if not t:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"target": t})


@app.route("/api/expansion-targets/<target_id>", methods=["PATCH"])
def api_expansion_targets_update(target_id: str):
    body = request.get_json(silent=True) or {}
    try:
        t = expansion_targets_store.update(target_id, **body)
    except expansion_targets_store.ExpansionTargetsStoreError as e:
        return jsonify({"error": str(e)}), 400
    if t is None:
        return jsonify({"error": "not_found"}), 404
    audit.log_event("expansion_target_updated", actor=_actor(),
                    target_id=target_id, fields=sorted(body.keys()))
    return jsonify({"target": t})


@app.route("/api/expansion-targets/<target_id>", methods=["DELETE"])
def api_expansion_targets_delete(target_id: str):
    ok = expansion_targets_store.delete(target_id)
    if not ok:
        return jsonify({"error": "not_found"}), 404
    audit.log_event("expansion_target_deleted", actor=_actor(),
                    target_id=target_id)
    return jsonify({"deleted": True})


# ---- per-target contacts -------------------------------------------------

@app.route("/api/expansion-targets/<target_id>/contacts", methods=["POST"])
def api_expansion_target_contact_add(target_id: str):
    body = request.get_json(silent=True) or {}
    try:
        c = expansion_targets_store.add_contact(target_id, body)
    except expansion_targets_store.ExpansionTargetsStoreError as e:
        msg = str(e)
        # If the target didn't exist we want 404, not 400.
        if "not found" in msg.lower():
            return jsonify({"error": msg}), 404
        return jsonify({"error": msg}), 400
    return jsonify({"contact": c}), 201


@app.route("/api/expansion-targets/<target_id>/contacts/<contact_id>",
            methods=["PATCH"])
def api_expansion_target_contact_update(target_id: str, contact_id: str):
    body = request.get_json(silent=True) or {}
    try:
        c = expansion_targets_store.update_contact(target_id, contact_id, **body)
    except expansion_targets_store.ExpansionTargetsStoreError as e:
        return jsonify({"error": str(e)}), 400
    if c is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"contact": c})


@app.route("/api/expansion-targets/<target_id>/contacts/<contact_id>",
            methods=["DELETE"])
def api_expansion_target_contact_delete(target_id: str, contact_id: str):
    ok = expansion_targets_store.delete_contact(target_id, contact_id)
    if not ok:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"deleted": True})


# ---- conversion ---------------------------------------------------------

@app.route("/api/expansion-targets/<target_id>/convert-to-lead",
            methods=["POST"])
def api_expansion_target_convert(target_id: str):
    """Mark a target as converted-to-lead. Body must include
    `lead_id` (the page_id of the new lead the AE just created).
    Idempotent — re-marking a converted target just updates the
    converted_lead_id.

    The actual lead creation happens via the standard Qualify
    flow; this endpoint only updates the bookkeeping so we
    preserve the lineage (target → lead).
    """
    body = request.get_json(silent=True) or {}
    lead_id = (body.get("lead_id") or "").strip()
    if not lead_id:
        return jsonify({"error": "lead_id required"}), 400
    t = expansion_targets_store.mark_converted(target_id, lead_id)
    if t is None:
        return jsonify({"error": "not_found"}), 404
    audit.log_event("expansion_target_converted", actor=_actor(),
                    target_id=target_id, lead_id=lead_id)
    return jsonify({"target": t})


# v1.0.0bj: account news --------------------------------------------------
# Fetch + score + persist + notify. The lead drawer hits
# /api/lead/<id>/news to render the news card; /api/admin/watchlist/sweep
# scans every watched account and fires notifications for new
# relevant items.

@app.route("/api/lead/<lead_id>/news", methods=["GET"])
def api_lead_news_list(lead_id: str):
    """Return persisted scored news for a lead. Does NOT fetch new
    items — that happens via the explicit refresh endpoint below or
    the sweep. List-only is cheap so the drawer can render it on
    every open without polling Google News."""
    return jsonify({
        "items": account_news_store.list_for(lead_id, limit=20),
    })


@app.route("/api/lead/<lead_id>/news/refresh", methods=["POST"])
def api_lead_news_refresh(lead_id: str):
    """Fetch fresh news for this lead, score via Claude, persist.
    Returns the updated list. UI calls this when the AE clicks
    Refresh on the news card."""
    # Need the company name to query Google News. Pull from Notion.
    try:
        lead = NotionSync().get_page(lead_id) or {}
    except Exception as e:
        return jsonify({"error": f"Couldn't resolve lead: {e}"}), 502
    company = (lead.get("company") or "").strip()
    if not company:
        return jsonify({"error": "lead has no company name"}), 400
    raw = account_news.fetch_for_company(company, limit=15)
    if not raw:
        return jsonify({
            "items": account_news_store.list_for(lead_id, limit=20),
            "added": 0, "scored": 0,
            "message": "No news found",
        })
    # Skip items we've already scored to save tokens + dedup notifications.
    seen = account_news_store.ids_already_seen(lead_id)
    fresh = [i for i in raw if i["id"] not in seen]
    scored = account_news.score_relevance(fresh, company) if fresh else []
    result = account_news_store.upsert_many(lead_id, scored)
    return jsonify({
        "items":  account_news_store.list_for(lead_id, limit=20),
        "added":  result["added"],
        "scored": len(scored),
        "raw":    len(raw),
    })


@app.route("/api/admin/watchlist/sweep", methods=["POST"])
def api_watchlist_sweep():
    """Scan every watched account: fetch news, score, persist new
    items, fire `news_alert` notifications to each watcher for items
    they haven't seen yet. Designed to be called daily (cron / cloud
    scheduler) but works on-demand too.

    Optional query:
      lead_id — restrict to one lead (testing / debugging)
    """
    only = (request.args.get("lead_id") or "").strip() or None
    summary: dict[str, Any] = {
        "leads_scanned": 0,
        "items_added":   0,
        "notifications_fired": 0,
        "errors": [],
    }
    # Build the set of leads to scan: every lead that any user is watching.
    lead_to_watchers: dict[str, list[str]] = {}
    try:
        for f in account_watchlist_store._store_dir().glob("*.json"):
            try:
                rows = json.loads(f.read_text())
                if not isinstance(rows, list):
                    continue
                user = f.stem  # slug — notifications_store accepts it
                for r in rows:
                    lid = (r.get("lead_id") or "").strip()
                    if not lid or (only and lid != only):
                        continue
                    lead_to_watchers.setdefault(lid, []).append(user)
            except (OSError, ValueError):
                continue
    except Exception as e:
        summary["errors"].append(f"watchlist scan: {e}")
        return jsonify(summary), 500

    # Resolve company names for every lead in one Notion call.
    company_by_id: dict[str, str] = {}
    try:
        sync = NotionSync()
        for r in sync.list_pipeline(limit=500):
            if r.get("id") and r.get("company"):
                company_by_id[r["id"]] = r["company"]
    except Exception as e:
        log.warning("Sweep: pipeline name lookup failed: %s", e)

    for lid, watchers in lead_to_watchers.items():
        company = company_by_id.get(lid) or lid
        try:
            raw = account_news.fetch_for_company(company, limit=15)
            seen = account_news_store.ids_already_seen(lid)
            fresh = [i for i in raw if i["id"] not in seen]
            scored = account_news.score_relevance(fresh, company) if fresh else []
            result = account_news_store.upsert_many(lid, scored)
            summary["leads_scanned"] += 1
            summary["items_added"]   += result["added"]
            # Notify each watcher for each NEW item (not updated).
            for item in result.get("new_items") or []:
                for user in watchers:
                    try:
                        notifications_store.notify_assignment(
                            user,
                            kind="news_alert",
                            title=f"{company}: {item.get('title', '')[:120]}",
                            body=(item.get("why_relevant") or
                                    item.get("snippet") or "")[:240],
                            link={"kind": "lead", "lead_id": lid},
                            actor=None,
                        )
                        summary["notifications_fired"] += 1
                    except Exception as e:
                        summary["errors"].append(
                            f"notify {user} for {lid}: {e}")
            # Bump the high-water mark per watcher.
            for user in watchers:
                try:
                    account_watchlist_store.mark_news_seen(user, lid)
                except Exception:
                    pass
        except Exception as e:
            summary["errors"].append(f"sweep {lid}: {e}")
            log.exception("Sweep error for %s", lid)

    audit.log_event("watchlist_sweep_ran", actor=_actor(),
                    leads_scanned=summary["leads_scanned"],
                    items_added=summary["items_added"],
                    notifications_fired=summary["notifications_fired"])
    return jsonify(summary)


# v1.0.0t: Dashboard endpoint ----------------------------------------------

# v1.0.0aw: per-MR-owner engagement leaderboard ---------------------------
# Rolls up engagement scores by owner so the Dashboard can show who's
# working their book hardest. Manager view of the v1.0.0at score.

@app.route("/api/dashboard/engagement-leaderboard", methods=["GET"])
def api_engagement_leaderboard():
    """Per-owner engagement aggregates.

    Query:
      per_owner_cap — max leads per owner to score (default 30,
                       clamped 1..100). Bounds the I/O fan-out for
                       owners with huge books.

    Returns:
      {
        "rows": [{owner, n_leads, avg_score, strong/warm/weak/cold,
                  needs_attention}],
        "totals": {n_owners, n_leads_scored},
        "generated_at": iso8601,
      }
    """
    from datetime import datetime, timezone
    try:
        per_owner_cap = max(1, min(100,
                                     int(request.args.get("per_owner_cap", "30"))))
    except ValueError:
        per_owner_cap = 30

    # Pull pipeline once; tolerate Notion outages by returning empty.
    try:
        pipeline_rows = NotionSync().list_pipeline(limit=500)
    except Exception as e:
        log.warning("Leaderboard: pipeline fetch failed (continuing): %s", e)
        pipeline_rows = []

    # Group active leads by owner, cap each owner's batch.
    by_owner: dict[str, list[dict]] = {}
    for r in pipeline_rows:
        if (r.get("status") or "") in {"Disqualified", "On Hold", "Closed Lost", "Nurture", "Rejected"}:
            continue
        owner = (r.get("owner") or "").strip() or "Unassigned"
        by_owner.setdefault(owner, []).append(r)

    # Sort each owner's leads by recency so the cap takes the most
    # relevant slice (recent activity = AE's current focus).
    entries: list[dict] = []
    n_scored = 0
    for owner, leads in by_owner.items():
        leads.sort(key=lambda r: r.get("last_edited") or "", reverse=True)
        for r in leads[:per_owner_cap]:
            lid = r.get("id")
            if not lid:
                continue
            try:
                e = _compute_engagement_for_lead(lid)
            except Exception as ex:
                log.warning("Leaderboard score for %s failed: %s", lid, ex)
                continue
            entries.append({
                "owner": owner,
                "score": e.get("score", 0),
                "band":  e.get("band", "cold"),
            })
            n_scored += 1

    rows = engagement.aggregate_by_owner(entries)
    return jsonify({
        "rows":   rows,
        "totals": {
            "n_owners":       len(rows),
            "n_leads_scored": n_scored,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    })


# v1.0.0cc: loss-reason aggregation. After v1.0.0ca introduced the
# Closed Lost flow that captures a `close_reason`, the team needs to
# see the pattern over time — "we keep losing to X" is the kind of
# signal that should drive product / pricing conversations.
#
# The aggregator walks the pipeline (Notion + cache fallback), buckets
# leads with status=Nurture or status=Rejected by their close_reason,
# and returns frequency counts + the most recent lead per bucket.
@app.route("/api/dashboard/loss-reasons", methods=["GET"])
def api_dashboard_loss_reasons():
    """Top close-reasons across recently-closed leads.

    Query:
      limit — max reasons to return (default 10, max 50)

    Returns:
      {
        "reasons": [
          {"reason": "Budget pulled", "count": 4,
           "leads": [{"id": "...", "company": "...", "status": "Nurture",
                       "last_edited": "..."}], }
        ],
        "totals": {"closed_count": 12, "with_reason": 9, "without_reason": 3},
        "generated_at": iso,
      }
    """
    from datetime import datetime, timezone
    try:
        limit = max(1, min(50, int(request.args.get("limit", "10"))))
    except ValueError:
        limit = 10

    # Pull pipeline once; tolerate Notion outages with an empty list.
    try:
        rows = NotionSync().list_pipeline(limit=500)
    except Exception as e:
        log.warning("loss_reasons: pipeline fetch failed: %s", e)
        rows = []

    # Closed leads = Nurture (came from Closed Lost) or Rejected.
    closed_statuses = {"Nurture", "Rejected"}
    closed_rows = [r for r in rows
                    if (r.get("status") or "") in closed_statuses]

    # Each pipeline row exposes `close_reason` via _row_from_page.
    by_reason: dict[str, list[dict]] = {}
    without_reason = 0
    for r in closed_rows:
        reason = (r.get("close_reason") or "").strip()
        if not reason:
            without_reason += 1
            continue
        # Normalise: strip + collapse internal whitespace + lower
        # for the bucket key so "Budget pulled" and "budget pulled"
        # don't fragment. Display the first canonical seen.
        key = " ".join(reason.split()).lower()
        bucket = by_reason.setdefault(key, [])
        bucket.append({
            "id":          r.get("id"),
            "company":     r.get("company"),
            "status":      r.get("status"),
            "owner":       r.get("owner"),
            "last_edited": r.get("last_edited"),
            "reason_text": reason,  # preserves casing
        })

    # Build ranked output. Tie-break by most-recent-edit so a freshly
    # populated bucket surfaces over a stale one of the same size.
    ranked = []
    for key, leads in by_reason.items():
        leads.sort(key=lambda lx: lx.get("last_edited") or "", reverse=True)
        ranked.append({
            "reason":      leads[0]["reason_text"],
            "count":       len(leads),
            "leads":       leads[:5],  # cap per-bucket preview
            "most_recent": leads[0].get("last_edited"),
        })
    ranked.sort(key=lambda x: (-x["count"], -(_iso_to_sortable(x["most_recent"]))))

    return jsonify({
        "reasons": ranked[:limit],
        "totals": {
            "closed_count":   len(closed_rows),
            "with_reason":    sum(len(b) for b in by_reason.values()),
            "without_reason": without_reason,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(
            timespec="seconds").replace("+00:00", "Z"),
    })


def _iso_to_sortable(iso_str: str | None) -> float:
    """Tiny helper for sort-by-recency. Returns 0 for unparseable
    timestamps so they sort last."""
    if not iso_str:
        return 0.0
    try:
        from datetime import datetime as _dt
        return _dt.fromisoformat(str(iso_str).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


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
