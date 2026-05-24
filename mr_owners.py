"""
Massive Rocket owners (v1.0.0o → v1.0.0bq).

This module used to own the canonical hard-coded list of MR
teammates. As of v1.0.0bq the list lives in `mr_owners_store.py`
(writable JSON) and this module is a thin backward-compat shim.

Why keep the shim
-----------------
Half a dozen modules import `mr_owners.list_owners` /
`mr_owners.get_owner` / `mr_owners.names`. Forcing every caller
to migrate at once would have been noisy + risky. The shim
re-exports those three functions verbatim so downstream code
doesn't notice the move.

Edit/add/remove
---------------
Use the Settings → Users surface in the UI, or hit the
`/api/settings/users` CRUD endpoints. The hard-coded SEED_OWNERS
list (in `mr_owners_store.py`) only fires once, on first read,
when no persisted file exists.
"""
from __future__ import annotations

from typing import Any

# v1.0.0bq: delegate everything to the writable store. The SEED_OWNERS
# constant there mirrors the v1.0.0o list verbatim so first-run
# experience is unchanged.
from mr_owners_store import (  # noqa: F401  (re-exports are intentional)
    list_owners,
    get_owner,
    names,
    SEED_OWNERS,
)

# v1.0.0o-era constant: kept as an alias for any code that imports
# `mr_owners.OWNERS` directly. Reads from the store, not from a
# frozen list. If a caller mutates OWNERS in-place (none should,
# but the old API allowed it) they'll get a fresh list each time —
# safer than letting them silently mutate seed data.
def _owners_proxy() -> list[dict[str, Any]]:
    return list_owners(active_only=False)


# Module-level attribute that behaves like a list for the common
# `for o in mr_owners.OWNERS` pattern. Materialises on import so
# scripts that took a snapshot still work.
OWNERS = _owners_proxy()
