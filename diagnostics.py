"""Pre-deploy diagnostics CLI.

    python -m diagnostics            # human-readable report
    python -m diagnostics --json     # machine-readable
    python -m diagnostics --strict   # exit 1 if any REQUIRED integration is broken

Checks performed (each labelled REQUIRED or OPTIONAL):
    - APOLLO_API_KEY present                                   REQUIRED in prod
    - NOTION_API_KEY present                                   REQUIRED
    - NOTION_DATA_SOURCE_ID present                            REQUIRED
    - APP_AUTH_TOKEN present (recommended for Railway)         OPTIONAL
    - ANTHROPIC_API_KEY present                                OPTIONAL
    - SLACK_WEBHOOK_URL present                                OPTIONAL
    - HubSpot enablement state                                 INFO
    - Apollo enrich_organization(deliveroo.co.uk) round-trip   REQUIRED in live mode
    - Notion data source GET                                   REQUIRED if Notion key set
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _check(name: str, required: bool, fn) -> dict[str, Any]:
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, f"exception: {e}"
    return {"name": name, "required": required, "ok": ok, "detail": detail}


def _check_env(var: str) -> tuple[bool, str]:
    v = os.environ.get(var, "").strip()
    return (bool(v), "set" if v else "unset")


def _check_apollo_live() -> tuple[bool, str]:
    """Confirms a real Apollo enrich call works. Skips politely in fixture mode."""
    import apollo
    cfg = apollo.ApolloConfig.from_env()
    if cfg.use_fixtures:
        return True, "fixture mode (skipped live call)"
    try:
        org = apollo.enrich_organization("deliveroo.co.uk", cfg=cfg)
        if org.get("name"):
            return True, f"enriched {org.get('name')} ({org.get('estimated_num_employees') or '?'} emp)"
        return False, "Apollo returned an empty payload"
    except apollo.ApolloError as e:
        return False, str(e)


def _check_notion() -> tuple[bool, str]:
    import notion_sync
    if not os.environ.get("NOTION_API_KEY"):
        return False, "NOTION_API_KEY unset"
    try:
        sync = notion_sync.NotionSync()
        db_id = sync.resolve_database_id()
        return True, f"data source resolved -> database {db_id}"
    except (notion_sync.NotionSyncError, ValueError) as e:
        return False, str(e)


def _check_hubspot_status() -> tuple[bool, str]:
    import hubspot_sync
    s = hubspot_sync.status()
    # "ok" here just means "wired correctly". Disabled by default is the desired state.
    label = "enabled (live writes ON)" if s["enabled"] else "disabled (scaffolding only)"
    return True, label


def run() -> dict:
    checks = [
        _check("APOLLO_API_KEY", True, lambda: _check_env("APOLLO_API_KEY")),
        _check("NOTION_API_KEY", True, lambda: _check_env("NOTION_API_KEY")),
        _check("NOTION_DATA_SOURCE_ID", True, lambda: _check_env("NOTION_DATA_SOURCE_ID")),
        _check("APP_AUTH_TOKEN", False, lambda: _check_env("APP_AUTH_TOKEN")),
        _check("ANTHROPIC_API_KEY", False, lambda: _check_env("ANTHROPIC_API_KEY")),
        _check("SLACK_WEBHOOK_URL", False, lambda: _check_env("SLACK_WEBHOOK_URL")),
        _check("Apollo live round-trip", True, _check_apollo_live),
        _check("Notion data source reachable", True, _check_notion),
        _check("HubSpot scaffolding", False, _check_hubspot_status),
    ]
    required_fail = any(c["required"] and not c["ok"] for c in checks)
    return {"ok": not required_fail, "checks": checks}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Lead Qualification Platform diagnostics")
    p.add_argument("--json", action="store_true", help="emit JSON")
    p.add_argument("--strict", action="store_true", help="exit 1 if any required check fails")
    args = p.parse_args(argv)

    report = run()

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("Lead Qualification Platform diagnostics\n")
        for c in report["checks"]:
            tag = "REQ " if c["required"] else "OPT "
            status_str = "OK " if c["ok"] else "FAIL"
            print(f"  [{tag}] [{status_str}] {c['name']:<32} {c['detail']}")
        print()
        print(f"Overall: {'PASS' if report['ok'] else 'FAIL — required checks broken'}")

    if args.strict and not report["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
