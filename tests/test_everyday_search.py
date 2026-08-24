"""Contracts for screen recall, context priority, and universal personal search."""

from __future__ import annotations

from reyes_agent.everyday import context_priority as cp
from reyes_agent.everyday import screen_recall as sr
from reyes_agent.everyday.context_priority import ScreenContext
from reyes_agent.everyday.personal_search import UniversalPersonalSearch
from reyes_agent.everyday.screen_recall import ScreenRecallEngine, ScreenSnapshot


# --- screen recall ----------------------------------------------------------
def _snap(i, app, **kw):
    return ScreenSnapshot(id=str(i), app=app, **kw)


def test_mode_off_stores_nothing():
    eng = ScreenRecallEngine(mode=sr.OFF)
    assert eng.capture(_snap(1, "chrome", title="Python error")) is False
    assert len(eng) == 0


def test_session_only_captures_and_searches():
    eng = ScreenRecallEngine(mode=sr.SESSION_ONLY)
    assert eng.capture(_snap(1, "chrome", title="Stack Overflow", description="python TypeError"))
    hits = eng.search("python error")
    assert hits and hits[0]["app"] == "chrome"


def test_excluded_and_incognito_never_captured():
    eng = ScreenRecallEngine(mode=sr.FULL_OPT_IN)
    assert eng.capture(_snap(1, "1Password", title="Vault")) is False       # excluded app
    assert eng.capture(_snap(2, "chrome", title="bank login"),
                       incognito=True) is False                              # incognito
    eng.exclude_app("secretapp")
    assert eng.capture(_snap(3, "SecretApp", title="x")) is False
    assert len(eng) == 0


def test_work_only_and_custom_apps_modes():
    work = ScreenRecallEngine(mode=sr.WORK_ONLY, work_apps={"vscode"})
    assert work.capture(_snap(1, "vscode", title="main.py"))
    assert work.capture(_snap(2, "chrome", title="youtube")) is False
    custom = ScreenRecallEngine(mode=sr.CUSTOM_APPS, custom_apps={"slack"})
    assert custom.capture(_snap(1, "slack", title="general"))
    assert custom.capture(_snap(2, "vscode", title="x")) is False


def test_secret_screen_is_refused():
    eng = ScreenRecallEngine(mode=sr.FULL_OPT_IN)
    assert eng.capture(_snap(1, "chrome", title="keys",
                             ocr_text="api key sk-ABCDEFGH1234567890")) is False


def test_forget_app_and_clear():
    eng = ScreenRecallEngine(mode=sr.SESSION_ONLY)
    eng.capture(_snap(1, "chrome", title="a"))
    eng.capture(_snap(2, "slack", title="b"))
    assert eng.forget_app("chrome") == 1 and len(eng) == 1
    eng.clear()
    assert len(eng) == 0


# --- context priority -------------------------------------------------------
def test_selection_wins_over_everything():
    ctx = ScreenContext(selection="highlighted text", focused_app="chrome",
                        active_file="a.py", active_url="http://x")
    r = cp.resolve(ctx)
    assert r["source"] == "selection" and r["content"] == "highlighted text"


def test_priority_falls_through_in_order():
    assert cp.resolve(ScreenContext(focused_app="VSCode", focused_title="main.py"))["source"] == "focused_window"
    assert cp.resolve(ScreenContext(conversation_ref="the API"))["source"] == "conversation"
    assert cp.resolve(ScreenContext(active_file="a.py"))["source"] == "active_file"
    assert cp.resolve(ScreenContext(active_url="http://x"))["source"] == "active_webpage"
    assert cp.resolve(ScreenContext(recent="last thing"))["source"] == "recent"
    assert cp.resolve(ScreenContext())["source"] == "none"


def test_resolve_for_command_targets():
    ctx = ScreenContext(selection="sel", active_url="http://page", active_file="f.py")
    assert cp.resolve_for("explain the selection", ctx)["source"] == "selection"
    assert cp.resolve_for("summarize this page", ScreenContext(active_url="http://p"))["source"] == "active_webpage"
    assert cp.resolve_for("open this file", ScreenContext(active_file="f.py"))["source"] == "active_file"


# --- universal personal search ----------------------------------------------
NOW = 1_000_000.0


def _src(items):
    return lambda q: items


def test_search_ranks_relevance_and_returns_provenance():
    s = UniversalPersonalSearch()
    s.register_source("files", _src([
        {"title": "SIWES report Catherine", "snippet": "the pdf", "location": "C:/docs/siwes.pdf",
         "timestamp": NOW - 3600},
        {"title": "unrelated grocery list", "snippet": "milk eggs", "location": "C:/x.txt",
         "timestamp": NOW - 3600},
    ]), trust=0.8)
    out = s.search("SIWES report Catherine", now=NOW)
    assert out[0]["title"].startswith("SIWES report")
    assert set(out[0]) >= {"title", "snippet", "source", "location", "timestamp",
                           "score", "confidence"}
    assert out[0]["source"] == "files" and out[0]["confidence"] in {"HIGH", "MEDIUM", "LOW"}


def test_recency_breaks_relevance_ties():
    s = UniversalPersonalSearch()
    s.register_source("notes", _src([
        {"title": "meeting notes", "snippet": "", "timestamp": NOW - 40 * 86400},
        {"title": "meeting notes", "snippet": "", "timestamp": NOW - 1 * 86400},
    ]))
    out = s.search("meeting notes", now=NOW)
    assert out[0]["timestamp"] == NOW - 1 * 86400          # newer first


def test_disconnected_source_excluded_and_reported():
    s = UniversalPersonalSearch()
    s.register_source("gmail", _src([{"title": "important mail", "timestamp": NOW}]),
                      connected=False)
    assert s.search("important mail", now=NOW) == []
    status = {x["name"]: x["connected"] for x in s.sources_status()}
    assert status["gmail"] is False


def test_bad_source_does_not_crash_search():
    s = UniversalPersonalSearch()
    def boom(q):
        raise RuntimeError("provider down")
    s.register_source("flaky", boom)
    s.register_source("good", _src([{"title": "found it", "timestamp": NOW}]))
    out = s.search("found", now=NOW)
    assert len(out) == 1 and out[0]["title"] == "found it"


def test_project_context_boosts():
    s = UniversalPersonalSearch()
    s.register_source("files", _src([
        {"title": "design doc", "snippet": "about the T21 dashboard", "timestamp": NOW},
        {"title": "design doc", "snippet": "about something else", "timestamp": NOW},
    ]))
    out = s.search("design doc", now=NOW, project="T21")
    assert "T21" in out[0]["snippet"]


def test_empty_query_returns_empty():
    s = UniversalPersonalSearch()
    s.register_source("x", _src([{"title": "a", "timestamp": NOW}]))
    assert s.search("", now=NOW) == []
