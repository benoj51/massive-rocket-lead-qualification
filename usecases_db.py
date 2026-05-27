"""Use-cases catalog read layer (v1.0.0dg).

Reads from Ben's separate Django app's Postgres DB. That app owns
the catalog_* tables (industry / platform / featurearea / usecase /
agent / generatedasset). We connect read-only by default and pull
use cases to surface inside this platform (lead drawer card,
Project Build matched picks, briefs).

Schema reference (Django-generated tables):
- catalog_industry        (id, name, slug)
- catalog_platform        (id, name, slug)
- catalog_featurearea     (id, name, slug, platform_id)
- catalog_usecase         (id, title, slug, client_name,
                            client_industry_id, is_anonymised,
                            problem, solution, outcome,
                            metrics JSONB, delivered_at, status, ...)
- catalog_usecase_platforms       (usecase_id, platform_id)
- catalog_usecase_feature_areas   (usecase_id, featurearea_id)
- catalog_agent           (id, name, slug, category, description, ...)
- catalog_usecase_agents_used     (usecase_id, agent_id)
- catalog_generatedasset  (id, title, prospect_industry,
                           prospect_platforms, angle,
                           output_markdown, output_email, ...)

Environment
-----------
DATABASE_URL_USECASES  - psycopg-style DSN, e.g.
    postgres://user:pw@host:5432/dbname

When unset, the module's `is_configured()` returns False; all
queries return empty lists / None so the UI degrades gracefully.

Connection model
----------------
Single global connection pool (psycopg_pool). Cheap reads, the
hot path is the lead drawer + Project Build cards.
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)

_pool = None
_POOL_INIT_TRIED = False


def is_configured() -> bool:
    """True when DATABASE_URL_USECASES is set + non-empty."""
    return bool((os.environ.get("DATABASE_URL_USECASES") or "").strip())


def _get_pool():
    """Lazy-init a connection pool. Returns None when not configured
    or when psycopg isn't importable (so callers can degrade)."""
    global _pool, _POOL_INIT_TRIED
    if _pool is not None:
        return _pool
    if _POOL_INIT_TRIED:
        return None
    _POOL_INIT_TRIED = True
    if not is_configured():
        return None
    try:
        from psycopg_pool import ConnectionPool
    except ImportError:
        log.warning("psycopg_pool not installed; use-cases catalog disabled")
        return None
    try:
        dsn = os.environ["DATABASE_URL_USECASES"].strip()
        # Railway sometimes hands out postgres:// instead of postgresql://;
        # psycopg 3 normalises but be explicit.
        if dsn.startswith("postgres://"):
            dsn = "postgresql://" + dsn[len("postgres://"):]
        _pool = ConnectionPool(
            conninfo=dsn,
            min_size=1,
            max_size=5,
            open=False,
            kwargs={"autocommit": True},
        )
        _pool.open()
    except Exception as e:
        log.warning("Use-cases DB pool init failed: %s", e)
        _pool = None
    return _pool


def _row_to_dict(cursor, row) -> dict[str, Any]:
    """psycopg3 returns tuples by default; build a dict from cursor.description."""
    if row is None:
        return {}
    cols = [d.name for d in cursor.description]
    return dict(zip(cols, row))


# ---------------------------------------------------------------------
# Public queries
# ---------------------------------------------------------------------

def healthcheck() -> dict[str, Any]:
    """Lightweight diagnostic for /api/health."""
    if not is_configured():
        return {"configured": False, "reachable": False,
                 "reason": "DATABASE_URL_USECASES not set"}
    pool = _get_pool()
    if pool is None:
        return {"configured": True, "reachable": False,
                 "reason": "pool init failed"}
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return {"configured": True, "reachable": True}
    except Exception as e:
        return {"configured": True, "reachable": False, "reason": str(e)}


def list_industries() -> list[dict[str, Any]]:
    pool = _get_pool()
    if pool is None:
        return []
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, name, slug FROM catalog_industry "
                             "ORDER BY name")
                return [_row_to_dict(cur, r) for r in cur.fetchall()]
    except Exception as e:
        log.warning("list_industries failed: %s", e)
        return []


def list_platforms() -> list[dict[str, Any]]:
    pool = _get_pool()
    if pool is None:
        return []
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, name, slug FROM catalog_platform "
                             "ORDER BY name")
                return [_row_to_dict(cur, r) for r in cur.fetchall()]
    except Exception as e:
        log.warning("list_platforms failed: %s", e)
        return []


def list_use_cases(*, industry_slug: str | None = None,
                    platform_slug: str | None = None,
                    status: str = "published",
                    limit: int = 100) -> list[dict[str, Any]]:
    """List use cases with optional filters. Status defaults to
    'published' so the lead-facing surfaces don't leak drafts."""
    pool = _get_pool()
    if pool is None:
        return []
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                # Base query with joins for industry name + concatenated
                # platforms / feature areas.
                sql = """
                    SELECT
                      u.id, u.title, u.slug,
                      u.client_name, u.is_anonymised,
                      u.problem, u.solution, u.outcome,
                      u.metrics, u.delivered_at, u.status,
                      i.name AS industry_name, i.slug AS industry_slug,
                      COALESCE(
                        ARRAY(
                          SELECT p.slug FROM catalog_usecase_platforms up
                          JOIN catalog_platform p ON p.id = up.platform_id
                          WHERE up.usecase_id = u.id
                        ), ARRAY[]::varchar[]
                      ) AS platform_slugs,
                      COALESCE(
                        ARRAY(
                          SELECT fa.slug FROM catalog_usecase_feature_areas uf
                          JOIN catalog_featurearea fa ON fa.id = uf.featurearea_id
                          WHERE uf.usecase_id = u.id
                        ), ARRAY[]::varchar[]
                      ) AS feature_area_slugs
                    FROM catalog_usecase u
                    LEFT JOIN catalog_industry i ON i.id = u.client_industry_id
                    WHERE u.status = %s
                """
                params: list[Any] = [status]
                if industry_slug:
                    sql += " AND i.slug = %s"
                    params.append(industry_slug)
                if platform_slug:
                    sql += (
                        " AND EXISTS ("
                        "  SELECT 1 FROM catalog_usecase_platforms up2 "
                        "  JOIN catalog_platform p2 ON p2.id = up2.platform_id "
                        "  WHERE up2.usecase_id = u.id AND p2.slug = %s"
                        ")"
                    )
                    params.append(platform_slug)
                sql += " ORDER BY u.delivered_at DESC NULLS LAST, u.updated_at DESC LIMIT %s"
                params.append(int(limit))
                cur.execute(sql, params)
                return [_row_to_dict(cur, r) for r in cur.fetchall()]
    except Exception as e:
        log.warning("list_use_cases failed: %s", e)
        return []


def get_use_case(use_case_id: int) -> dict[str, Any] | None:
    pool = _get_pool()
    if pool is None:
        return None
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                      u.id, u.title, u.slug,
                      u.client_name, u.is_anonymised,
                      u.problem, u.solution, u.outcome,
                      u.metrics, u.delivered_at, u.status,
                      u.source_doc, u.source_text,
                      i.name AS industry_name, i.slug AS industry_slug,
                      COALESCE(
                        ARRAY(
                          SELECT p.slug FROM catalog_usecase_platforms up
                          JOIN catalog_platform p ON p.id = up.platform_id
                          WHERE up.usecase_id = u.id
                        ), ARRAY[]::varchar[]
                      ) AS platform_slugs,
                      COALESCE(
                        ARRAY(
                          SELECT fa.slug FROM catalog_usecase_feature_areas uf
                          JOIN catalog_featurearea fa ON fa.id = uf.featurearea_id
                          WHERE uf.usecase_id = u.id
                        ), ARRAY[]::varchar[]
                      ) AS feature_area_slugs,
                      COALESCE(
                        ARRAY(
                          SELECT a.slug FROM catalog_usecase_agents_used ua
                          JOIN catalog_agent a ON a.id = ua.agent_id
                          WHERE ua.usecase_id = u.id
                        ), ARRAY[]::varchar[]
                      ) AS agent_slugs
                    FROM catalog_usecase u
                    LEFT JOIN catalog_industry i ON i.id = u.client_industry_id
                    WHERE u.id = %s
                """, (int(use_case_id),))
                row = cur.fetchone()
                return _row_to_dict(cur, row) if row else None
    except Exception as e:
        log.warning("get_use_case(%s) failed: %s", use_case_id, e)
        return None


def match_for_lead(*, industry: str | None = None,
                    tech_stack: list[str] | None = None,
                    limit: int = 6) -> list[dict[str, Any]]:
    """Find use cases that look relevant for a given lead.

    Match rules (best-effort - cumulative score):
    - +3 points if catalog_industry.slug matches the lead's industry
      (or .name does case-insensitively)
    - +2 points per platform_slug that appears in the lead's
      tech_stack (or vice versa)
    - filtered to status='published'
    - ordered by score desc, then delivered_at desc

    Returns at most `limit` use cases with a 'match_score' field.
    """
    pool = _get_pool()
    if pool is None:
        return []

    # Normalise inputs
    industry_norm = (industry or "").strip().lower()
    stack_norm = {(t or "").strip().lower() for t in (tech_stack or []) if (t or "").strip()}

    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                # Pull a wide-ish window of published use cases (the
                # taxonomy is small enough to filter in Python; the DB
                # call avoids a fragile SQL-side fuzzy match).
                cur.execute("""
                    SELECT
                      u.id, u.title, u.slug,
                      u.client_name, u.is_anonymised, u.outcome,
                      u.metrics, u.delivered_at,
                      LOWER(COALESCE(i.name, '')) AS industry_name_lc,
                      LOWER(COALESCE(i.slug, '')) AS industry_slug_lc,
                      COALESCE(
                        ARRAY(
                          SELECT LOWER(p.slug) FROM catalog_usecase_platforms up
                          JOIN catalog_platform p ON p.id = up.platform_id
                          WHERE up.usecase_id = u.id
                        ), ARRAY[]::varchar[]
                      ) AS platform_slugs_lc,
                      COALESCE(
                        ARRAY(
                          SELECT LOWER(p.name) FROM catalog_usecase_platforms up
                          JOIN catalog_platform p ON p.id = up.platform_id
                          WHERE up.usecase_id = u.id
                        ), ARRAY[]::varchar[]
                      ) AS platform_names_lc
                    FROM catalog_usecase u
                    LEFT JOIN catalog_industry i ON i.id = u.client_industry_id
                    WHERE u.status = 'published'
                    ORDER BY u.delivered_at DESC NULLS LAST
                    LIMIT 200
                """)
                rows = [_row_to_dict(cur, r) for r in cur.fetchall()]
    except Exception as e:
        log.warning("match_for_lead failed: %s", e)
        return []

    scored: list[dict[str, Any]] = []
    for r in rows:
        score = 0
        # Industry match: slug or name (case-insensitive)
        if industry_norm:
            if r.get("industry_slug_lc") == industry_norm:
                score += 3
            elif r.get("industry_name_lc") == industry_norm:
                score += 3
        # Platform / stack overlap
        if stack_norm:
            platform_set = set(r.get("platform_slugs_lc") or []) | set(
                r.get("platform_names_lc") or [])
            overlap = platform_set & stack_norm
            score += 2 * len(overlap)
        if score > 0:
            r["match_score"] = score
            # Drop the internal lowercase fields before returning
            r.pop("industry_name_lc", None)
            r.pop("industry_slug_lc", None)
            r.pop("platform_slugs_lc", None)
            r.pop("platform_names_lc", None)
            scored.append(r)

    scored.sort(key=lambda x: (-x["match_score"],
                                 (x.get("delivered_at") or "")), reverse=False)
    # Sort key above only flips the score descending; sort_at desc
    # handled by the SQL order, so just slice.
    scored.sort(key=lambda x: x["match_score"], reverse=True)
    return scored[:limit]
