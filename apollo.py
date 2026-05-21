"""
Apollo.io REST client for the Lead Qualification Platform.

Single source of truth for talking to Apollo. Two public entrypoints:
    - enrich_organization(domain)  -> normalised org dict
    - search_people(org_id, titles) -> list of normalised people dicts

Network calls are file-cached for APOLLO_CACHE_TTL_HOURS (default 24h) to keep
Apollo credit consumption low during dev/testing.

When APOLLO_USE_FIXTURES=1 or APOLLO_API_KEY is empty, the client serves
fixtures from tests/fixtures/apollo/ — same shape as the real responses,
so the rest of the platform is identical in stubbed mode.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

APOLLO_BASE = "https://api.apollo.io/api/v1"
DEFAULT_TIMEOUT = 30
FIXTURE_DIR = Path(__file__).parent / "tests" / "fixtures" / "apollo"


class ApolloError(RuntimeError):
    """Raised when Apollo returns a non-2xx response we can't recover from."""


@dataclass
class ApolloConfig:
    api_key: str
    cache_dir: Path
    cache_ttl_seconds: int
    use_fixtures: bool

    @classmethod
    def from_env(cls) -> "ApolloConfig":
        api_key = os.environ.get("APOLLO_API_KEY", "").strip()
        use_fixtures = os.environ.get("APOLLO_USE_FIXTURES", "0") == "1" or not api_key
        cache_dir = Path(os.environ.get("APOLLO_CACHE_DIR", "cache/apollo"))
        ttl_hours = int(os.environ.get("APOLLO_CACHE_TTL_HOURS", "24"))
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cls(
            api_key=api_key,
            cache_dir=cache_dir,
            cache_ttl_seconds=ttl_hours * 3600,
            use_fixtures=use_fixtures,
        )


REGION_MAP_COUNTRY = {
    # EMEA
    "united kingdom": "EMEA", "ireland": "EMEA", "france": "EMEA",
    "germany": "EMEA", "spain": "EMEA", "italy": "EMEA", "netherlands": "EMEA",
    "sweden": "EMEA", "norway": "EMEA", "denmark": "EMEA", "finland": "EMEA",
    "poland": "EMEA", "portugal": "EMEA", "belgium": "EMEA", "switzerland": "EMEA",
    "austria": "EMEA", "uae": "EMEA", "saudi arabia": "EMEA", "israel": "EMEA",
    "south africa": "EMEA",
    # NAM
    "united states": "NAM", "usa": "NAM", "canada": "NAM", "mexico": "NAM",
    # APAC
    "australia": "APAC", "new zealand": "APAC", "singapore": "APAC",
    "japan": "APAC", "south korea": "APAC", "india": "APAC", "indonesia": "APAC",
    "philippines": "APAC", "malaysia": "APAC", "thailand": "APAC", "vietnam": "APAC",
    "hong kong": "APAC", "china": "APAC",
    # LATAM rolls into "Other" per ICP
    "brazil": "Other", "argentina": "Other", "chile": "Other", "colombia": "Other",
}


def _derive_region(country: str | None) -> str:
    if not country:
        return "Other"
    return REGION_MAP_COUNTRY.get(country.strip().lower(), "Other")


def _cache_key(endpoint: str, payload: dict) -> str:
    blob = json.dumps({"e": endpoint, "p": payload}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def _cache_read(cfg: ApolloConfig, key: str) -> dict | None:
    path = cfg.cache_dir / f"{key}.json"
    if not path.exists():
        return None
    age = time.time() - path.stat().st_mtime
    if age > cfg.cache_ttl_seconds:
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _cache_write(cfg: ApolloConfig, key: str, data: dict) -> None:
    path = cfg.cache_dir / f"{key}.json"
    try:
        path.write_text(json.dumps(data))
    except OSError:
        pass


def _fixture_for(domain: str) -> dict | None:
    if not FIXTURE_DIR.exists():
        return None
    slug = domain.lower().replace("https://", "").replace("http://", "")
    slug = slug.split("/")[0].replace("www.", "").replace(".", "_")
    path = FIXTURE_DIR / f"{slug}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _clean_domain(url_or_domain: str) -> str:
    s = url_or_domain.strip().lower()
    for prefix in ("https://", "http://"):
        if s.startswith(prefix):
            s = s[len(prefix):]
    if s.startswith("www."):
        s = s[4:]
    s = s.split("/")[0].split("?")[0]
    return s


def _post(cfg: ApolloConfig, endpoint: str, payload: dict) -> dict:
    """Cached POST. Returns parsed JSON or raises ApolloError."""
    key = _cache_key(endpoint, payload)
    cached = _cache_read(cfg, key)
    if cached is not None:
        return cached
    url = f"{APOLLO_BASE}{endpoint}"
    headers = {
        "Cache-Control": "no-cache",
        "Content-Type": "application/json",
        "accept": "application/json",
        "x-api-key": cfg.api_key,
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=DEFAULT_TIMEOUT)
    if resp.status_code == 429:
        raise ApolloError("Apollo rate limit hit (429). Back off and retry.")
    if not resp.ok:
        raise ApolloError(f"Apollo {endpoint} {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    _cache_write(cfg, key, data)
    return data


def _normalise_organization(raw: dict) -> dict:
    org = raw.get("organization") or raw
    if not org:
        return {}
    country = org.get("country") or org.get("organization_country")
    industry = org.get("industry") or ""
    technologies = []
    for t in (org.get("current_technologies") or []):
        if isinstance(t, dict) and t.get("name"):
            technologies.append(t["name"])
        elif isinstance(t, str):
            technologies.append(t)
    technologies.extend(org.get("technology_names") or [])
    technologies = sorted({t for t in technologies if t})

    return {
        "apollo_id": org.get("id"),
        "name": org.get("name"),
        "domain": org.get("primary_domain") or org.get("website_url"),
        "website_url": org.get("website_url"),
        "linkedin_url": org.get("linkedin_url"),
        "industry": industry,
        "keywords": org.get("keywords") or [],
        "short_description": org.get("short_description") or org.get("seo_description"),
        "founded_year": org.get("founded_year"),
        "annual_revenue": org.get("annual_revenue"),
        "annual_revenue_printed": org.get("annual_revenue_printed"),
        "estimated_num_employees": org.get("estimated_num_employees"),
        "country": country,
        "city": org.get("city"),
        "state": org.get("state"),
        "region": _derive_region(country),
        "technologies": technologies,
        "raw": org,
    }


def _normalise_person(p: dict) -> dict:
    return {
        "apollo_id": p.get("id"),
        "name": p.get("name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
        "title": p.get("title"),
        "seniority": p.get("seniority"),
        "linkedin_url": p.get("linkedin_url"),
        "email": p.get("email"),
        "email_status": p.get("email_status"),
        "city": p.get("city"),
        "country": p.get("country"),
        "departments": p.get("departments") or [],
        "functions": p.get("functions") or [],
    }


def enrich_organization(domain_or_url: str, cfg: ApolloConfig | None = None) -> dict:
    """Enrich a company by domain. Returns a normalised dict (see _normalise_organization)."""
    cfg = cfg or ApolloConfig.from_env()
    domain = _clean_domain(domain_or_url)
    if not domain:
        raise ValueError("Empty domain passed to enrich_organization")

    if cfg.use_fixtures:
        fixture = _fixture_for(domain)
        if fixture is not None:
            return _normalise_organization(fixture)
        # Fixture missing but fixtures mode is on -> return a clearly-stubbed shell
        return {
            "name": None, "domain": domain, "region": "Other",
            "industry": None, "technologies": [], "raw": {},
            "_stub": True,
            "_stub_reason": f"No fixture for {domain}; add tests/fixtures/apollo/{domain.replace('.', '_')}.json"
        }

    raw = _post(cfg, "/organizations/enrich", {"domain": domain})
    return _normalise_organization(raw)


# Default seniority filters Massive Rocket cares about for first-touch outreach.
# Covers Marketing/CRM leadership, Digital, Data, and Analytics functions —
# MR's typical buyer mix on QSR + retail + fintech engagements.
DEFAULT_PEOPLE_TITLES = [
    # Marketing + CRM leadership
    "VP Marketing", "VP CRM", "VP Customer", "VP Growth",
    "Director Marketing", "Director CRM", "Director Lifecycle",
    "Head of Marketing", "Head of CRM", "Head of Lifecycle", "Head of Growth",
    "Chief Marketing Officer", "CMO",
    "Chief Customer Officer", "CCO",
    # Martech + Marketing Operations (v0.10.0r — was the gap behind Ben's
    # "only marketing contacts" feedback; Martech ops owns the CDP + ESP
    # decision in the QSR / retail / travel buyers we sell into)
    "VP Marketing Technology", "VP Martech",
    "Director Marketing Technology", "Director Martech",
    "Head of Marketing Technology", "Head of Martech",
    "Marketing Technology Lead", "Martech Lead", "Martech Architect",
    "Marketing Technologist",
    "VP Marketing Operations", "Director Marketing Operations",
    "Head of Marketing Operations", "Marketing Operations Manager",
    "Senior Manager Marketing Operations",
    "Director Marketing Technology & Analytics",
    # Digital leadership
    "Chief Digital Officer", "CDO",
    "Chief Digital Transformation Officer", "CDTO",
    "VP Digital", "Director Digital", "Head of Digital",
    "Head of Digital Marketing", "Director Digital Marketing",
    "Director Digital Experience", "Head of Digital Experience",
    "Director Digital Product", "Head of Digital Product",
    # Data leadership
    "Chief Data Officer", "Chief Data and Analytics Officer",
    "VP Data", "Director Data", "Head of Data",
    "Head of Data Engineering", "Director Data Engineering",
    "Head of Analytics", "VP Analytics", "Director Analytics",
    "Head of Customer Data", "Director Customer Data",
    "Head of Data Platform", "Director Data Platform",
    "Head of Data Science", "Director Data Science",
]


def search_people(
    org_id: str | None = None,
    org_domain: str | None = None,
    titles: list[str] | None = None,
    limit: int = 10,
    cfg: ApolloConfig | None = None,
) -> list[dict]:
    """Find decision-makers for an org. Pass either apollo org_id or domain."""
    cfg = cfg or ApolloConfig.from_env()
    titles = titles or DEFAULT_PEOPLE_TITLES

    if cfg.use_fixtures:
        domain_slug = _clean_domain(org_domain or "") if org_domain else None
        if domain_slug:
            fixture = _fixture_for(domain_slug)
            if fixture and isinstance(fixture.get("people"), list):
                return [_normalise_person(p) for p in fixture["people"][:limit]]
        return []

    payload: dict[str, Any] = {
        "person_titles": titles,
        "page": 1,
        "per_page": limit,
    }
    if org_id:
        payload["organization_ids"] = [org_id]
    elif org_domain:
        payload["q_organization_domains_list"] = [_clean_domain(org_domain)]
    else:
        raise ValueError("search_people requires org_id or org_domain")

    # /mixed_people/search was deprecated mid-2026; the current path is
    # /mixed_people/api_search. Payload shape is unchanged.
    raw = _post(cfg, "/mixed_people/api_search", payload)
    people = raw.get("people") or []
    return [_normalise_person(p) for p in people[:limit]]


def healthcheck(cfg: ApolloConfig | None = None) -> dict:
    """Lightweight diagnostic for /api/health."""
    cfg = cfg or ApolloConfig.from_env()
    return {
        "configured": bool(cfg.api_key),
        "mode": "fixtures" if cfg.use_fixtures else "live",
        "cache_dir": str(cfg.cache_dir),
        "cache_ttl_seconds": cfg.cache_ttl_seconds,
    }
