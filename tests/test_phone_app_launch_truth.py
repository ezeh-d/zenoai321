"""Regression coverage for verified phone-to-Windows app launching."""

from __future__ import annotations

from types import SimpleNamespace

from reyes_agent.remote_access import desktop_agent
from reyes_agent import tools
from reyes_agent.tools import system


def test_phone_notepad_command_is_deterministic_and_skips_the_model(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def run(action: str, payload: dict):
        calls.append((action, payload))
        return True, {
            "tool": "open_app",
            "detail": "Opened 'notepad'; postcondition verified: visible Notepad window.",
            "verification_state": "verified",
        }

    monkeypatch.setattr(desktop_agent, "_run_tool", run)
    ok, result = desktop_agent._exec_ask({
        "text": "Open note pad on the system",
        "_owner_elevated": True,
    })

    assert ok is True
    assert calls == [("open_app", {"name": "notepad"})]
    assert result["verification_state"] == "verified"
    assert result["local_fast_path"] is True
    assert result["tool_calls"] == [
        {"name": "open_app", "input": {"name_or_path": "notepad"}}
    ]
    assert "verified" in result["answer"].casefold()


def test_phone_app_command_cannot_turn_unverified_launch_into_done(monkeypatch) -> None:
    monkeypatch.setattr(
        desktop_agent,
        "_run_tool",
        lambda *_args, **_kwargs: (
            False,
            {
                "tool": "open_app",
                "detail": "Failed: no visible window.",
                "verification_state": "failed",
                "error": "The application action did not produce verified Windows evidence.",
            },
        ),
    )

    ok, result = desktop_agent._exec_ask({
        "text": "Please open Notepad on my laptop",
        "_owner_elevated": True,
    })

    assert ok is False
    assert result["intent"] == "open_app"
    assert "verified Windows evidence" in result["error"]
    assert "answer" not in result


def test_direct_phone_parser_accepts_only_allowlisted_single_app_requests() -> None:
    parse = desktop_agent._direct_remote_app_request
    assert parse("ZENO, could you please launch VS Code on my computer?") == {
        "name": "Visual Studio Code"
    }
    assert parse("Can you open the Notepad app on the system?") == {"name": "notepad"}
    assert parse("Open up notepad") == {"name": "notepad"}
    assert parse("open C:\\Windows\\System32\\cmd.exe") is None
    assert parse("open notepad and type my password") is None
    assert parse("do not open notepad") is None


def test_open_app_provider_alias_is_canonicalized_before_execution(monkeypatch) -> None:
    observed: list[dict] = []
    monkeypatch.setattr(
        tools.TOOLS["open_app"],
        "func",
        lambda **kwargs: observed.append(kwargs) or
        "Opened 'notepad'; postcondition verified: visible Notepad window.",
    )
    monkeypatch.setattr("reyes_agent.permissions.check", lambda _name: "ENABLED")

    result = tools.run_tool("open_app", {"name": "notepad"})

    assert observed == [{"name_or_path": "notepad"}]
    assert "postcondition verified" in result


def test_open_app_provider_alias_rejects_extra_fields() -> None:
    malformed = {"name": "notepad", "target": "calculator"}
    assert tools._canonical_tool_input("open_app", malformed) is malformed


def test_remote_effect_executor_rejects_a_normal_but_unverified_return(monkeypatch) -> None:
    monkeypatch.setattr(
        "reyes_agent.tools.run_tool",
        lambda *_args, **_kwargs: "Launch request returned but no window evidence exists.",
    )
    ok, result = desktop_agent._run_tool("open_app", {"name": "notepad"})
    assert ok is False
    assert result["verification_state"] == "unverified"
    assert "verified Windows evidence" in result["error"]


def test_process_without_visible_window_is_not_open_app_evidence(monkeypatch) -> None:
    process = SimpleNamespace(info={"pid": 808, "name": "notepad.exe"})
    monkeypatch.setattr(system.psutil, "process_iter", lambda _attrs: [process])
    monkeypatch.setattr(system, "_visible_windows", lambda: [])

    evidence = system._verify_app_open("notepad", set(), timeout_s=0.2)
    assert evidence == ""


def test_visible_window_owned_by_expected_process_is_verified(monkeypatch) -> None:
    process = SimpleNamespace(info={"pid": 808, "name": "notepad.exe"})
    monkeypatch.setattr(system.psutil, "process_iter", lambda _attrs: [process])
    monkeypatch.setattr(
        system, "_visible_windows", lambda: [(12345, 808, "Untitled - Notepad")]
    )

    evidence = system._verify_app_open("notepad", set(), timeout_s=0.2)
    assert "visible window" in evidence
    assert "PID 808" in evidence


def test_explorer_launch_can_be_verified_without_permitting_explorer_close(monkeypatch) -> None:
    process = SimpleNamespace(info={"pid": 404, "name": "explorer.exe"})
    monkeypatch.setattr(system.psutil, "process_iter", lambda _attrs: [process])
    monkeypatch.setattr(
        system, "_visible_windows", lambda: [(999, 404, "Documents")]
    )

    evidence = system._verify_app_open("explorer", {404}, timeout_s=0.2)
    assert "visible window 'Documents'" in evidence
    assert "explorer" not in system._CLOSE_APP_PROCESSES


def test_open_app_reports_failed_when_windows_postcondition_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(system.os, "startfile", lambda _target: None)
    monkeypatch.setattr(system, "_verify_app_open", lambda *_args, **_kwargs: "")

    result = system.open_app("notepad")
    assert result.startswith("Failed:")
    assert "visible Windows window" in result
