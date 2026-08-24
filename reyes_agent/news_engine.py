"""Live news pipeline: fetch -> dedupe -> rank by freshness + source quality.

Reuses the same Google-News-RSS retrieval `get_news` already uses (which itself
aggregates Reuters/AP/BBC/TechCrunch/official blogs and groups related stories),
and adds the parts the brief asks for: parse publication dates, deduplicate the
same story across outlets (counting corroboration), score source quality, and
rank genuinely-newest-first. Everything is injectable (`fetch`, `now`) so it is
tested deterministically without the network, and it degrades honestly -- an
empty/failed fetch yields an empty result, never invented headlines.

Publication date vs. event date: RSS gives the PUBLICATION time. We rank on that
for "latest" and say so; we do not fabricate an event date we cannot see.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Callable

# Source reputation, modular and extensible. Higher = more trusted primary/wire
# reporting. Unknown sources default to a neutral score, never zero.
SOURCE_TIER: dict[str, float] = {
    "reuters": 1.0, "associated press": 1.0, "ap news": 1.0, "ap": 0.98,
    "bloomberg": 0.95, "financial times": 0.92, "the wall street journal": 0.92,
    "bbc": 0.9, "bbc news": 0.9, "npr": 0.88, "ars technica": 0.86,
    "the guardian": 0.85, "cnbc": 0.85, "al jazeera": 0.85, "the economist": 0.9,
    "cnn": 0.8, "techcrunch": 0.8, "the verge": 0.8, "wired": 0.8, "engadget": 0.75,
    # Official/primary sources rank high for their own news.
    "openai": 0.92, "google": 0.88, "microsoft": 0.88, "nvidia": 0.88,
    "meta": 0.85, "apple": 0.88,
    # Reputable Nigerian outlets.
    "premium times": 0.82, "the punch": 0.78, "punch": 0.78, "vanguard": 0.75,
    "the guardian nigeria": 0.78, "channels television": 0.8,
}
_DEFAULT_SOURCE = 0.5
_SIMILAR = 0.72          # title-similarity threshold for "same story"
_HALF_LIFE_H = 12.0      # freshness half-life in hours


@dataclass
class Article:
    title: str
    link: str = ""
    source: str = ""
    published: datetime | None = None
    corroboration: int = 1                 # how many outlets carried this story
    also_reported_by: list[str] = field(default_factory=list)
    score: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"title": self.title, "link": self.link, "source": self.source,
                "published": self.published.isoformat() if self.published else None,
                "corroboration": self.corroboration,
                "also_reported_by": list(self.also_reported_by),
                "score": round(self.score, 4)}


# --- retrieval (reuses Google News RSS, the same source as get_news) ---------
def _parse_rss_date(value: str) -> datetime | None:
    value = str(value or "").strip()
    if not value:
        return None
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def fetch_rss(topic: str, limit: int = 20) -> list[Article]:
    """Fetch and parse Google News RSS. Network-touching; returns [] on failure."""
    import urllib.parse
    import xml.etree.ElementTree as ET

    import requests

    topic = str(topic or "").strip()
    if topic:
        url = (f"https://news.google.com/rss/search?q={urllib.parse.quote(topic)}"
               "&hl=en-US&gl=US&ceid=US:en")
    else:
        url = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception:  # noqa: BLE001 -- honest empty result, never invented news
        return []
    out: list[Article] = []
    for item in root.findall(".//item")[:max(1, int(limit))]:
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        out.append(Article(
            title=title, link=(item.findtext("link") or "").strip(),
            source=(item.findtext("source") or "").strip(),
            published=_parse_rss_date(item.findtext("pubDate") or "")))
    return out


# --- pipeline ----------------------------------------------------------------
_PUNCT = re.compile(r"[^a-z0-9 ]+")


def _norm_title(title: str) -> str:
    # Google News appends " - Source"; drop it so titles compare on content.
    base = re.split(r"\s+-\s+[^-]+$", str(title or ""), maxsplit=1)[0]
    return " ".join(_PUNCT.sub(" ", base.lower()).split())


def source_score(source: str) -> float:
    return SOURCE_TIER.get(str(source or "").strip().casefold(), _DEFAULT_SOURCE)


def _freshness(published: datetime | None, now: datetime) -> float:
    if published is None:
        return 0.4                          # unknown date -> mild penalty, not zero
    age_h = max(0.0, (now - published).total_seconds() / 3600.0)
    return 0.5 ** (age_h / _HALF_LIFE_H)     # 1.0 now, 0.5 at one half-life


def _same_story(a_norm: str, b_norm: str) -> bool:
    """Whether two normalized titles are the same story. Long headlines can match
    fuzzily; SHORT ones must be near-identical, so 'Story 0' and 'Story 1' (or two
    unrelated short titles) are never wrongly merged."""
    ratio = SequenceMatcher(None, a_norm, b_norm).ratio()
    if min(len(a_norm), len(b_norm)) < 25:
        return ratio >= 0.95
    return ratio >= _SIMILAR


def deduplicate(articles: list[Article]) -> list[Article]:
    """Collapse the same story across outlets, counting corroboration. Keeps the
    highest-quality source as the representative."""
    kept: list[Article] = []
    for art in articles:
        norm = _norm_title(art.title)
        match = None
        for existing in kept:
            if _same_story(norm, _norm_title(existing.title)):
                match = existing
                break
        if match is None:
            kept.append(art)
            continue
        match.corroboration += 1
        if art.source and art.source not in match.also_reported_by:
            match.also_reported_by.append(art.source)
        # Promote the more reputable outlet to be the representative.
        if source_score(art.source) > source_score(match.source):
            art.corroboration = match.corroboration
            art.also_reported_by = match.also_reported_by + [match.source]
            kept[kept.index(match)] = art
    return kept


def rank(articles: list[Article], now: datetime) -> list[Article]:
    """Composite score: freshness (newest wins for 'latest') + source quality +
    a small corroboration bonus (multiple outlets => higher confidence)."""
    for art in articles:
        fresh = _freshness(art.published, now)
        src = source_score(art.source)
        corrob = min(0.15, 0.05 * (art.corroboration - 1))
        art.score = round(0.55 * fresh + 0.35 * src + corrob, 4)
    return sorted(articles, key=lambda a: (-a.score,
                                           -(a.published.timestamp() if a.published else 0)))


def live_news(topic: str = "", limit: int = 6, *, now: datetime | None = None,
              fetch: Callable[[str, int], list[Article]] | None = None) -> dict[str, Any]:
    """Run the full pipeline and return structured, ranked, cited results."""
    now = now or datetime.now(timezone.utc)
    fetch = fetch or fetch_rss
    try:
        raw = fetch(topic, max(10, int(limit) * 3))
    except Exception:  # noqa: BLE001
        raw = []
    if not raw:
        return {"topic": str(topic or "").strip(), "count": 0, "articles": [],
                "note": "No current headlines came back."}
    ranked = rank(deduplicate(raw), now)[:max(1, int(limit))]
    return {
        "topic": str(topic or "").strip(),
        "count": len(ranked),
        "as_of": now.isoformat(),
        "articles": [a.as_dict() for a in ranked],
        "note": "Ranked by publication recency and source quality; publication "
                "time may differ from when the event occurred.",
    }
