#!/usr/bin/env python3
"""v1.0.0dm — CLI entry point for the scheduled agents.

Run from cron / a Railway scheduled job. Examples:

    # Run whatever is due today (matches the job's weekday):
    python run_scheduled.py --today

    # Run one job explicitly:
    python run_scheduled.py monday_pipeline_digest

    # Run everything (manual / catch-up):
    python run_scheduled.py --all

    # Just list the jobs and their cadence:
    python run_scheduled.py --list

A typical Railway setup is three weekly cron jobs that each call
`python run_scheduled.py --today`; whichever job's weekday matches runs.
Or schedule one per day and let `--today` be a no-op on the others.

Exit code is 0 if every job that ran reported ok, 1 otherwise — so a
cron wrapper can alert on failure.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

import scheduled_agents


def _print_record(rec: dict) -> None:
    status = "ok" if rec.get("ok") else "FAILED"
    print(f"[{status}] {rec.get('job')} ({rec.get('kind')}) "
          f"at {rec.get('ran_at')}")
    msg = (rec.get("message") or "").strip()
    if msg:
        # Indent the body so multi-job output stays readable.
        for line in msg.splitlines():
            print(f"    {line}")
    steps = rec.get("steps") or []
    if steps:
        tools = ", ".join(s.get("tool", "?") for s in steps)
        print(f"    (tools: {tools})")
    print()


def _run_keys(keys: list[str]) -> int:
    if not keys:
        print("Nothing to run.")
        return 0
    all_ok = True
    for key in keys:
        rec = scheduled_agents.run_job(key, actor="cron")
        if rec.get("error"):
            print(f"[ERROR] {key}: {rec['error']}")
            all_ok = False
            continue
        _print_record(rec)
        all_ok = all_ok and bool(rec.get("ok"))
    return 0 if all_ok else 1


def main(argv: list[str]) -> int:
    arg = (argv[0] if argv else "--today").strip()

    if arg in ("--list", "-l"):
        for j in scheduled_agents.list_jobs():
            lr = j.get("last_run") or {}
            when = lr.get("ran_at", "never")
            print(f"{j['key']:<28} {j['cadence']:<16} {j['kind']:<7} "
                  f"last: {when}")
        return 0

    if arg in ("--all", "-a"):
        keys = [j["key"] for j in scheduled_agents.list_jobs()]
        return _run_keys(keys)

    if arg in ("--today", "-t"):
        weekday = datetime.now(timezone.utc).weekday()  # 0=Mon..6=Sun
        jobs = scheduled_agents.jobs_for_weekday(weekday)
        if not jobs:
            print(f"No jobs scheduled for weekday {weekday}.")
            return 0
        return _run_keys([j.key for j in jobs])

    # Otherwise treat the argument(s) as explicit job keys.
    return _run_keys([a for a in argv if not a.startswith("-")])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
