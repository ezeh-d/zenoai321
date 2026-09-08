"""Regression tests for the Teaching Whiteboard (checkpointed lesson engine)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _isolated_vault():
    """Context-manager-free helper: returns (tempdir, restore) for VAULT_PATH."""
    from reyes_agent import config, teaching

    raw = tempfile.TemporaryDirectory()
    prior_vault = config.VAULT_PATH
    prior_publish = teaching._publish
    config.VAULT_PATH = Path(raw.name) / "vault"
    teaching._publish = lambda *_args, **_kwargs: None

    def restore():
        teaching._publish = prior_publish
        config.VAULT_PATH = prior_vault
        raw.cleanup()

    return restore


def test_lesson_checkpoints_and_resumes_across_turns() -> None:
    from reyes_agent import teaching

    restore = _isolated_vault()
    try:
        started = teaching.start("Python", ["Variables", "Loops", "Functions"])
        assert started["lesson_index"] == 0
        assert started["lesson_title"] == "Variables"
        assert started["status"] == "active"

        with_block = teaching.push_block("Python", "explanation", "A variable stores a value.")
        assert with_block["blocks"][-1]["kind"] == "explanation"

        after_lesson_one = teaching.complete_lesson("Python")
        assert after_lesson_one["completed"] == ["Variables"]
        assert after_lesson_one["lesson_index"] == 1
        assert after_lesson_one["lesson_title"] == "Loops"
        # Blocks reset for the new lesson -- the board shows the CURRENT
        # lesson, not an ever-growing dump of every lesson taught so far.
        assert after_lesson_one["blocks"] == []
        assert after_lesson_one["status"] == "active"

        # Simulate a brand new conversation turn resuming the same subject:
        # status() must reflect real, already-persisted progress.
        resumed = teaching.status("python")  # subject_key is case/whitespace insensitive
        assert resumed["lesson_index"] == 1
        assert resumed["completed"] == ["Variables"]
    finally:
        restore()


def test_session_never_claims_completion_while_lessons_remain() -> None:
    from reyes_agent import teaching

    restore = _isolated_vault()
    try:
        teaching.start("music theory", ["Intervals", "Chords"])
        after_first = teaching.complete_lesson("music theory")
        assert after_first["status"] == "active"
        after_second = teaching.complete_lesson("music theory")
        assert after_second["status"] == "complete"
        assert set(after_second["completed"]) == {"Intervals", "Chords"}
        # Completing an already-complete session is a safe no-op, not an error.
        again = teaching.complete_lesson("music theory")
        assert again["status"] == "complete"
    finally:
        restore()


def test_push_block_requires_an_existing_session_and_bounds_kind() -> None:
    from reyes_agent import teaching

    restore = _isolated_vault()
    try:
        assert teaching.push_block("nothing started", "explanation", "text") is None
        teaching.start("Chemistry", ["Atoms"])
        snapshot = teaching.push_block("Chemistry", "not-a-real-kind", "falls back safely")
        assert snapshot["blocks"][-1]["kind"] == "explanation"
        snapshot2 = teaching.push_block("Chemistry", "code", "x = 1")
        assert snapshot2["blocks"][-1]["kind"] == "code"
    finally:
        restore()


def test_latest_returns_the_most_recently_touched_session() -> None:
    from reyes_agent import teaching

    restore = _isolated_vault()
    try:
        teaching.start("Old Topic", ["A"])
        teaching.start("New Topic", ["B", "C"])
        current = teaching.latest()
        assert current["subject"] == "new topic"
        teaching.push_block("old topic", "explanation", "touch it again")
        current2 = teaching.latest()
        assert current2["subject"] == "old topic"
    finally:
        restore()


def test_pause_and_resume_do_not_affect_a_completed_session() -> None:
    from reyes_agent import teaching

    restore = _isolated_vault()
    try:
        teaching.start("Topic", ["Only lesson"])
        teaching.complete_lesson("Topic")
        paused = teaching.pause("Topic")
        assert paused["status"] == "complete"
    finally:
        restore()


def test_directive_triggers_only_for_explicit_lesson_language() -> None:
    from reyes_agent import teaching

    assert teaching.directive("Teach me Python.")
    assert teaching.directive("Give me a full course on thermodynamics.")
    assert not teaching.directive("What's the weather like?")
    assert not teaching.directive("Can you remember my favourite colour?")


def test_teaching_directive_is_added_to_the_existing_provider_turn() -> None:
    from reyes_agent import agent
    from reyes_agent.provider import AgentTurn

    captured: list[str] = []
    original_run_turn = agent.run_turn
    original_tools = agent.tool_definitions

    def fake_turn(_history, *, system, tools, on_text, cancel_check, task_kind):
        captured.append(system)
        on_text("Lesson ready.")
        return AgentTurn(text="Lesson ready.")

    try:
        agent.run_turn = fake_turn
        agent.tool_definitions = lambda **_kwargs: []
        history = [{"role": "user", "content": "Teach me everything about Python."}]
        agent.run_agent(history)
    finally:
        agent.run_turn = original_run_turn
        agent.tool_definitions = original_tools

    assert len(captured) == 1
    assert "Teaching Whiteboard:" in captured[0]


def test_teaching_board_tool_is_registered_core_and_kate_can_use_it() -> None:
    from reyes_agent.tools import CORE_TOOL_NAMES, TOOLS, tool_definitions
    from reyes_agent.tools import subagents

    assert "teaching_board" in TOOLS
    assert "teaching_board" in CORE_TOOL_NAMES
    core = {tool["name"] for tool in tool_definitions()}
    assert "teaching_board" in core
    kate = subagents._SPECIALISTS["kate"]
    assert "teaching_board" in kate["tools"]


def test_teaching_board_tool_reports_missing_session_without_raising() -> None:
    from reyes_agent.tools.design import teaching_board

    restore = _isolated_vault()
    try:
        result = teaching_board("push_block", "Never Started", kind="explanation", content="x")
        assert "No active teaching session" in result
        started = teaching_board("start", "Geometry", syllabus=["Angles", "Triangles"])
        assert "geometry" in started.casefold()
        blocked = teaching_board("push_block", "Geometry", kind="explanation", content="")
        assert "content is required" in blocked
    finally:
        restore()


def test_teaching_panel_is_routed_and_registered() -> None:
    from reyes_agent import panels

    assert panels.route_tool("teaching_board") == "teaching"
    decision = panels.decide(tool="teaching_board")
    assert decision["panel"] == "teaching"
    assert panels.PANELS["teaching"]["support"] == "live"


def test_notepad_target_and_progress_persist_and_reset_on_lesson_advance() -> None:
    from reyes_agent import teaching

    restore = _isolated_vault()
    try:
        started = teaching.start("Python", ["Variables", "Loops"], target="notepad")
        assert started["target"] == "notepad"
        assert started["notepad_written"] == 0

        teaching.push_block("Python", "title", "Variables")
        teaching.push_block("Python", "explanation", "A variable stores a value.")
        after_write = teaching.set_notepad_written("Python", 1)
        assert after_write["notepad_written"] == 1
        rendered = teaching.format_status(after_write)
        assert "Notepad: 1 block(s) written, 1 pending" in rendered

        # Advancing the lesson clears the board AND the notepad progress --
        # a stale count from lesson 1 must never carry into lesson 2.
        after_lesson = teaching.complete_lesson("Python")
        assert after_lesson["notepad_written"] == 0
        assert after_lesson["blocks"] == []
    finally:
        restore()


def test_non_notepad_session_has_no_notepad_target() -> None:
    from reyes_agent import teaching

    restore = _isolated_vault()
    try:
        started = teaching.start("History", ["Ancient Rome"])
        assert started["target"] == ""
        rendered = teaching.format_status(started)
        assert "Notepad:" not in rendered
    finally:
        restore()


def test_teaching_directive_mentions_notepad_only_when_asked() -> None:
    from reyes_agent import teaching

    with_notepad = teaching.directive("Teach me Python in Notepad.")
    assert "write_lesson_to_notepad" in with_notepad
    assert "target='notepad'" in with_notepad

    without_notepad = teaching.directive("Teach me Python.")
    assert "write_lesson_to_notepad" not in without_notepad
    assert "notepad" not in without_notepad.casefold()


def test_write_lesson_to_notepad_requires_a_notepad_targeted_session() -> None:
    from reyes_agent.tools.teaching_notepad import write_lesson_to_notepad

    restore = _isolated_vault()
    try:
        assert "No active teaching session" in write_lesson_to_notepad("Nothing Started")
        from reyes_agent import teaching
        teaching.start("Chemistry", ["Atoms"])  # no target='notepad'
        result = write_lesson_to_notepad("Chemistry")
        assert "wasn't started for Notepad" in result
    finally:
        restore()


def test_write_lesson_to_notepad_writes_only_pending_blocks_once(monkeypatch) -> None:
    from reyes_agent import teaching
    from reyes_agent.computer import window
    from reyes_agent.tools import hands_tools
    from reyes_agent.tools.teaching_notepad import write_lesson_to_notepad

    restore = _isolated_vault()
    try:
        teaching.start("Python", ["Variables"], target="notepad")
        teaching.push_block("Python", "title", "Variables")
        teaching.push_block("Python", "code", "x = 10")

        monkeypatch.setattr(window, "find_by_title", lambda _title: [(123, "Untitled - Notepad")])
        monkeypatch.setattr(window, "is_foreground", lambda _handle: True)
        typed = []
        monkeypatch.setattr(hands_tools, "type_text",
                            lambda text: (typed.append(text), '{"ok": true}')[1])
        monkeypatch.setattr(hands_tools, "press_keys", lambda _keys: '{"ok": true}')

        result = write_lesson_to_notepad("Python")
        assert "Wrote 2 new block(s)" in result
        assert len(typed) == 2
        assert "Variables" in typed[0] and "x = 10" in typed[1]

        # Calling again with nothing new pushed must NOT retype anything.
        typed.clear()
        again = write_lesson_to_notepad("Python")
        assert "Nothing new to write" in again
        assert typed == []
    finally:
        restore()


def test_write_lesson_to_notepad_stops_and_checkpoints_on_a_failed_type(monkeypatch) -> None:
    from reyes_agent import teaching
    from reyes_agent.computer import window
    from reyes_agent.tools import hands_tools
    from reyes_agent.tools.teaching_notepad import write_lesson_to_notepad

    restore = _isolated_vault()
    try:
        teaching.start("Python", ["Variables"], target="notepad")
        teaching.push_block("Python", "title", "Variables")
        teaching.push_block("Python", "explanation", "A variable stores a value.")
        teaching.push_block("Python", "code", "x = 10")

        monkeypatch.setattr(window, "find_by_title", lambda _title: [(123, "Untitled - Notepad")])
        monkeypatch.setattr(window, "is_foreground", lambda _handle: True)
        monkeypatch.setattr(hands_tools, "press_keys", lambda _keys: '{"ok": true}')

        calls = {"n": 0}

        def flaky_type(_text):
            calls["n"] += 1
            if calls["n"] == 2:
                return '{"ok": false, "detail": "focus moved to another window"}'
            return '{"ok": true}'

        monkeypatch.setattr(hands_tools, "type_text", flaky_type)

        result = write_lesson_to_notepad("Python")
        assert "Stopped after writing 1 new block(s)" in result
        assert "focus moved" in result

        snapshot = teaching.status("Python")
        assert snapshot["notepad_written"] == 1  # the failed 2nd block was never counted

        # A retry only sends the still-pending blocks (2 and 3), never block 1 again.
        calls["n"] = 0
        monkeypatch.setattr(hands_tools, "type_text", lambda _text: '{"ok": true}')
        retried = write_lesson_to_notepad("Python")
        assert "Wrote 2 new block(s)" in retried
        assert teaching.status("Python")["notepad_written"] == 3
    finally:
        restore()


def test_write_lesson_to_notepad_reports_when_notepad_cannot_be_focused(monkeypatch) -> None:
    from reyes_agent import teaching
    from reyes_agent.computer import window
    from reyes_agent.tools import system as system_tools
    from reyes_agent.tools.teaching_notepad import write_lesson_to_notepad

    restore = _isolated_vault()
    try:
        teaching.start("Python", ["Variables"], target="notepad")
        teaching.push_block("Python", "title", "Variables")

        monkeypatch.setattr(window, "find_by_title", lambda _title: [])
        monkeypatch.setattr(system_tools, "open_app", lambda _name: "Couldn't find an app matching 'notepad'.")

        result = write_lesson_to_notepad("Python")
        assert "could not bring Notepad to the foreground" in result
        assert teaching.status("Python")["notepad_written"] == 0
    finally:
        restore()


def test_write_lesson_to_notepad_tool_is_registered_and_reachable_from_kate() -> None:
    from reyes_agent.tools import TOOLS
    from reyes_agent.tools import subagents

    assert "write_lesson_to_notepad" in TOOLS
    kate = subagents._SPECIALISTS["kate"]
    assert "write_lesson_to_notepad" in kate["tools"]


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
