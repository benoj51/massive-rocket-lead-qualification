"""
Account group relationships (v0.10.0 Phase A).

Models the parent → brand relationship for B2B realities like Yum! Brands →
[KFC, Pizza Hut, Taco Bell, Habit Burger]. One level deep on purpose —
Corp → Division → Brand is real but rare; we'll add it only if it bites.

Storage: a single JSON file at cache/accounts_graph.json containing one
big dict `{lead_id: parent_account_id}`. Small (one row per linked
brand), trivial to read/write, no schema migrations.

Why a single file and not per-lead like the other stores?
- The graph is small (max a few hundred entries in a real pipeline).
- Children-of-parent queries are O(n) on the whole file — fine at this
  scale, much simpler than a sibling index.
- A single file makes cycle/self-ref detection a one-shot in-memory check.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

import project_store

_DEFAULT_PATH = Path(__file__).parent / "cache" / "accounts_graph.json"
_LOCK = threading.Lock()


def _path() -> Path:
    override = os.environ.get("ACCOUNTS_GRAPH_PATH")
    p = Path(override) if override else _DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load() -> dict[str, str]:
    p = _path()
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text())
        # Only keep string→string entries (defensive against hand edits).
        return {str(k): str(v) for k, v in raw.items() if v}
    except (json.JSONDecodeError, OSError):
        return {}


def _write(data: dict[str, str]) -> None:
    _path().write_text(json.dumps(data, indent=2, sort_keys=True))


def _norm(lead_id: str) -> str:
    """Canonical lead identifier — slug of whatever the caller passes."""
    return project_store.slugify(lead_id)


# ---------- read ----------

def parent_of(lead_id: str) -> str | None:
    """Return the parent_account_id (slug) for this lead, or None if standalone."""
    with _LOCK:
        return _load().get(_norm(lead_id))


def children_of(parent_id: str) -> list[str]:
    """Return all lead_ids that have parent_id as their parent."""
    pid = _norm(parent_id)
    with _LOCK:
        data = _load()
    return sorted([k for k, v in data.items() if v == pid])


def full_graph() -> dict[str, str]:
    """Return the entire {child: parent} map."""
    with _LOCK:
        return _load()


def is_parent(lead_id: str) -> bool:
    """True iff at least one other lead points to this one as parent."""
    pid = _norm(lead_id)
    with _LOCK:
        data = _load()
    return any(v == pid for v in data.values())


# ---------- write ----------

class GraphError(ValueError):
    """Raised when a set_parent call would violate a graph invariant."""


def set_parent(lead_id: str, parent_id: str | None) -> dict[str, Any]:
    """Set or clear the parent for a lead.

    Validates:
      - no self-reference (A → A)
      - no cycle (A → B → A; we're one-level only, so the simple rule is:
        a lead that already has children cannot itself be made a child)
      - parent_id is non-empty if provided

    Returns {"lead_id": str, "parent_account_id": str | None}.
    Raises GraphError on violation.
    """
    child = _norm(lead_id)
    with _LOCK:
        data = _load()
        if parent_id is None or str(parent_id).strip() == "":
            # Unlink.
            data.pop(child, None)
            _write(data)
            return {"lead_id": child, "parent_account_id": None}

        parent = _norm(parent_id)
        if parent == child:
            raise GraphError("An account cannot be its own parent.")
        # A lead that has children cannot become a child itself (one-level rule).
        if any(v == child for v in data.values()):
            raise GraphError(
                "This account is already a parent group. "
                "Unlink its brands first, or pick a different parent."
            )
        # Apply.
        data[child] = parent
        _write(data)
        return {"lead_id": child, "parent_account_id": parent}


def can_delete(lead_id: str) -> tuple[bool, list[str]]:
    """Phase A delete-guard: returns (ok, children_blocking_delete).

    A parent with children cannot be deleted until its children are
    unlinked or reassigned. Returns the list of child lead_ids that
    would be orphaned so the caller can show a clear error.
    """
    kids = children_of(lead_id)
    return (len(kids) == 0, kids)


def unlink_all_children(parent_id: str) -> list[str]:
    """Clear the parent link on every child of this account.

    Used when the AE confirms 'unlink brands and delete'. Returns the
    list of lead_ids that were unlinked.
    """
    pid = _norm(parent_id)
    with _LOCK:
        data = _load()
        unlinked = [k for k, v in data.items() if v == pid]
        for k in unlinked:
            data.pop(k, None)
        _write(data)
    return unlinked
