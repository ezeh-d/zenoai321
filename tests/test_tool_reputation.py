"""Contracts for rolling-window tool reputation."""

from __future__ import annotations

from reyes_agent.tool_reputation import ToolReputation, WINDOW


def test_unseen_tool_has_zero_confidence():
    r = ToolReputation()
    rep = r.reputation("ghost")
    assert rep["samples"] == 0 and rep["confidence"] == 0.0
    assert rep["success_rate"] == 0.0 and rep["recent_failures"] == 0


def test_success_rate_and_confidence_rise_with_evidence():
    r = ToolReputation()
    for _ in range(2):
        r.record("a", True)
    rep_small = r.reputation("a")
    r2 = ToolReputation()
    for _ in range(200):
        r2.record("a", True)
    rep_big = r2.reputation("a")
    # Both are 100% raw, but 200/200 is more trustworthy than 2/2.
    assert rep_small["success_rate"] == 1.0 and rep_big["success_rate"] == 1.0
    assert rep_big["confidence"] > rep_small["confidence"]


def test_rolling_window_forgets_old_outcomes():
    r = ToolReputation()
    # Fill the window with failures, then flood with successes past the window.
    for _ in range(WINDOW):
        r.record("t", False)
    for _ in range(WINDOW):
        r.record("t", True)
    rep = r.reputation("t")
    # The early failures have decayed out entirely.
    assert rep["samples"] == WINDOW and rep["success_rate"] == 1.0
    assert rep["recent_failures"] == 0


def test_recent_failure_streak_counted():
    r = ToolReputation()
    r.record("t", True)
    r.record("t", True)
    r.record("t", False)
    r.record("t", False)
    assert r.reputation("t")["recent_failures"] == 2
    r.record("t", True)
    assert r.reputation("t")["recent_failures"] == 0


def test_latency_percentiles():
    r = ToolReputation()
    for ms in [10, 20, 30, 40, 100]:
        r.record("t", True, latency_ms=ms)
    rep = r.reputation("t")
    assert rep["median_latency_ms"] == 30
    assert rep["p95_latency_ms"] >= 40  # near the top of the sample


def test_best_of_prefers_proven_tool():
    r = ToolReputation()
    for _ in range(50):
        r.record("reliable", True)
    for i in range(50):
        r.record("flaky", i % 2 == 0)  # ~50%
    assert r.best_of(["flaky", "reliable"]) == "reliable"


def test_best_of_all_unseen_returns_first():
    r = ToolReputation()
    assert r.best_of(["x", "y", "z"]) == "x"


def test_all_reputations_sorted_by_confidence():
    r = ToolReputation()
    for _ in range(30):
        r.record("good", True)
    for _ in range(30):
        r.record("bad", False)
    reps = r.all_reputations()
    assert [x["tool"] for x in reps][0] == "good"
    assert reps[0]["confidence"] > reps[-1]["confidence"]


def test_record_never_raises_on_bad_input():
    r = ToolReputation()
    r.record("", True)          # empty name ignored
    r.record(None, True)        # type: ignore[arg-type]
    assert r.reputation("")["samples"] == 0


def test_confidence_drops_when_failures_appear():
    r = ToolReputation()
    for _ in range(20):
        r.record("t", True)
    high = r.reputation("t")["confidence"]
    for _ in range(20):
        r.record("t", False)
    low = r.reputation("t")["confidence"]
    assert low < high
