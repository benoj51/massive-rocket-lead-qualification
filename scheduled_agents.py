"""v1.0.0dm — scheduled agents (cron-style recurring jobs).

The CRM gap analysis (step 5) called for scheduled agents: recurring
jobs that run a persona on a cadence and leave their output where the
team can read it. This module is that scheduler's logic — the WHAT and
the HOW of each job. The WHEN is delegated to whatever cron / Railway
scheduled-job runs `run_scheduled.py` (or hits the run endpoint).

Three jobs, mirroring the gap analysis:

  - monday_pipeline_digest   — Pipeline Analyst persona writes the weekly
                               pipeline-health + target-attainment digest.
  - wednesday_news_sweep     — runs the watchlist news sweep (reuses
                               watchlist_sweep.run_sweep; no LLM needed).
  - friday_stale_stakeholders— Partner Relationship Coach lists partner
                               contacts who are overdue / under-covered.

Each run is persisted (latest run per job, under cache/scheduled_runs/)
so the UI can show "here's last Monday's digest" and an audit event is
written. Agent jobs carry the same `steps` audit trace as interactive
agent turns.

Public API
----------
list_jobs()                       -> list[dict]   # defs + last run
get_job(key)                      -> JobDef | None
jobs_for_weekday(weekday)         -> list[JobDef] # weekday 0=Mon..6=Sun
run_job(key, *, actor="scheduler")-> dict         # runs + persists
latest_run(key)                   -> dict | None
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from json_file_store import (
    load_dict,
    now_iso,
    safe_id,
    store_dir,
    write_json,
)

log = logging.getLogger(__name__)

_RUNS_DIR_NAME = "scheduled_runs"
_RUNS_ENV_VAR = "SCHEDULED_RUNS_STORE_DIR"


@dataclass(frozen=True)
class JobDef:
    key: str
    label: str
    description: str
    cadence: str            # human-readable, e.g. "Monday 08:00"
    weekday: int            # 0=Mon .. 6=Sun (used by the CLI day matcher)
    kind: str               # "agent" | "sweep"
    persona: str | None = None   # for kind == "agent"
    prompt: str | None = None    # seed user message for kind == "agent"


# ---------------------------------------------------------------------
# Job registry
# ---------------------------------------------------------------------

_JOBS: dict[str, JobDef] = {}


def _register(j: JobDef) -> None:
    _JOBS[j.key] = j


_register(JobDef(
    key="monday_pipeline_digest",
    label="Monday pipeline digest",
    description="Weekly pipeline-health and quarterly-attainment digest "
                "for the sales manager.",
    cadence="Monday 08:00",
    weekday=0,
    kind="agent",
    persona="pipeline_analyst",
    prompt=(
        "It's Monday. Produce this week's pipeline digest for the sales "
        "manager. Cover: how the pipeline looks right now (counts by "
        "stage and any notable movements), where we stand against the "
        "current quarter's targets, and the 2-3 accounts most worth "
        "attention this week. Use the tools to ground every number. Keep "
        "it skimmable: short headings and bullets."
    ),
))

_register(JobDef(
    key="wednesday_news_sweep",
    label="Wednesday news sweep",
    description="Fetches and scores fresh news for every watched account, "
                "then alerts the watchers.",
    cadence="Wednesday 07:00",
    weekday=2,
    kind="sweep",
))

_register(JobDef(
    key="friday_stale_stakeholders",
    label="Friday stale-stakeholder list",
    description="Lists partner stakeholders who are overdue for a touch or "
                "where coverage is thin, prioritised by tier.",
    cadence="Friday 16:00",
    weekday=4,
    kind="agent",
    persona="partner_coach",
    prompt=(
        "It's Friday. Produce the weekly stale-stakeholder list for the "
        "partnerships team. Use get_stakeholder_coverage and "
        "get_overdue_contacts to find partner contacts who are overdue for "
        "a touch or where coverage is thin. Prioritise by tier and how "
        "long it has been since the last contact. For the top few, suggest "
        "one concrete next step each. Do not draft full outreach unless "
        "asked."
    ),
))


def get_job(key: str) -> JobDef | None:
    return _JOBS.get((key or "").strip())


def jobs_for_weekday(weekday: int) -> list[JobDef]:
    """Jobs scheduled to run on the given weekday (0=Mon .. 6=Sun)."""
    return [j for j in _JOBS.values() if j.weekday == weekday]


# ---------------------------------------------------------------------
# Run persistence (latest run per job)
# ---------------------------------------------------------------------

def _runs_dir():
    return store_dir(_RUNS_DIR_NAME, env_var=_RUNS_ENV_VAR)


def _run_path(key: str):
    return _runs_dir() / f"{safe_id(key)}.json"


def latest_run(key: str) -> dict[str, Any] | None:
    """The most recent persisted run for a job, or None."""
    try:
        return load_dict(_run_path(key))
    except (ValueError, OSError):
        return None


def _save_run(record: dict[str, Any]) -> None:
    try:
        write_json(_run_path(record["job"]), record)
    except (ValueError, OSError) as e:
        log.warning("could not persist scheduled run %s: %s",
                    record.get("job"), e)


# ---------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------

def _run_agent_job(job: JobDef) -> dict[str, Any]:
    """Run an agent-backed job. Returns (ok, message, steps, error)."""
    import agent
    if not agent.is_configured():
        return {
            "ok": False,
            "message": "Agent is offline: ANTHROPIC_API_KEY is not set.",
            "steps": [],
            "error_code": "agent_disabled",
        }
    result = agent.run_agent(
        job.persona,
        [{"role": "user", "content": job.prompt or ""}],
        max_steps=6,
    )
    if result.get("error"):
        return {
            "ok": False,
            "message": result.get("error") or "Agent run failed.",
            "steps": result.get("steps") or [],
            "error_code": result.get("code"),
        }
    return {
        "ok": True,
        "message": result.get("message") or "",
        "steps": result.get("steps") or [],
        "stopped": result.get("stopped"),
    }


def _run_sweep_job(job: JobDef) -> dict[str, Any]:
    """Run the watchlist news sweep. No LLM involved."""
    import watchlist_sweep
    summary = watchlist_sweep.run_sweep()
    scanned = summary.get("leads_scanned", 0)
    added = summary.get("items_added", 0)
    fired = summary.get("notifications_fired", 0)
    msg = (f"Swept {scanned} watched "
           f"{'account' if scanned == 1 else 'accounts'}: "
           f"{added} new news {'item' if added == 1 else 'items'}, "
           f"{fired} {'alert' if fired == 1 else 'alerts'} sent.")
    if summary.get("errors"):
        msg += f" {len(summary['errors'])} error(s) — see data.errors."
    return {
        "ok": not summary.get("errors"),
        "message": msg,
        "steps": [],
        "data": summary,
    }


def run_job(key: str, *, actor: str = "scheduler") -> dict[str, Any]:
    """Run one job now, persist its latest result, and audit it.

    Returns the run record:
      {job, label, kind, ran_at, ok, message, steps, data?, actor,
       error_code?}
    On an unknown job: {"error", "code": "unknown_job"}.
    """
    job = get_job(key)
    if not job:
        return {"error": f"unknown scheduled job: {key}",
                "code": "unknown_job"}

    if job.kind == "agent":
        outcome = _run_agent_job(job)
    elif job.kind == "sweep":
        outcome = _run_sweep_job(job)
    else:  # pragma: no cover - registry is closed
        return {"error": f"unknown job kind: {job.kind}",
                "code": "unknown_kind"}

    record: dict[str, Any] = {
        "job": job.key,
        "label": job.label,
        "kind": job.kind,
        "ran_at": now_iso(),
        "actor": actor,
        "ok": bool(outcome.get("ok")),
        "message": outcome.get("message") or "",
        "steps": outcome.get("steps") or [],
    }
    if "data" in outcome:
        record["data"] = outcome["data"]
    if outcome.get("error_code"):
        record["error_code"] = outcome["error_code"]

    _save_run(record)

    try:
        import audit
        audit.log_event(
            "scheduled_job_ran",
            actor=actor,
            job=job.key,
            kind=job.kind,
            ok=record["ok"],
            steps=len(record["steps"]),
            tools=",".join(s.get("tool", "") for s in record["steps"])[:200],
        )
    except Exception:  # noqa: BLE001 - logging must never break a run
        pass

    return record


def list_jobs() -> list[dict[str, Any]]:
    """Job definitions plus the latest run for each (for the UI)."""
    out: list[dict[str, Any]] = []
    for j in _JOBS.values():
        out.append({
            "key": j.key,
            "label": j.label,
            "description": j.description,
            "cadence": j.cadence,
            "weekday": j.weekday,
            "kind": j.kind,
            "persona": j.persona,
            "last_run": latest_run(j.key),
        })
    return out
