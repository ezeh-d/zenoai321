"""Situational awareness and anticipation.

CLAUDE owns this file. The thing being defended here is honesty: an
assistant that guesses at your habits and states it confidently is worse
than one that says nothing, so most of these tests assert that ZENO STAYS
QUIET when the evidence is thin.

Run: `.venv/Scripts/python.exe tests/test_awareness.py`
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _fixture_db(rows: list[tuple[float, str, int]]) -> Path:
    """A throwaway activity_log so tests never depend on the real machine."""
    raw = Path(tempfile.mkdtemp(prefix="zeno-aware-")) / "state.db"
    conn = sqlite3.connect(raw)
    conn.execute("CREATE TABLE activity_log (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "ts REAL, day TEXT, app TEXT, title TEXT, idle INTEGER)")
    conn.executemany("INSERT INTO activity_log (ts, day, app, title, idle) VALUES (?,?,?,?,?)",
                     [(ts, "", app, "SECRET DOCUMENT TITLE", idle) for ts, app, idle in rows])
    conn.commit()
    conn.close()
    return raw


def _with_db(module, path: Path):
    previous = module._DB
    module._DB = path
    module.reset()
    return previous


# --- anticipation: evidence discipline -----------------------------------

def test_no_history_means_no_prediction() -> None:
    """A fresh install must not pretend to know the owner."""
    from reyes_agent import anticipation

    previous = _with_db(anticipation, _fixture_db([]))
    try:
        assert anticipation.predict_app() is None
        assert anticipation.predict_next("chrome.exe") is None
        assert anticipation.quiet_hours() == []
        ready = anticipation.readiness()
        assert ready["ready"] is False and ready["total_samples"] == 0
        assert anticipation.directive() == "", "silence is the correct output of an untrained model"
    finally:
        anticipation._DB = previous
        anticipation.reset()


def test_thin_evidence_is_refused_not_guessed() -> None:
    from reyes_agent import anticipation

    # One sample short of the threshold, all the same app: tempting, but
    # not enough to claim a habit.
    base = datetime.now().replace(minute=0, second=0, microsecond=0)
    rows = [((base - timedelta(days=d)).timestamp(), "chrome.exe", 0)
            for d in range(0, (anticipation.MIN_SAMPLES - 1) * 7, 7)]
    previous = _with_db(anticipation, _fixture_db(rows))
    try:
        assert len(rows) < anticipation.MIN_SAMPLES
        assert anticipation.predict_app(base.weekday(), base.hour) is None
    finally:
        anticipation._DB = previous
        anticipation.reset()


def test_a_real_pattern_is_learned_with_honest_confidence() -> None:
    from reyes_agent import anticipation

    base = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
    # 8 Mondays at 10:00: Chrome 6, Slack 2 -> 75%, above both thresholds.
    rows = []
    for index in range(8):
        day = base - timedelta(days=7 * index)
        rows.append((day.timestamp(), "chrome.exe" if index >= 2 else "Slack.exe", 0))
    previous = _with_db(anticipation, _fixture_db(rows))
    try:
        prediction = anticipation.predict_app(base.weekday(), 10)
        assert prediction is not None, "8 samples at 75% must produce a prediction"
        assert prediction.value == "Chrome"
        assert 0.7 <= prediction.confidence <= 0.8
        assert prediction.observations == 8
        # The evidence is stated, not just the conclusion.
        assert "of 8 samples" in prediction.basis
    finally:
        anticipation._DB = previous
        anticipation.reset()


def test_a_split_habit_is_not_reported_as_a_habit() -> None:
    """Four apps evenly at one hour is not a routine."""
    from reyes_agent import anticipation

    base = datetime.now().replace(hour=15, minute=0, second=0, microsecond=0)
    apps = ["chrome.exe", "Slack.exe", "Code.exe", "explorer.exe"]
    rows = [((base - timedelta(days=7 * i)).timestamp(), apps[i % 4], 0) for i in range(12)]
    previous = _with_db(anticipation, _fixture_db(rows))
    try:
        prediction = anticipation.predict_app(base.weekday(), 15)
        assert prediction is None, "25% each is not a pattern worth stating"
    finally:
        anticipation._DB = previous
        anticipation.reset()


def test_transitions_need_adjacent_samples_not_just_order() -> None:
    """Two apps either side of a six-hour gap are not a habit."""
    from reyes_agent import anticipation

    now = time.time()
    far_apart = []
    for index in range(10):
        far_apart.append((now - (index * 2 * 3600) - 3600, "chrome.exe", 0))
        far_apart.append((now - (index * 2 * 3600), "Slack.exe", 0))
    previous = _with_db(anticipation, _fixture_db(sorted(far_apart)))
    try:
        assert anticipation.predict_next("chrome.exe") is None, \
            "samples an hour apart must not count as a transition"
    finally:
        anticipation._DB = previous
        anticipation.reset()

    # Adjacent samples DO count.
    close = []
    for index in range(10):
        close.append((now - (index * 300) - 60, "chrome.exe", 0))
        close.append((now - (index * 300), "Slack.exe", 0))
    previous = _with_db(anticipation, _fixture_db(sorted(close)))
    try:
        prediction = anticipation.predict_next("chrome.exe")
        assert prediction is not None and prediction.value == "Slack"
        assert prediction.observations >= anticipation.MIN_TRANSITIONS
    finally:
        anticipation._DB = previous
        anticipation.reset()


def test_idle_samples_break_the_chain() -> None:
    from reyes_agent import anticipation

    now = time.time()
    rows = []
    for index in range(10):
        rows.append((now - (index * 300) - 60, "chrome.exe", 0))
        rows.append((now - (index * 300) - 30, "chrome.exe", 1))   # went idle
        rows.append((now - (index * 300), "Slack.exe", 0))
    previous = _with_db(anticipation, _fixture_db(sorted(rows)))
    try:
        assert anticipation.predict_next("chrome.exe") is None, \
            "an idle gap means he walked away, not that he switched apps"
    finally:
        anticipation._DB = previous
        anticipation.reset()


def test_window_titles_are_never_learned_from() -> None:
    """A title can name a document, a client, a message. Counts only."""
    from reyes_agent import anticipation

    source = (ROOT / "reyes_agent" / "anticipation.py").read_text(encoding="utf-8")
    assert "title" not in source.split("SELECT ts, app, idle")[1][:200].lower(), \
        "the learning query must not select titles"

    base = datetime.now().replace(hour=11, minute=0, second=0, microsecond=0)
    rows = [((base - timedelta(days=7 * i)).timestamp(), "chrome.exe", 0) for i in range(10)]
    previous = _with_db(anticipation, _fixture_db(rows))   # fixture stores a secret title
    try:
        model = anticipation.learn(force=True)
        blob = repr(model.as_dict()) + repr(dict(model.slots)) + repr(dict(model.transitions))
        assert "SECRET DOCUMENT TITLE" not in blob
        prediction = anticipation.predict_app(base.weekday(), 11)
        assert prediction and "SECRET" not in prediction.basis
    finally:
        anticipation._DB = previous
        anticipation.reset()


# --- awareness: honest observation ---------------------------------------

def test_a_sparse_history_cannot_claim_a_continuous_session() -> None:
    """The measured bug: a 10-minute gap threshold produced a claim of 65
    hours of continuous work from samples ~6.6 minutes apart."""
    from reyes_agent import awareness

    now = time.time()
    # Samples spread far apart -- real elapsed time, but no proof of
    # continuity between them.
    rows = [(now - (index * 600), "chrome.exe", 0) for index in range(30)]
    previous = _with_db(awareness, _fixture_db(rows))
    try:
        situation = awareness.observe(force=True)
        if situation.session_minutes is not None:
            assert situation.session_minutes < 30, \
                f"claimed {situation.session_minutes}m of continuity from 10-minute gaps"
    finally:
        awareness._DB = previous
        awareness.reset()


def test_contiguous_samples_do_yield_a_session() -> None:
    from reyes_agent import awareness

    now = time.time()
    # 40 contiguous samples, then an IDLE one marking where the stretch
    # began. Without that boundary the walk runs out of rows and awareness
    # correctly refuses to name a start it cannot see -- so the fixture has
    # to supply the end of the session, not just its middle.
    rows = [(now - (index * 60), "chrome.exe", 0) for index in range(40)]
    rows.append((now - (40 * 60), "chrome.exe", 1))
    previous = _with_db(awareness, _fixture_db(rows))
    try:
        situation = awareness.observe(force=True)
        if situation.app == "chrome.exe":     # only when this machine agrees
            assert situation.session_minutes is not None, "a bounded stretch must be measurable"
            assert 30 <= situation.session_minutes <= 45, situation.session_minutes
    finally:
        awareness._DB = previous
        awareness.reset()


def test_the_situation_summary_omits_what_it_does_not_know() -> None:
    from reyes_agent import awareness

    situation = awareness.Situation(hour=9, weekday="Monday", part_of_day="morning")
    summary = situation.summary()
    assert "Monday" in summary and "morning" in summary
    for absent in ("None", "battery", "task", "continuously"):
        assert absent not in summary, f"summary invented '{absent}' from no data"


def test_awareness_states_what_it_cannot_sense() -> None:
    from reyes_agent import awareness

    cannot = " ".join(awareness.cannot_sense()).lower()
    for claim in ("location", "biometric", "camera", "room"):
        assert claim in cannot, f"'{claim}' must be named as beyond ZENO's senses"


def test_observation_is_cached_so_it_costs_nothing_per_turn() -> None:
    from reyes_agent import awareness

    awareness.observe(force=True)
    started = time.perf_counter()
    for _ in range(500):
        awareness.observe()
    per_call_ms = (time.perf_counter() - started) * 1000 / 500
    assert per_call_ms < 0.5, f"cached observe costs {per_call_ms:.3f}ms"


def test_directives_are_context_not_instructions_to_narrate() -> None:
    from reyes_agent import anticipation, awareness

    directive = awareness.directive()
    if directive:
        assert "do not narrate it back" in directive
        assert "never claim to sense anything not listed" in directive
    pattern = anticipation.directive()
    if pattern:
        assert "Context only" in pattern
        assert "never present a pattern as certainty" in pattern


def test_awareness_never_breaks_a_turn() -> None:
    """A broken sensor must degrade to silence, not raise."""
    from reyes_agent import anticipation, awareness

    previous_a = _with_db(awareness, Path("does/not/exist.db"))
    previous_b = _with_db(anticipation, Path("does/not/exist.db"))
    try:
        assert isinstance(awareness.observe(force=True), awareness.Situation)
        assert isinstance(awareness.directive(), str)
        assert anticipation.directive() == ""
        assert anticipation.readiness()["ready"] is False
    finally:
        awareness._DB = previous_a
        anticipation._DB = previous_b
        awareness.reset()
        anticipation.reset()


def test_the_tools_are_registered_and_answer_honestly() -> None:
    from reyes_agent.tools import TOOLS

    assert "current_situation_report" in TOOLS and "learned_patterns" in TOOLS
    report = TOOLS["current_situation_report"].func()
    assert "cannot sense" in report.lower()
    patterns = TOOLS["learned_patterns"].func()
    assert "samples" in patterns.lower()
    # Never claims more than counts support.
    assert "definitely" not in patterns.lower() and "always" not in patterns.lower()


def test_quiet_hours_are_reported_as_real_ranges() -> None:
    """[0..8, 19..23] must not print as '00:00-23:00'."""
    from reyes_agent.tools import TOOLS
    from reyes_agent import anticipation

    real = anticipation.quiet_hours
    anticipation.quiet_hours = lambda: [0, 1, 2, 3, 19, 20, 21]
    try:
        text = TOOLS["learned_patterns"].func()
        if "rarely active" in text:
            assert "00:00-23:00" not in text, "two ranges collapsed into 'always quiet'"
            assert "00:00-04:00" in text and "19:00-22:00" in text
    finally:
        anticipation.quiet_hours = real


def _run_all() -> int:
    tests = [v for n, v in sorted(globals().items()) if n.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        started = time.time()
        try:
            test()
            print(f"PASS {test.__name__} ({time.time() - started:.2f}s)")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
