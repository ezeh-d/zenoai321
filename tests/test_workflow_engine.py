"""Offline coverage for owner-taught workflow recording and replay."""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reyes_agent import permissions
from reyes_agent.workflow_engine import (
    MODES,
    TEACH_MODE_PAUSED,
    TEACH_MODE_RECORDING,
    TEACH_MODE_REVIEW,
    WORKFLOW_COMPLETED,
    WORKFLOW_READY,
    WORKFLOW_WAITING_FOR_CONFIRMATION,
    WORKFLOW_WAITING_FOR_INPUT,
    WorkflowEngine,
)


class FakeRecorder:
    def __init__(self, _engine) -> None:
        self.started = False
        self.paused = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False


class FakeContext:
    def check_cancelled(self) -> None:
        return None

    def progress(self, *_args, **_kwargs) -> None:
        return None

    def wait(self, _seconds: float) -> None:
        return None


def make_engine(root: Path) -> WorkflowEngine:
    return WorkflowEngine(root=root, recorder_factory=FakeRecorder, memory_writer=lambda name, count: f"memory-{name}-{count}")


def test_teach_modes_review_and_save_are_explicit() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        engine = make_engine(Path(temp_dir))
        assert "Teach Mode is recording" in engine.start_teaching()
        assert engine.status()["mode"] == TEACH_MODE_RECORDING
        engine.record_action({"op": "ensure_app", "app": "chrome", "expected_app": "chrome.exe"})
        engine.record_action({"op": "hotkey", "keys": "ctrl+l"})
        assert engine.pause_teaching().startswith("Teach Mode paused")
        assert engine.status()["mode"] == TEACH_MODE_PAUSED
        assert engine.resume_teaching() == "Teach Mode resumed."
        assert "What should I call" in engine.stop_teaching()
        assert engine.status()["mode"] == TEACH_MODE_REVIEW
        review = engine.review()
        assert "Open or activate chrome" in review
        assert "CTRL+L" in review
        assert "Saved and approved" in engine.save("Morning Report")
        assert engine.status()["mode"] == WORKFLOW_READY
        saved = engine.list_workflows()
        assert saved[0]["name"] == "Morning Report"
        assert (Path(temp_dir) / "morning-report.json").exists()


def test_text_and_browser_fill_values_are_never_saved() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        engine = make_engine(Path(temp_dir))
        engine.start_teaching()
        engine.record_tool_action({"tool": "browser_fill", "input": {"value": "private-password"}})
        engine.record_tool_action({"tool": "browser_open", "input": {"url": "https://example.com/path?token=private"}})
        engine.stop_teaching()
        review = engine.review()
        assert "private-password" not in review
        assert "input_required" not in review
        assert "variable text manually" in review
        engine.save("Private-safe")
        saved = (Path(temp_dir) / "private-safe.json").read_text(encoding="utf-8")
        assert "private-password" not in saved
        assert "token=private" not in saved
        assert "https://example.com/path" in saved


def test_replay_stops_for_input_then_resumes_from_the_next_step() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        workflow = {
            "id": "demo", "name": "Demo", "approved_at": time.time(), "steps": [
                {"op": "focus", "app": "chrome"},
                {"op": "input_required", "app": "chrome"},
                {"op": "focus", "app": "winword.exe"},
            ],
        }
        (root / "demo.json").write_text(json.dumps(workflow), encoding="utf-8")
        engine = make_engine(root)
        engine._run_job(FakeContext(), "demo", 0)  # exact managed-task body, no desktop action involved
        assert engine.status()["mode"] == WORKFLOW_WAITING_FOR_INPUT
        assert engine.status()["index"] == 2
        engine._run_job(FakeContext(), "demo", 2)
        assert engine.status()["mode"] == WORKFLOW_COMPLETED


def test_pause_is_applied_after_a_completed_step_without_replaying_it() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / "safe-pause.json").write_text(json.dumps({
            "id": "safe-pause", "name": "Safe pause", "approved_at": time.time(),
            "steps": [{"op": "focus", "app": "chrome"}, {"op": "focus", "app": "word"}],
        }), encoding="utf-8")
        engine = make_engine(root)
        engine._pause_requested.set()
        engine._run_job(FakeContext(), "safe-pause", 0)
        assert engine.status()["mode"] == WORKFLOW_WAITING_FOR_INPUT
        assert engine.status()["index"] == 1


def test_manual_workflow_waits_for_owner_visual_verification_before_completion() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / "visual-check.json").write_text(json.dumps({
            "id": "visual-check", "name": "Visual check", "approved_at": time.time(), "steps": [],
            "requires_owner_visual_confirmation": True,
        }), encoding="utf-8")
        engine = make_engine(root)
        engine._run_job(FakeContext(), "visual-check", 0)
        assert engine.status()["mode"] == WORKFLOW_WAITING_FOR_INPUT
        assert engine.status()["awaiting_owner_visual_confirmation"] is True
        engine._runtime["owner_visual_confirmed"] = True
        engine._run_job(FakeContext(), "visual-check", 0)
        assert engine.status()["mode"] == WORKFLOW_COMPLETED


def test_permission_requirement_enters_confirm_mode_before_replay() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / "clicker.json").write_text(json.dumps({
            "id": "clicker", "name": "Clicker", "approved_at": time.time(),
            "steps": [{"op": "desktop_click", "x": 0.5, "y": 0.5, "button": "left"}],
        }), encoding="utf-8")
        engine = make_engine(root)
        original = permissions.state_for
        permissions.state_for = lambda capability: permissions.CONFIRM if capability == "desktop_automation" else permissions.ENABLED
        try:
            message = engine.start_run("Clicker")
        finally:
            permissions.state_for = original
        assert "needs confirmation" in message
        assert engine.status()["mode"] == WORKFLOW_WAITING_FOR_CONFIRMATION


def test_all_requested_modes_are_exported() -> None:
    assert len(MODES) == 13
    assert WORKFLOW_WAITING_FOR_CONFIRMATION in MODES
    assert WORKFLOW_COMPLETED in MODES


def test_voice_tools_web_api_and_mini_orb_share_one_workflow_runtime() -> None:
    from reyes_agent.tools import TOOLS
    from reyes_agent.web import app

    assert {"workflow_teach", "workflow_run", "workflow_confirm"}.issubset(TOOLS)
    assert TOOLS["workflow_confirm"].requires_confirmation is True
    assert permissions.capability_for_tool("workflow_confirm") == "desktop_automation"
    paths = {route.path for route in app.routes}
    assert {"/api/workflows", "/api/workflows/teach", "/api/workflows/run"}.issubset(paths)
    mini = (ROOT / "reyes_agent" / "static" / "mini.html").read_text(encoding="utf-8")
    assert "data.workflow" in mini
    assert "WORKFLOW_RUNNING" in mini


def _run_all() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001 - standalone runner
            failures += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
