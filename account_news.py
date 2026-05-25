"""v1.0.0bj — Account news fetcher + AI relevance scorer.

Pulls recent news for an account (company name), runs it through
Claude to score relevance against Massive Rocket's offer, returns
the scored + filtered set ready for persistence + notification.

Why Google News RSS
-------------------
Free, no API key, returns the last ~30 days of headlines for any
query. Good enough for "what's notable about this account this week".
If we outgrow it (rate limits, noise) we can swap for NewsAPI /
Perplexity later — the public interface stays the same.

MR relevance rubric
-------------------
Score 0-10. The prompt asks Claude to consider:
- Is this material to MR's CRM, loyalty, data, AI/personalization, or
  engineering offer?
- Examples that score high: loyalty programme launch, CDP/warehouse
  migration, new mobile app, marketing tech RFP, leadership change in
  CMO / CIO / VP Marketing / Head of CRM, M&A that consolidates a
  customer database, earnings commentary on marketing spend.
- Examples that score low: local store openings, generic press, sports
  sponsorships, non-marketing-org leadership changes.

API
---
    fetch_for_company(company_name, *, since_iso=None) -> list[NewsItem]
        Pulls + parses RSS. Optional `since_iso` filter drops items
        older than that timestamp. Returns raw items (no scoring).

    score_relevance(items, company_name) -> list[ScoredNewsItem]
        Runs each item through Claude. Returns items with
        {relevance_score, why_relevant, mr_action_hint}. Items
        below threshold (4) are dropped.

    NewsItem = {id, title, link, source, published_at, snippet}
    ScoredNewsItem extends NewsItem with:
      relevance_score (int 0-10)
      why_relevant    (1-line str)
      mr_action_hint  (str | None — what an AE could do with this)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import requests

log = logging.getLogger(__name__)

# Google News RSS endpoint. Query parameter `q` accepts any text.
# Extra params: language=en, geo=US (broad — we trim by publishedAt).
_GOOGLE_NEWS_URL = (
    "https://news.google.com/rss/search"
    "?q={q}&hl=en-US&gl=US&ceid=US:en"
)

# Drop items with relevance below this. Tunable.
_RELEVANCE_THRESHOLD = 4

# v1.0.0bj system prompt for the relevance scorer.
_RELEVANCE_SYSTEM_PROMPT = """You are scoring news headlines for an
agency called Massive Rocket. MR sells:
- CRM + lifecycle marketing strategy + build + execute (Braze,
  Iterable, Salesforce Marketing Cloud, Customer.io)
- Customer data platforms + data warehousing (mParticle, Segment,
  Snowflake, Hightouch)
- Loyalty programme strategy + build
- Mobile + web personalisation + AI personalisation
- Engineering / integration work for the above

You'll receive a JSON array of news items, each with title +
snippet + source + publication date. For each, return:
{
  "id": "<the id as supplied>",
  "relevance_score": <int 0-10>,
  "why_relevant": "<one short sentence: why this matters for MR>",
  "mr_action_hint": "<one short phrase: what could an AE do with this,
                     or null if nothing actionable>"
}

Score rubric:
- 9-10: directly material — a new CRM/loyalty programme, CMO/Head of
  CRM hire, data platform RFP, marketing tech consolidation, M&A that
  merges customer databases.
- 6-8: indirectly relevant — earnings commentary on marketing spend
  growth, mobile app launch, new product line that needs lifecycle
  marketing, leadership change in adjacent function (CIO, COO).
- 4-5: tangentially interesting — adjacent industry signal, smaller
  product update, partnership announcement.
- 1-3: background noise — local store opening, sponsorship,
  non-marketing exec change.
- 0: irrelevant.

Be strict. Most news scores below 5. Don't inflate.

The why_relevant should ground itself in MR's offer specifically —
not generic ("good for the company") but specific ("loyalty rebuild
opportunity" or "fresh CMO is a relationship-rebuild window").

mr_action_hint is optional. Set it only when there's a clear, concrete
next move ("Reach out via Marina at Braze on the Q3 CDP RFP"). Use
null when nothing concrete jumps out.

Return ONLY a JSON array. No prose, no markdown fence."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _item_id(title: str, link: str) -> str:
    """Deterministic id for dedup. Hash of title+link so the same
    article from a re-poll doesn't reappear."""
    h = hashlib.sha1(f"{title.strip().lower()}|{link.strip()}".encode("utf-8"))
    return h.hexdigest()[:16]


def _parse_rss(xml_text: str) -> list[dict[str, Any]]:
    """Cheap RSS parse — no external lib. Google News' RSS is
    well-formed enough that regex extraction works reliably; the
    feedparser dependency isn't worth the bloat for one feed."""
    items: list[dict[str, Any]] = []
    # Each <item>...</item> block. Non-greedy.
    for block in re.findall(r"<item>(.*?)</item>", xml_text, flags=re.DOTALL):
        def _get(tag: str) -> str:
            m = re.search(rf"<{tag}>(.*?)</{tag}>", block, flags=re.DOTALL)
            if not m:
                return ""
            text = m.group(1).strip()
            # Strip CDATA + HTML if present.
            text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1",
                            text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", "", text)
            return text.strip()
        title = _get("title")
        link = _get("link")
        if not (title and link):
            continue
        # description in Google News RSS is usually HTML with the
        # source name + snippet. Strip + keep first 280 chars.
        snippet = _get("description")[:280]
        # source name lives in <source>name</source> usually.
        source = _get("source") or _extract_source_from_title(title)
        pub_date = _get("pubDate")
        # Normalise pub_date to ISO if parseable.
        published_iso = _normalise_pub_date(pub_date)
        items.append({
            "id":           _item_id(title, link),
            "title":        title,
            "link":         link,
            "source":       source,
            "published_at": published_iso,
            "snippet":      snippet,
        })
    return items


def _extract_source_from_title(title: str) -> str:
    """Google News titles often look like "Headline text - Reuters".
    Pull the dash-suffix as the source when no <source> tag was
    present."""
    if " - " in title:
        return title.rsplit(" - ", 1)[-1].strip()
    return ""


def _normalise_pub_date(raw: str) -> str | None:
    """Google News uses RFC-822 dates. Best-effort parse → ISO-Z.
    Returns None if unparseable."""
    if not raw:
        return None
    # Common RFC-822 formats from Google News.
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%a, %d %b %Y %H:%M:%S +0000",
    ):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    return None


def fetch_for_company(company_name: str, *,
                      since_iso: str | None = None,
                      limit: int = 20) -> list[dict[str, Any]]:
    """Pull recent news for `company_name`. Optionally filter to items
    newer than `since_iso`. Returns raw items (no scoring)."""
    if not (company_name or "").strip():
        return []
    q = quote_plus(company_name.strip())
    url = _GOOGLE_NEWS_URL.format(q=q)
    try:
        resp = requests.get(url, timeout=15,
                             headers={"User-Agent": "MR-LeadPlatform/1.0"})
        if not resp.ok:
            # v1.0.0cb: log status code only — response bodies can
            # echo the query (which contains the company name) into
            # log destinations we don't necessarily control.
            log.warning("Google News fetch returned HTTP %s",
                          resp.status_code)
            return []
    except requests.RequestException as e:
        log.warning("Google News fetch failed for %s: %s", company_name, e)
        return []
    items = _parse_rss(resp.text)
    if since_iso:
        items = [i for i in items
                 if not i.get("published_at")
                 or i["published_at"] > since_iso]
    return items[:limit]


def score_relevance(items: list[dict[str, Any]], company_name: str
                    ) -> list[dict[str, Any]]:
    """Run Claude on `items` to score each for MR relevance. Items
    below the threshold are dropped. Caller decides what to do with
    the rest (persist, notify, etc).

    Returns each surviving item augmented with relevance_score,
    why_relevant, mr_action_hint. Original keys are preserved.

    Returns [] if Anthropic isn't configured OR the call fails. The
    caller can fall back to showing items without scoring (e.g. raw
    feed view) rather than nothing at all.
    """
    if not items:
        return []
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return []
    try:
        from anthropic import Anthropic
    except ImportError:
        log.warning("anthropic SDK not installed; relevance scoring off.")
        return []
    # Send only the fields the model needs (id + display text).
    payload = [
        {
            "id":           i["id"],
            "title":        i.get("title", ""),
            "snippet":      i.get("snippet", "")[:280],
            "source":       i.get("source", ""),
            "published_at": i.get("published_at", ""),
        }
        for i in items
    ]
    user_msg = (f"Company: {company_name}\n\n"
                f"News items:\n{json.dumps(payload, indent=2)}")
    try:
        client = Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
            max_tokens=2500,
            system=_RELEVANCE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = ""
        for block in msg.content:
            t = getattr(block, "text", None) or ""
            if t:
                text = t
                break
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text).rstrip("`").strip()
        scored = json.loads(text)
    except Exception as e:
        log.warning("Relevance scoring failed for %s: %s", company_name, e)
        return []
    if not isinstance(scored, list):
        log.warning("Relevance scoring: expected list, got %s",
                      type(scored).__name__)
        return []
    by_id = {i["id"]: i for i in items}
    out: list[dict[str, Any]] = []
    for s in scored:
        if not isinstance(s, dict):
            continue
        item_id = s.get("id")
        if item_id not in by_id:
            continue
        try:
            score = int(s.get("relevance_score") or 0)
        except (ValueError, TypeError):
            continue
        if score < _RELEVANCE_THRESHOLD:
            continue
        why = (s.get("why_relevant") or "").strip()
        action = (s.get("mr_action_hint") or "").strip() or None
        out.append({
            **by_id[item_id],
            "relevance_score": max(0, min(10, score)),
            "why_relevant":    why,
            "mr_action_hint":  action,
            "scored_at":       _now_iso(),
        })
    # Sort highest-relevance first.
    out.sort(key=lambda r: -r["relevance_score"])
    return out
