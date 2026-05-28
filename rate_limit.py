"""v1.0.0do — lightweight, dependency-free in-process rate limiter.

The security review flagged that the cost-bearing endpoints (anything
that calls Anthropic, plus the watchlist news sweep) had no throttle.
With a single shared auth token, one holder, a leaked token, or a
runaway client loop could rack up unbounded Anthropic spend and hammer
the outbound RSS fetch. This module bounds that.

Why not flask-limiter: this is a single-instance Railway deploy with a
handful of users. A 40-line fixed-window counter keyed by client IP is
enough, avoids a new dependency to pin / audit, and is fully
deterministic to test (no storage backend, no network).

Design
------
- Fixed-window counter per (scope, client-key). Client key is the first
  X-Forwarded-For hop (Railway sets it) falling back to remote_addr.
- Limits are read from the environment at call time, so ops can tune
  them without a redeploy, and tests can set them per-case. A limit of
  0 (or negative) disables the check for that scope.
- The decorator returns HTTP 429 + Retry-After when the window is full;
  otherwise it calls through to the handler unchanged.
- @app.route must stay the OUTERMOST decorator (above the rate-limit
  decorator) so Flask registers the wrapped view.

Public API
----------
rate_limit(env_var, default, *, window_s=60.0, scope="") -> decorator
llm()    -> decorator   # shared bucket for all LLM-calling endpoints
sweep()  -> decorator   # the watchlist news sweep
reset()                 -> None    # clear all counters (tests)
"""
from __future__ import annotations

import os
import threading
import time
from functools import wraps

from flask import jsonify, request

# Defaults are deliberately generous: the goal is to bound a runaway
# loop or abuse, not to police normal team usage. Ops can lower these
# via the env vars below.
_LLM_ENV = "RATE_LIMIT_LLM_PER_MIN"
_LLM_DEFAULT = 60
_SWEEP_ENV = "RATE_LIMIT_SWEEP_PER_MIN"
_SWEEP_DEFAULT = 12

_LOCK = threading.Lock()
# (scope:client-key) -> list[monotonic timestamps within the window]
_HITS: dict[str, list[float]] = {}


def reset() -> None:
    """Clear all counters. For tests that assert window behaviour."""
    with _LOCK:
        _HITS.clear()


def _limit_from_env(env_var: str, default: int) -> int:
    raw = os.environ.get(env_var)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _client_key() -> str:
    """Best-effort caller identity for bucketing. Prefer the first
    X-Forwarded-For hop (Railway / proxies set it); fall back to the
    socket peer. Tolerates being called outside a request context."""
    try:
        xff = request.headers.get("X-Forwarded-For", "")
        if xff:
            return xff.split(",")[0].strip() or "unknown"
        return request.remote_addr or "unknown"
    except RuntimeError:
        return "unknown"


def _check(key: str, limit: int, window_s: float) -> tuple[bool, float]:
    """Record a hit against `key`. Returns (allowed, retry_after_s).

    Fixed window: keep only timestamps newer than (now - window_s); if
    that count is already at the limit, reject and report how long until
    the oldest hit ages out.
    """
    now = time.monotonic()
    cutoff = now - window_s
    with _LOCK:
        hits = [t for t in _HITS.get(key, ()) if t > cutoff]
        if len(hits) >= limit:
            _HITS[key] = hits
            retry = window_s - (now - hits[0])
            return False, max(0.0, retry)
        hits.append(now)
        _HITS[key] = hits
        return True, 0.0


def rate_limit(env_var: str, default: int, *,
               window_s: float = 60.0, scope: str = ""):
    """Decorator factory. Throttle a Flask view to `limit` requests per
    `window_s` seconds per client, where `limit` comes from `env_var`
    (falling back to `default`; 0 disables). Views sharing a `scope`
    share one bucket per client."""
    def deco(fn):
        bucket = scope or fn.__name__

        @wraps(fn)
        def wrapper(*args, **kwargs):
            limit = _limit_from_env(env_var, default)
            if limit <= 0:
                return fn(*args, **kwargs)  # disabled
            allowed, retry = _check(f"{bucket}:{_client_key()}",
                                    limit, window_s)
            if not allowed:
                resp = jsonify({
                    "error": "Rate limit exceeded. Slow down and retry shortly.",
                    "code": "rate_limited",
                })
                resp.status_code = 429
                resp.headers["Retry-After"] = str(int(retry) + 1)
                return resp
            return fn(*args, **kwargs)
        return wrapper
    return deco


def llm():
    """Shared bucket for every endpoint that calls Anthropic. One
    runaway client can't burn unbounded tokens across qualify / extract
    / summary / agent / Jeff combined."""
    return rate_limit(_LLM_ENV, _LLM_DEFAULT, scope="llm")


def sweep():
    """The watchlist news sweep (outbound RSS + optional scoring)."""
    return rate_limit(_SWEEP_ENV, _SWEEP_DEFAULT, scope="sweep")
