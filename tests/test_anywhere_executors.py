"""Safety and truthfulness tests for ZENO Anywhere desktop executors."""

from __future__ import annotations

import json
import time
from pathlib import Path

from reyes_agent import permissions
from reyes_agent.tools import TOOLS
from reyes_agent.tools import system
from reyes_agent.workflow_engine import WorkflowEngine


class _Handle:
    done = False

    @staticmethod
    def snapshot() -> dict:
        return {"id": "task_remote_workflow", "state": "RUNNING"}

    def cancel(self) -> None:
        self.done = True


class _Kernel:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def submit(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return _Handle()


def _workflow(root: Path, *, approved: bool = True, steps: list[dict] | None = None) -> None:
    payload = {
        "id": "morning-report", "name": "Morning Report",
        "approved_at": time.time() if approved else 0,
        "steps": list(steps or []),
    }
    (root / "morning-report.json").write_text(json.dumps(payload), encoding="utf-8")


def test_close_app_is_permission_gated_and_mapped_to_app_control() -> None:
    assert TOOLS["close_app"].requires_confirmation is True
    assert permissions.capability_for_tool("close_app") == "app_control"
    schema = TOOLS["close_app"].input_schema
    assert schema["additionalProperties"] is False
    assert "python" not in schema["properties"]["name"]["enum"]


def test_close_app_posts_only_graceful_window_messages_and_verifies(monkeypatch) -> None:
    observations = iter([
        [(101, 501, "Document - Notepad")],
        [],
    ])
    posted: list[int] = []
    monkeypatch.setattr(system, "_matching_close_windows", lambda _names: next(observations))
    monkeypatch.setattr(system, "_post_close_message", lambda hwnd: posted.append(hwnd) or True)

    result = system.close_app("Notepad", timeout_s=0.2)
    assert posted == [101]
    assert "postcondition verified" in result
    called_names = set(system.close_app.__code__.co_names)
    assert called_names.isdisjoint({"terminate", "kill", "taskkill", "subprocess", "run", "Popen"})


def test_close_app_denies_zeno_python_webview_shell_and_arbitrary_names(monkeypatch) -> None:
    monkeypatch.setattr(
        system, "_matching_close_windows",
        lambda _names: (_ for _ in ()).throw(AssertionError("protected name reached window lookup")),
    )
    for name in ("ZENO", "python", "python.exe", "pythonw", "WebView2", "msedgewebview2.exe",
                 "File Explorer", "explorer.exe", "system"):
        assert system.close_app(name).startswith("Blocked:")
    assert system.close_app("cmd.exe & whoami").startswith("Blocked:")


def test_close_app_does_not_claim_success_when_window_remains(monkeypatch) -> None:
    monkeypatch.setattr(system, "_matching_close_windows", lambda _names: [(99, 5, "Unsaved - Word")])
    monkeypatch.setattr(system, "_post_close_message", lambda _hwnd: True)
    result = system.close_app("Word", timeout_s=0.2)
    assert result.startswith("Failed:")
    assert "no process was terminated" in result


def test_remote_workflow_starts_only_persisted_approved_record(tmp_path, monkeypatch) -> None:
    _workflow(tmp_path)
    engine = WorkflowEngine(root=tmp_path)
    kernel = _Kernel()
    monkeypatch.setattr("reyes_agent.kernel.get_kernel", lambda: kernel)
    monkeypatch.setattr(permissions, "state_for", lambda _capability: permissions.ENABLED)

    result = engine.start_approved_remote_run(
        "Morning Report", approval_id="apr_1234567890abcdef",
        command_id="cmd_1234567890abcdef", requesting_device="trusted-phone",
    )
    assert result["ok"] is True and result["state"] == "STARTED"
    assert result["workflow_id"] == "morning-report"
    assert result["task_id"] == "task_remote_workflow"
    assert len(kernel.calls) == 1


def test_remote_workflow_rejects_raw_definitions_paths_and_invalid_approval(tmp_path) -> None:
    _workflow(tmp_path)
    engine = WorkflowEngine(root=tmp_path)
    attempts = (
        ({"id": "morning-report"}, "apr_1234567890abcdef"),
        ('{"steps":[{"op":"tool"}]}', "apr_1234567890abcdef"),
        ("..\\morning-report.json", "apr_1234567890abcdef"),
        ("Morning\nReport", "apr_1234567890abcdef"),
        ("Morning Report", "not-an-approval"),
    )
    for reference, approval in attempts:
        result = engine.start_approved_remote_run(reference, approval_id=approval)  # type: ignore[arg-type]
        assert result["ok"] is False and result["state"] == "REJECTED"


def test_remote_approval_never_overrides_blocked_capability(tmp_path, monkeypatch) -> None:
    _workflow(tmp_path, steps=[{"op": "desktop_click", "x": 0.5, "y": 0.5}])
    engine = WorkflowEngine(root=tmp_path)
    monkeypatch.setattr(
        permissions, "state_for",
        lambda capability: permissions.BLOCKED if capability == "desktop_automation" else permissions.ENABLED,
    )
    result = engine.start_approved_remote_run(
        "morning-report", approval_id="apr_1234567890abcdef")
    assert result["ok"] is False
    assert "blocked capability" in result["error"].casefold()


def test_unapproved_persisted_workflow_cannot_start_remotely(tmp_path) -> None:
    _workflow(tmp_path, approved=False)
    result = WorkflowEngine(root=tmp_path).start_approved_remote_run(
        "morning-report", approval_id="apr_1234567890abcdef")
    assert result["ok"] is False
    assert "owner-approved" in result["error"]
