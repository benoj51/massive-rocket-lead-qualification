"""Shared pytest setup.

v1.0.0do: the new in-process rate limiter (rate_limit.py) is on by
default in production, but its counters are module-global and the whole
test suite runs inside one 60-second wall-clock window. Left enabled,
the many endpoint tests that call the LLM / sweep routes would exhaust
the shared bucket and trip 429s on later tests.

Disable it globally for the suite by setting the limits to 0 BEFORE any
test module imports `server`. The dedicated test_rate_limit.py re-enables
it per-case by setting the env vars and calling rate_limit.reset().
"""
import os

os.environ.setdefault("RATE_LIMIT_LLM_PER_MIN", "0")
os.environ.setdefault("RATE_LIMIT_SWEEP_PER_MIN", "0")
