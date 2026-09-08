"""list_open_windows: a live, honest read of what's actually on the desktop
right now -- never a remembered/stale answer (spec: 'ZENO tracks relevant
open windows', 'never trust old context blindly')."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reyes_agent.computer import window as computer_window
from reyes_agent.tools import system


def test_list_open_windows_reports_title_process_foreground_and_minimized(monkeypatch) -> None:
    processes = [
        SimpleNamespace(info={"pid": 100, "name": "chrome.exe"}),
        SimpleNamespace(info={"pid": 200, "name": "notepad.exe"}),
    ]
    monkeypatch.setattr(system.psutil, "process_iter", lambda _attrs: processes)
    monkeypatch.setattr(system, "_visible_windows", lambda: [
        (1, 100, "GitHub - Google Chrome"),
        (2, 200, "Untitled - Notepad"),
    ])
    monkeypatch.setattr(computer_window, "status", lambda hwnd: (
        {"handle": 1, "foreground": True, "minimized": False} if hwnd == 1
        else {"handle": 2, "foreground": False, "minimized": True}
    ))

    result = json.loads(system.list_open_windows())
    assert result["count"] == 2
    chrome, notepad = result["windows"]
    assert chrome["title"] == "GitHub - Google Chrome"
    assert chrome["process"] == "chrome.exe"
    assert chrome["foreground"] is True
    assert chrome["minimized"] is False
    assert notepad["process"] == "notepad.exe"
    assert notepad["foreground"] is False
    assert notepad["minimized"] is True


def test_list_open_windows_respects_the_limit(monkeypatch) -> None:
    monkeypatch.setattr(system.psutil, "process_iter", lambda _attrs: [])
    monkeypatch.setattr(system, "_visible_windows", lambda: [(i, i, f"Window {i}") for i in range(10)])
    monkeypatch.setattr(computer_window, "status", lambda _hwnd: {"handle": 0, "foreground": False, "minimized": False})

    result = json.loads(system.list_open_windows(limit=3))
    assert result["count"] == 3


def test_list_open_windows_is_never_stale_between_calls(monkeypatch) -> None:
    """Two calls in a row must reflect whatever _visible_windows reports at
    THAT moment -- proof this is a live query, not a cached snapshot."""
    monkeypatch.setattr(system.psutil, "process_iter", lambda _attrs: [])
    monkeypatch.setattr(computer_window, "status", lambda _hwnd: {"handle": 0, "foreground": False, "minimized": False})

    monkeypatch.setattr(system, "_visible_windows", lambda: [(1, 1, "Only Window")])
    first = json.loads(system.list_open_windows())
    assert first["count"] == 1

    monkeypatch.setattr(system, "_visible_windows", lambda: [])
    second = json.loads(system.list_open_windows())
    assert second["count"] == 0


def test_list_open_windows_tool_is_registered_and_light() -> None:
    from reyes_agent.tools import TOOLS

    assert "list_open_windows" in TOOLS
    assert TOOLS["list_open_windows"].light is True
