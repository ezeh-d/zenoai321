"""Tests for Claude's awareness/anticipation handoff and CODEX integration."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _history_db() -> Path:
    path = Path(tempfile.mkdtemp()) / "state.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE activity_log (id INTEGER PRIMARY KEY, ts REAL, day TEXT, app TEXT, title TEXT, idle INTEGER)")
        conn.execute("CREATE TABLE calendar_events (id INTEGER PRIMARY KEY, title TEXT, due_at REAL, notes TEXT, notified INTEGER DEFAULT 0)")
    return path


def test_awareness_reads_the_real_calendar_schema_and_existing_activity() -> None:
    from reyes_agent import activity_monitor, awareness

    path = _history_db()
    now = time.time()
    with sqlite3.connect(path) as conn:
        conn.executemany(
            "INSERT INTO activity_log (ts, day, app, title, idle) VALUES (?, '2026-08-10', ?, ?, 0)",
            [(now - 120, "code.exe", "private title one"), (now - 60, "code.exe", "private title two")],
        )
        conn.execute("INSERT INTO calendar_events (title, due_at) VALUES (?, ?)", ("Owner review", now + 1800))

    original_db = awareness._DB
    original_foreground = activity_monitor.foreground_app
    original_idle = activity_monitor._idle_seconds
    try:
        awareness._DB = path
        activity_monitor.foreground_app = lambda: ("code.exe", "Current private title")
        activity_monitor._idle_seconds = lambda: 4.0
        situation = awareness.Situation()
        awareness._read_activity(situation)
        awareness._read_environment(situation)
        assert situation.app == "code.exe"
        assert situation.focus_minutes is not None
        assert situation.next_event == "Owner review"
        assert 28 <= situation.next_event_minutes <= 30
    finally:
        awareness._DB = original_db
        activity_monitor.foreground_app = original_foreground
        activity_monitor._idle_seconds = original_idle
        awareness.reset()


def test_anticipation_uses_the_newest_bounded_samples_and_never_titles() -> None:
    from reyes_agent import anticipation

    path = _history_db()
    now = time.time()
    weekday = time.localtime(now).tm_wday
    hour = time.localtime(now).tm_hour
    with sqlite3.connect(path) as conn:
        for index in range(8):
            conn.execute(
                "INSERT INTO activity_log (ts, day, app, title, idle) VALUES (?, '', 'chrome.exe', ?, 0)",
                (now - 3600 - index, f"secret old {index}"),
            )
        for index in range(3):
            conn.execute(
                "INSERT INTO activity_log (ts, day, app, title, idle) VALUES (?, '', 'msedge.exe', ?, 0)",
                (now - 2 + index * 0.1, f"secret recent {index}"),
            )

    original_db, original_rows = anticipation._DB, anticipation._MAX_ROWS
    original_samples = anticipation.MIN_SAMPLES
    try:
        anticipation._DB = path
        anticipation._MAX_ROWS = 3
        anticipation.MIN_SAMPLES = 3
        anticipation.reset()
        prediction = anticipation.predict_app(weekday=weekday, hour=hour)
        assert prediction is not None
        assert prediction.value == "Edge"
        assert prediction.observations == 3
        assert "secret" not in prediction.basis
    finally:
        anticipation._DB = original_db
        anticipation._MAX_ROWS = original_rows
        anticipation.MIN_SAMPLES = original_samples
        anticipation.reset()


def test_awareness_and_anticipation_are_prompt_context_not_a_second_brain() -> None:
    from reyes_agent import agent, anticipation, awareness

    captured: dict[str, str] = {}
    original_turn = agent.run_turn
    original_awareness = awareness.directive
    original_anticipation = anticipation.directive
    try:
        awareness.directive = lambda: "[MEASURED SITUATION]"
        anticipation.directive = lambda: "[EVIDENCE PATTERN]"

        def fake_turn(_history, *, system, **_kwargs):
            captured["system"] = system
            return SimpleNamespace(wants_tool=False, text="Ready.")

        agent.run_turn = fake_turn
        history = [{"role": "user", "content": "hello"}]
        agent.run_agent(history)
        assert "[MEASURED SITUATION]" in captured["system"]
        assert "[EVIDENCE PATTERN]" in captured["system"]
        assert history[-1]["content"] == "Ready."
    finally:
        agent.run_turn = original_turn
        awareness.directive = original_awareness
        anticipation.directive = original_anticipation


def test_current_situation_tool_exposes_evidence_and_readiness() -> None:
    from reyes_agent.tools.intelligence_tools import current_situation

    state = json.loads(current_situation())
    assert "observed" in state
    assert "anticipation" in state
    assert "readiness" in state["anticipation"]


def test_hud_projects_awareness_without_starting_a_sensor() -> None:
    hud = (ROOT / "reyes_agent" / "static" / "jarvis_hud.js").read_text(encoding="utf-8")
    awareness_source = (ROOT / "reyes_agent" / "awareness.py").read_text(encoding="utf-8")
    anticipation_source = (ROOT / "reyes_agent" / "anticipation.py").read_text(encoding="utf-8")

    assert "SITUATIONAL AWARENESS" in hud
    assert "NO CONFIDENT PATTERN" in hud
    assert "setInterval" not in awareness_source
    assert "Thread(" not in awareness_source
    assert "setInterval" not in anticipation_source
    assert "Thread(" not in anticipation_source
    assert "SELECT ts, app, idle" in anticipation_source
    assert "SELECT ts, app, title" not in anticipation_source


def _run_all() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
