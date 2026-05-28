"""v1.0.0cg — shared primitives for the JSON-file-per-entity stores.

The duplication audit found 22 `*_store.py` files re-implementing the
same 30-line preamble: `_DEFAULT_DIR`, `_LOCK`, `_now()`, `_load_raw`,
`_write_raw`, env-var override on the storage directory. Worse: the
implementations had drifted. Most stores used second-precision
timestamps; `partners_store._now()` used microseconds. That's how
`updated_at` ends up inconsistent across the system.

This module is the single source of truth. Stores import from here
instead of redefining. Per-store concerns (CRUD shape, validation,
side-effects) STAY in the store — only the boring file-system
plumbing lives here.

Public API
----------
    now_iso()                        -> ISO-Z timestamp, second precision
    new_id(short=False)              -> uuid hex
    slugify(value, fallback="...")   -> URL-safe slug
    safe_id(value, error_cls=...)    -> strict ID guard, raises on bad input
    store_dir(name, env_var=None)    -> resolve storage dir (env override)
    load_list(path)                  -> list[dict] or [] on missing/bad json
    load_dict(path)                  -> dict or None on missing/bad json
    write_json(path, data)           -> write with lock + parent.mkdir

Lock semantics
--------------
A single module-level lock guards all writes. The cache files are
small JSON dicts/lists; contention is low and per-store locks were
over-engineering. The lock is reentrant (`RLock`) so a store can
call other helpers from inside a locked section without deadlock.

Migration notes
---------------
A store wanting to migrate replaces the top boilerplate with:

    from json_file_store import (
        now_iso, new_id, slugify, store_dir, load_list, write_json
    )

    _DIR_NAME = "expansion_targets"
    _ENV_VAR  = "EXPANSION_TARGETS_STORE_DIR"

    def _store_dir():
        return store_dir(_DIR_NAME, env_var=_ENV_VAR)

That's it. The store keeps its own `_normalise`, validation, and
CRUD signatures. Tests pinning the existing behaviour will keep
passing.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_BASE = Path(__file__).parent / "cache"
_LOCK = threading.RLock()


class CorruptStoreError(RuntimeError):
    """Raised by `load_list_safe(strict=True)` when a JSON list file
    EXISTS but neither it nor its `.bak` sidecar can be parsed.

    This is the keystone of the note-loss guard (v1.0.0dp). Mutation
    paths (add / update / delete) load strict so that a corrupt or
    transiently-unreadable file ABORTS the write instead of silently
    overwriting recoverable history with a near-empty list. Read paths
    load lenient (return [])."""

# Strict ID guard — UUID hex + URL-safe alphabet. Matches the guard
# v1.0.0bz added to expansion_targets_store / live_projects_store.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def now_iso() -> str:
    """ISO-Z timestamp, second precision. Mirrors what every store
    used to define locally — now centralised so `updated_at` values
    are consistent across the system."""
    return datetime.now(timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def new_id(short: bool = False) -> str:
    """uuid4 hex. `short=True` returns the first 10 chars — fine for
    embedded entities (contacts inside a target, KRs inside an OKR)
    where collision risk is contained."""
    return uuid.uuid4().hex[:10] if short else uuid.uuid4().hex


def slugify(value: str, *, fallback: str = "unknown") -> str:
    """URL-safe slug. `Foo Bar!` -> `foo-bar`. Empty input -> fallback.
    Used for filenames when the entity ID isn't already URL-safe."""
    if not value:
        return fallback
    s = re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")
    return s or fallback


def safe_id(value: str, *, error_cls: type[Exception] = ValueError) -> str:
    """v1.0.0bz security guard, generalised. Rejects any ID outside
    `[A-Za-z0-9_-]{1,64}` — defends against `../etc/passwd`-style
    escapes from any future code path that calls store_dir / _path
    with non-URL input."""
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise error_cls(f"invalid id: {value!r}")
    return value


def store_dir(name: str, *, env_var: str | None = None) -> Path:
    """Resolve the storage directory for a store, with env-var
    override. `cache/<name>` by default; if `env_var` is set in
    the environment, use that path instead.

    Side-effect: ensures the directory exists.
    """
    override = os.environ.get(env_var) if env_var else None
    d = Path(override) if override else _BASE / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_list(path: Path) -> list[dict[str, Any]]:
    """Read a JSON list file. Returns [] on missing / bad JSON /
    non-list payload — never raises. Behaviour deliberately matches
    what every store's `_load_raw` already did."""
    if not path.exists():
        return []
    try:
        with _LOCK:
            data = json.loads(path.read_text())
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def load_dict(path: Path) -> dict[str, Any] | None:
    """Read a JSON dict file. Returns None on missing / bad JSON /
    non-dict payload."""
    if not path.exists():
        return None
    try:
        with _LOCK:
            data = json.loads(path.read_text())
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def write_json(path: Path, data: Any) -> None:
    """Write JSON to `path` with the shared lock held. Ensures the
    parent directory exists. Indented + ensure_ascii=False for
    human-readable output (matches every store's existing format).

    v1.0.0cu: ATOMIC write via tempfile + os.replace. Audit caught that
    a crash mid-write_text() could leave a partially-written JSON file,
    silently truncating data because the load path catches JSONDecodeError
    and returns []. Writing to a sibling tempfile then atomically
    renaming guarantees readers see either the old file or the new one,
    never a half-written one.
    """
    import os
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    with _LOCK:
        # NamedTemporaryFile in the SAME directory as the target so the
        # os.replace is on the same filesystem (atomicity requirement
        # on Linux). delete=False so we can rename it ourselves.
        fd, tmp_name = tempfile.mkstemp(
            prefix=path.name + ".",
            suffix=".tmp",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    # fsync can fail on some pseudo-filesystems
                    # (tmpfs in containers); a best-effort flush is
                    # still better than no flush.
                    pass
            os.replace(tmp_name, path)
        except Exception:
            # If anything goes wrong, clean up the tempfile so we don't
            # leave litter behind.
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise


# ---------------------------------------------------------------------------
# v1.0.0dp — note-loss guard
#
# v1.0.0cu made every store's write ATOMIC (tempfile + os.replace), which
# stops a crash mid-write from *creating* a half-written file. It did NOT
# close the matching read-side hole: `load_list` returns [] on a file that
# exists but can't be parsed, so the very next add / delete loads [],
# appends to it, and writes it back -- permanently destroying notes that
# were recoverable a moment earlier.
#
# These helpers shut that path: a `.bak` sidecar preserves the prior good
# state on every write, and `load_list_safe` distinguishes "missing"
# (legitimately empty) from "corrupt" (recover from .bak, or refuse to
# overwrite under strict mode). Used by the notes / calls stores, which
# hold human-authored history with no other source of truth.
# ---------------------------------------------------------------------------

def _bak_path(path: Path) -> Path:
    """Sidecar backup path: `foo.json` -> `foo.json.bak`. The `.bak`
    suffix means it is never matched by the `glob('*.json')` /
    `endswith('.json')` consumers elsewhere in the codebase."""
    return path.with_name(path.name + ".bak")


def _try_parse_list(path: Path) -> list[dict[str, Any]] | None:
    """Parse `path` as a JSON list. Returns the list, an empty list for
    an empty file, or None when the file is missing / unreadable / not a
    JSON list. None is the explicit 'cannot trust this file' signal."""
    if not path.exists():
        return None
    try:
        with _LOCK:
            text = path.read_text()
    except OSError:
        return None
    if not text.strip():
        return []
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, list) else None


def load_list_safe(path: Path, *, strict: bool = False) -> list[dict[str, Any]]:
    """Corruption-aware list loader that guards against silent data loss.

    Behaviour by case:
      - primary parses as a list   -> return it
      - primary genuinely absent   -> return [] (never written, or an
                                       intentional delete; we do NOT
                                       resurrect from .bak so cascade
                                       deletes stay deleted)
      - primary EXISTS but corrupt -> recover from the `.bak` sidecar if
                                       that parses; otherwise:
                                         strict=True  -> raise CorruptStoreError
                                         strict=False -> return []

    Mutation paths pass strict=True so they refuse to overwrite a file
    they could not read. Read paths pass strict=False and degrade to [].
    """
    primary = _try_parse_list(path)
    if primary is not None:
        return primary
    if not path.exists():
        # Genuinely absent -- not corrupt. Empty store.
        return []
    # Primary exists but is unparseable -> fall back to the sidecar.
    backup = _try_parse_list(_bak_path(path))
    if backup is not None:
        return backup
    if strict:
        raise CorruptStoreError(
            f"{path.name}: file and .bak sidecar are both unreadable; "
            "refusing to overwrite to avoid destroying existing data")
    return []


def write_json_backup(path: Path, data: Any) -> None:
    """Atomic write (see `write_json`) that first preserves the prior
    file contents as a `.bak` sidecar, so a wrong write, a logic bug, or
    an accidental wipe is recoverable.

    Only a READABLE prior file is snapshotted -- we never overwrite a
    good `.bak` with a corrupt primary, so the last known-good state
    survives even across a corruption event."""
    with _LOCK:
        if _try_parse_list(path) is not None:
            try:
                shutil.copy2(path, _bak_path(path))
            except OSError:
                pass
        write_json(path, data)


def backup_file(path: Path) -> bool:
    """Snapshot `path` to its `.bak` sidecar before a destructive op
    (e.g. a cascade delete). Returns True if a backup was written. Only
    backs up a file that exists and parses as a JSON list, so a corrupt
    file never clobbers a good sidecar."""
    with _LOCK:
        if _try_parse_list(path) is None:
            return False
        try:
            shutil.copy2(path, _bak_path(path))
            return True
        except OSError:
            return False
