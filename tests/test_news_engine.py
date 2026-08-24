"""Contracts for the live-news pipeline: recency + source quality + dedupe."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from reyes_agent import news_engine as ne
from reyes_agent.news_engine import Article

NOW = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)


def _at(hours_ago: float) -> datetime:
    return NOW - timedelta(hours=hours_ago)


def _fetch(articles):
    return lambda topic, limit: list(articles)


def test_recency_ranks_newest_first():
    arts = [
        Article("Old story about AI", source="Reuters", published=_at(30)),
        Article("Fresh story about AI", source="Reuters", published=_at(1)),
    ]
    out = ne.live_news("AI", limit=5, now=NOW, fetch=_fetch(arts))
    assert out["articles"][0]["title"] == "Fresh story about AI"


def test_source_quality_breaks_freshness_ties():
    arts = [
        Article("Same-age story", source="Random Blog", published=_at(2)),
        Article("Same-age story two", source="Reuters", published=_at(2)),
    ]
    out = ne.live_news("x", limit=5, now=NOW, fetch=_fetch(arts))
    assert out["articles"][0]["source"] == "Reuters"


def test_deduplicates_same_story_across_outlets():
    arts = [
        Article("OpenAI releases a new model today", source="TechCrunch", published=_at(2)),
        Article("OpenAI releases a new model today", source="Reuters", published=_at(3)),
        Article("Totally different football result", source="BBC", published=_at(1)),
    ]
    out = ne.live_news("openai", limit=5, now=NOW, fetch=_fetch(arts))
    titles = [a["title"] for a in out["articles"]]
    # The duplicated OpenAI story collapses to one entry.
    assert sum("OpenAI releases" in t for t in titles) == 1
    merged = next(a for a in out["articles"] if "OpenAI releases" in a["title"])
    assert merged["corroboration"] == 2
    # The more reputable outlet (Reuters) represents it.
    assert merged["source"] == "Reuters" and "TechCrunch" in merged["also_reported_by"]


def test_missing_date_is_included_with_penalty():
    arts = [
        Article("Dated fresh story", source="AP", published=_at(1)),
        Article("Undated story", source="AP", published=None),
    ]
    out = ne.live_news("x", limit=5, now=NOW, fetch=_fetch(arts))
    assert out["count"] == 2
    assert out["articles"][0]["title"] == "Dated fresh story"   # fresh beats undated


def test_empty_fetch_is_honest():
    out = ne.live_news("nothing", now=NOW, fetch=_fetch([]))
    assert out["count"] == 0 and out["articles"] == []
    assert "No current headlines" in out["note"]


def test_provider_failure_degrades_gracefully():
    def boom(topic, limit):
        raise RuntimeError("network down")
    out = ne.live_news("x", now=NOW, fetch=boom)
    assert out["count"] == 0


def test_source_score_map_and_default():
    assert ne.source_score("Reuters") == 1.0
    assert ne.source_score("BBC News") == 0.9
    assert ne.source_score("Some Random Blog") == 0.5


def test_norm_title_strips_outlet_suffix():
    assert ne._norm_title("Big AI news - The Verge") == ne._norm_title("Big AI news")


def test_limit_respected_and_structured_shape():
    arts = [Article(f"Story {i}", source="Reuters", published=_at(i)) for i in range(10)]
    out = ne.live_news("x", limit=3, now=NOW, fetch=_fetch(arts))
    assert out["count"] == 3
    art = out["articles"][0]
    assert set(art) >= {"title", "link", "source", "published", "corroboration",
                        "also_reported_by", "score"}


def test_corroboration_bonus_lifts_confidence():
    # Two-outlet story vs a lone slightly-fresher story of equal source quality.
    arts = [
        Article("Widely reported quake hits region", source="Reuters", published=_at(3)),
        Article("Widely reported quake hits region", source="AP News", published=_at(3)),
        Article("Single-source minor update", source="Reuters", published=_at(2)),
    ]
    out = ne.live_news("quake", limit=5, now=NOW, fetch=_fetch(arts))
    top = out["articles"][0]
    assert "quake" in top["title"].lower() and top["corroboration"] == 2
