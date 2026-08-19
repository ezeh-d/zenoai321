"""ZENO's anime/manga companion.

The network and the vision model are mocked -- these test ZENO's own logic:
that AniList responses are parsed correctly (manhwa vs manga vs anime), that
the reader asks the vision model the right thing for each format, that the
shelf round-trips, and that everything fails honestly when a service is down.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("ZENO_ENV", "test")

from reyes_agent.anime import catalog, library, reader  # noqa: E402
from reyes_agent.tools import TOOLS  # noqa: E402


# --- fixtures: canned AniList media -------------------------------------
def _media(**over):
    node = {
        "id": 1, "type": "MANGA", "format": "MANGA", "status": "RELEASING",
        "countryOfOrigin": "KR", "episodes": None, "chapters": 200, "volumes": None,
        "averageScore": 84, "genres": ["Action", "Fantasy"],
        "title": {"romaji": "Solo Leveling", "english": "Solo Leveling", "native": "나 혼자만 레벨업"},
        "description": "<p>Ten years ago, gates connected our world to monsters.</p>",
        "siteUrl": "https://anilist.co/manga/105398", "startDate": {"year": 2018},
    }
    node.update(over)
    return node


# --- catalog: parsing ----------------------------------------------------
def test_a_korean_manga_is_labelled_manhwa():
    s = catalog._series(_media(countryOfOrigin="KR"))
    assert s.flavour == "manhwa"


def test_a_japanese_manga_is_labelled_manga():
    s = catalog._series(_media(countryOfOrigin="JP"))
    assert s.flavour == "manga"


def test_an_anime_is_labelled_anime():
    s = catalog._series(_media(type="ANIME", episodes=25, chapters=None))
    assert s.flavour == "anime"


def test_html_is_stripped_from_the_synopsis():
    s = catalog._series(_media())
    assert "<p>" not in s.as_dict()["synopsis"]
    assert "monsters" in s.as_dict()["synopsis"]


def test_search_parses_a_page(monkeypatch):
    monkeypatch.setattr(catalog, "_query",
                        lambda q, v: {"Page": {"media": [_media(), _media(id=2, title={"romaji": "Omniscient Reader"})]}})
    results = catalog.search("reader")
    assert len(results) == 2
    assert results[0].title == "Solo Leveling"


def test_recommendations_returns_base_plus_list(monkeypatch):
    monkeypatch.setattr(catalog, "_query", lambda q, v: {"Media": {
        **_media(),
        "recommendations": {"nodes": [
            {"mediaRecommendation": _media(id=9, title={"romaji": "The Beginning After The End"})}]}}})
    base, recs = catalog.recommendations("Solo Leveling")
    assert base.title == "Solo Leveling"
    assert recs and recs[0].title == "The Beginning After The End"


def test_a_network_error_is_a_plain_message(monkeypatch):
    def boom(q, v):
        raise RuntimeError("couldn't reach AniList: timeout")

    monkeypatch.setattr(catalog, "_query", boom)
    out = TOOLS["anime_search"].func(query="anything")
    assert "Couldn't search AniList" in out


# --- reader: the vision-based page understanding ------------------------
def test_the_reader_tells_the_model_manga_is_right_to_left(monkeypatch):
    captured = {}

    def fake_describe(image_bytes, prompt):
        captured["prompt"] = prompt
        return "Panel 1: ..."

    monkeypatch.setattr("reyes_agent.tools.vision._describe_image", fake_describe)
    result = reader.read_page(b"fakeimagebytes", fmt="manga")
    assert result.ok
    assert "RIGHT-TO-LEFT" in captured["prompt"]


def test_the_reader_tells_the_model_manhwa_is_vertical(monkeypatch):
    captured = {}
    monkeypatch.setattr("reyes_agent.tools.vision._describe_image",
                        lambda b, p: captured.update(prompt=p) or "ok")
    reader.read_page(b"img", fmt="manhwa")
    assert "TOP-TO-BOTTOM" in captured["prompt"] or "vertical" in captured["prompt"].lower()


def test_the_reader_fails_honestly_without_a_vision_key(monkeypatch):
    def no_key(image_bytes, prompt):
        raise RuntimeError("No GEMINI_API_KEY set")

    monkeypatch.setattr("reyes_agent.tools.vision._describe_image", no_key)
    result = reader.read_page(b"img", fmt="auto")
    assert result.ok is False
    assert "GEMINI_API_KEY" in result.detail


def test_the_reader_refuses_an_empty_image():
    assert reader.read_page(b"", fmt="manga").ok is False


def test_read_manga_page_reports_a_missing_file():
    out = TOOLS["read_manga_page"].func(path="/no/such/page.png")
    assert "No file at" in out


# --- library: the shelf --------------------------------------------------
def test_the_shelf_tracks_and_recalls_progress(tmp_path):
    shelf = library.reset_for_tests(tmp_path / "shelf.sqlite")
    shelf.track("Frieren", "anime", status="watching", progress=12, total=28)
    entry = shelf.get("Frieren")
    assert entry.status == "watching"
    assert entry.progress == 12
    assert "12/28" in entry.as_dict()["progress"]


def test_updating_progress_keeps_the_earlier_fields(tmp_path):
    shelf = library.reset_for_tests(tmp_path / "shelf.sqlite")
    shelf.track("Solo Leveling", "manga", status="reading", total=200)
    shelf.track("Solo Leveling", "manga", progress=110)   # only progress
    entry = shelf.get("Solo Leveling")
    assert entry.progress == 110
    assert entry.total == 200          # not lost
    assert entry.status == "reading"   # not reset


def test_the_shelf_filters_by_status(tmp_path):
    shelf = library.reset_for_tests(tmp_path / "shelf.sqlite")
    shelf.track("A", "anime", status="watching")
    shelf.track("B", "anime", status="completed")
    watching = shelf.shelf(status="watching")
    assert [e.title for e in watching] == ["A"]


def test_my_shelf_tool_is_empty_then_populated(tmp_path):
    library.reset_for_tests(tmp_path / "shelf.sqlite")
    assert "empty" in TOOLS["my_shelf"].func().lower()
    TOOLS["track_series"].func(title="Berserk", kind="manga", status="reading", progress=364)
    out = TOOLS["my_shelf"].func()
    assert "Berserk" in out and "364" in out


# --- registration + routing ---------------------------------------------
def test_all_seven_anime_tools_are_registered():
    for name in ("anime_search", "anime_info", "anime_recommend", "anime_trending",
                 "read_manga_page", "track_series", "my_shelf"):
        assert name in TOOLS, name


def test_anime_requests_route_to_anime():
    from reyes_agent.routing import capability

    for msg in ("what's a good manhwa to read", "recommend an anime to watch",
                "read this manga page", "what am I watching",
                "add Solo Leveling to my reading list"):
        assert "anime" in capability.tools_for(msg).capabilities, msg


def test_non_anime_requests_do_not_route_to_anime():
    from reyes_agent.routing import capability

    for msg in ("open Chrome", "read the config file", "delete the folder"):
        assert "anime" not in capability.tools_for(msg).capabilities, msg
