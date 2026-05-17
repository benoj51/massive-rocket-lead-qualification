"""
Parent-account suggestion from Apollo enrichment (v0.10.0 Phase B).

Goal: when we enrich KFC via Apollo, surface "this is part of Yum! Brands"
to the AE so they can one-click link it under the parent group.

Signal sources, in order of trust:
  1. Apollo's structured `parent_organization_*` fields (rare in practice
     — most plans don't return these reliably).
  2. Text patterns in the company's `short_description`. Phrases we look
     for are well-established M&A vocabulary that VCs/journalists use
     consistently across press: "subsidiary of X", "owned by X", "part of
     the X family", "operating company of X", "a brand of X", etc.

The detector returns a {source, name, confidence} dict or None.
- `source`: "apollo" | "description"
- `name`: the candidate parent name (raw, to be slugified/normalised by caller)
- `confidence`: "high" | "medium" | "low"
  - high: Apollo structured field present
  - medium: clear pattern match ("subsidiary of X", "owned by X")
  - low: softer phrasing ("part of X", "brand of X" — could be ambiguous)

We deliberately do NOT make a second Apollo call here. Resolving a
parent_organization_id → name costs another API credit and is brittle
when the parent isn't an Apollo-tracked org. The AE confirms the link
either way, so a name string is sufficient.
"""
from __future__ import annotations

import re
from typing import Any

# Patterns are ordered: most specific first wins. Each pattern returns
# the parent name in group(1). Trailing punctuation/qualifiers are stripped
# after the match.
#
# Confidence ladder:
#   high   — Apollo structured field
#   medium — "subsidiary of", "owned by", "operating company of",
#            "a wholly-owned subsidiary of"
#   low    — "part of", "brand of", "family of brands of", "division of"
# Patterns deliberately do NOT use re.IGNORECASE for the name-capture portion:
# we need [A-Z\d] to mean *real* uppercase so the regex stops at lowercase
# trailing words like "since 2020" or "focused on cloud services". The
# connector phrases ("subsidiary of", "owned by") are written lowercase in
# press copy, so no IGNORECASE needed.
#
# Name capture: leading [A-Z] + token chars, followed by up to 5 more
# Title-Cased or numeric tokens. "Yum! Brands" → 2 tokens, both pass.
_NAME = r"[A-Z][\w&\.\-\!\']*(?:\s+[A-Z\d][\w&\.\-\!\']*){0,5}"
_PATTERNS_MEDIUM: list[re.Pattern] = [
    re.compile(rf"\b(?:wholly[-\s]?owned\s+)?subsidiary\s+of\s+({_NAME})"),
    re.compile(rf"\bowned\s+by\s+({_NAME})"),
    re.compile(rf"\boperating\s+(?:company|brand)\s+of\s+({_NAME})"),
    re.compile(rf"\bacquired\s+by\s+({_NAME})"),
]
_PATTERNS_LOW: list[re.Pattern] = [
    re.compile(rf"\bpart\s+of\s+(?:the\s+)?({_NAME})\s+(?:family|group|portfolio|brands)"),
    re.compile(rf"\b(?:a\s+)?brand\s+of\s+({_NAME})"),
    re.compile(rf"\bdivision\s+of\s+({_NAME})"),
]

# Cleanup tokens that often trail a captured name and aren't part of it.
# Narrow: only strip the legal-form suffix when separated by a comma (the
# canonical form "Company Name, Inc."). "Brands", "Group", "Holdings" are
# deliberately NOT in this list — they're frequently part of the real name
# ("Yum! Brands", "Restaurant Brands International", "Marriott International
# Group", "Berkshire Hathaway Holdings"). Stripping them would mis-identify
# the parent.
_TRAILING_NOISE = re.compile(
    r",\s*(?:Inc|LLC|Ltd|Limited|Corp|Corporation|Co|Company|plc|PLC|N\.?V\.?|S\.?A\.?|GmbH)\.?\s*$",
    re.IGNORECASE,
)

# Words we won't accept as the start of a parent name — they signal the
# regex over-matched a generic noun phrase.
_BAD_STARTS = {
    "the", "a", "an", "this", "that", "these", "those", "our",
    "global", "leading", "major", "world", "world's", "innovative",
}


def _clean_name(raw: str) -> str:
    """Trim noise, strip trailing legal suffix tokens, preserve canonical name."""
    name = raw.strip()
    # Cut off the first sentence-ending punctuation if it slipped in.
    for stop in (". ", "; ", "—", " — ", ", a ", ", an ", ", the "):
        idx = name.find(stop)
        if idx > 0:
            name = name[:idx]
            break
    # Strip a trailing legal suffix only if there's still a real name left.
    stripped = _TRAILING_NOISE.sub("", name).strip(" ,.;:-")
    return stripped if len(stripped) >= 2 else name.strip(" ,.;:-")


def _looks_like_real_name(name: str) -> bool:
    """Reject candidates that don't look like an actual company name."""
    if not name or len(name) < 2:
        return False
    first_word = name.split()[0].lower().rstrip(",.;:")
    if first_word in _BAD_STARTS:
        return False
    # At least one capital letter (Apollo names are TitleCased).
    if not any(c.isupper() for c in name):
        return False
    return True


def detect_from_description(description: str) -> dict[str, Any] | None:
    """Scan the short_description for parent-relationship phrasing.

    Returns {"source": "description", "name": str, "confidence": "medium"|"low",
             "matched_phrase": str} on hit, None otherwise.
    """
    if not description:
        return None
    text = description.strip()
    for pat in _PATTERNS_MEDIUM:
        m = pat.search(text)
        if m:
            name = _clean_name(m.group(1))
            if _looks_like_real_name(name):
                return {
                    "source": "description",
                    "name": name,
                    "confidence": "medium",
                    "matched_phrase": m.group(0).strip(),
                }
    for pat in _PATTERNS_LOW:
        m = pat.search(text)
        if m:
            name = _clean_name(m.group(1))
            if _looks_like_real_name(name):
                return {
                    "source": "description",
                    "name": name,
                    "confidence": "low",
                    "matched_phrase": m.group(0).strip(),
                }
    return None


def detect_from_apollo_raw(raw_org: dict | None) -> dict[str, Any] | None:
    """Pull a parent reference from Apollo's raw organization payload, if present.

    Apollo plans vary — older ones included `parent_organization_id`, some
    include `linked_organizations`, none of them reliably. We're permissive:
    we'll surface whatever we find, leaving the AE to confirm.
    """
    if not raw_org:
        return None
    # Direct fields. Try flat names first, then a nested dict if Apollo gives one.
    name = raw_org.get("parent_organization_name") or raw_org.get("parent_account_name")
    if not name:
        nested = raw_org.get("parent_organization")
        if isinstance(nested, dict):
            name = nested.get("name")
    parent_id = raw_org.get("parent_organization_id") or raw_org.get("parent_account_id")
    domain = raw_org.get("parent_organization_domain") or raw_org.get("parent_account_domain")
    if name or parent_id or domain:
        return {
            "source": "apollo",
            "name": name or domain or parent_id,
            "confidence": "high",
            "apollo_id": parent_id,
            "domain": domain,
        }
    return None


def suggest_parent(normalised_org: dict | None) -> dict[str, Any] | None:
    """Top-level entry: combine Apollo and description signals.

    Apollo structured field wins if present (high confidence).
    Otherwise fall back to description pattern matching.
    Returns None when there's no signal — the UI hides the suggestion.
    """
    if not normalised_org:
        return None
    # Apollo structured signal first.
    apollo_hit = detect_from_apollo_raw(normalised_org.get("raw"))
    if apollo_hit:
        return apollo_hit
    # Description fallback.
    desc = normalised_org.get("short_description") or ""
    return detect_from_description(desc)
