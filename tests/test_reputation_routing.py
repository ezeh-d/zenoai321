"""The capability router ranks exposed tools by rolling-window reputation."""

from __future__ import annotations

import pytest

from reyes_agent.routing.capability import _rank_by_reputation
from reyes_agent.tool_reputation import ToolReputation


@pytest.fixture
def fresh_rep(monkeypatch):
    rep = ToolReputation()
    monkeypatch.setattr("reyes_agent.tool_reputation.get_reputation", lambda: rep)
    # Keep the flag on regardless of the live store, without persisting.
    monkeypatch.setattr("reyes_agent.feature_flags.is_enabled",
                        lambda name, default=None: True)
    return rep


def test_reliable_tool_ranks_before_flaky(fresh_rep):
    for _ in range(30):
        fresh_rep.record("browser_open", True)
    for _ in range(30):
        fresh_rep.record("browser_vision_click", False)
    ranked = _rank_by_reputation(("browser_vision_click", "browser_open"))
    assert ranked[0] == "browser_open"


def test_unseen_tools_keep_curated_order(fresh_rep):
    tools = ("a", "b", "c", "d")
    assert _rank_by_reputation(tools) == tools  # no data -> stable no-op


def test_single_or_empty_is_returned_unchanged(fresh_rep):
    assert _rank_by_reputation(()) == ()
    assert _rank_by_reputation(("solo",)) == ("solo",)


def test_proven_tool_beats_unseen_but_unseen_keep_order(fresh_rep):
    for _ in range(40):
        fresh_rep.record("proven", True)
    ranked = _rank_by_reputation(("unseen1", "unseen2", "proven", "unseen3"))
    assert ranked[0] == "proven"
    # the unseen ones stay in their original relative order
    assert ranked[1:] == ("unseen1", "unseen2", "unseen3")


def test_flag_off_disables_ranking(monkeypatch):
    rep = ToolReputation()
    for _ in range(30):
        rep.record("good", True)
    for _ in range(30):
        rep.record("bad", False)
    monkeypatch.setattr("reyes_agent.tool_reputation.get_reputation", lambda: rep)
    monkeypatch.setattr("reyes_agent.feature_flags.is_enabled",
                        lambda name, default=None: False)
    assert _rank_by_reputation(("bad", "good")) == ("bad", "good")  # unchanged


def test_ranking_never_raises(monkeypatch):
    def boom():
        raise RuntimeError("telemetry down")

    monkeypatch.setattr("reyes_agent.tool_reputation.get_reputation", boom)
    monkeypatch.setattr("reyes_agent.feature_flags.is_enabled",
                        lambda name, default=None: True)
    # Degrades to the given order rather than breaking routing.
    assert _rank_by_reputation(("a", "b")) == ("a", "b")


def test_tools_for_still_returns_a_route(fresh_rep):
    # Smoke: the integrated path runs end to end and exposes tools.
    from reyes_agent.routing.capability import tools_for

    route = tools_for("open chrome and search the web")
    assert route.tools and isinstance(route.tools, tuple)
