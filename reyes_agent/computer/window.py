"""Bring a window forward -- the remedy `vision.coverage` keeps prescribing.

WHY THIS EXISTS
---------------
Coverage can now tell the owner exactly why a window could not be read:
it is minimized, or Windows has suspended it in the background. Both
diagnoses end in "bring it to the foreground and look again" -- and until
this module there was nothing in ZENO that could do that. A diagnosis with
no remedy is just a nicer way of failing.

THE FOREGROUND LOCK
-------------------
`SetForegroundWindow` alone silently fails when another process owns the
foreground; Windows refuses to let background apps steal focus mid-typing.
Observed directly: launching Notepad while Chrome was in use left Chrome
in front, and the window never came forward.

The documented way through is to attach this thread's input queue to the
one that currently owns the foreground, so Windows treats the request as
coming from the active app, then detach again. That is what the dance
below does -- and it is bounded, checked, and reports honestly when it
loses, because "focus refused" must never look like "done".
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import time
from typing import Any

SW_RESTORE = 9
SW_SHOW = 5

_user32 = ctypes.windll.user32


def handle_of_pid(pid: int) -> int:
    """The first visible top-level window belonging to `pid`, or 0."""
    found: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def _each(handle, _param):
        owner = ctypes.wintypes.DWORD()
        _user32.GetWindowThreadProcessId(handle, ctypes.byref(owner))
        if owner.value == pid and _user32.IsWindowVisible(handle):
            if _user32.GetWindowTextLengthW(handle) > 0:
                found.append(int(handle))
                return False
        return True

    try:
        _user32.EnumWindows(_each, 0)
    except Exception:  # noqa: BLE001
        return 0
    return found[0] if found else 0


def title_of(handle: int) -> str:
    try:
        length = _user32.GetWindowTextLengthW(handle)
        buffer = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(handle, buffer, length + 1)
        return buffer.value
    except Exception:  # noqa: BLE001
        return ""


def find_by_title(want: str) -> list[tuple[int, str]]:
    """Visible top-level windows whose title contains `want`, best first.

    An exact title beats a prefix beats a substring, so "Notepad" prefers
    the actual Notepad over "Notepad tips - Google Chrome".
    """
    needle = str(want or "").strip().lower()
    if not needle:
        return []
    matches: list[tuple[int, int, str]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def _each(handle, _param):
        if _user32.IsWindowVisible(handle):
            title = title_of(handle)
            low = title.lower()
            if needle in low:
                rank = 0 if low == needle else (1 if low.startswith(needle) else 2)
                matches.append((rank, int(handle), title))
        return True

    try:
        _user32.EnumWindows(_each, 0)
    except Exception:  # noqa: BLE001
        return []
    matches.sort(key=lambda row: (row[0], len(row[2])))
    return [(handle, title) for _rank, handle, title in matches]


def is_foreground(handle: int) -> bool:
    try:
        return int(_user32.GetForegroundWindow()) == int(handle)
    except Exception:  # noqa: BLE001
        return False


def activate(handle: int, *, timeout_s: float = 2.0) -> tuple[bool, str]:
    """Bring `handle` to the front. (succeeded, what happened)."""
    if not handle:
        return False, "no window handle"
    if is_foreground(handle):
        return True, "already in front"

    try:
        if _user32.IsIconic(handle):
            _user32.ShowWindow(handle, SW_RESTORE)
        else:
            _user32.ShowWindow(handle, SW_SHOW)

        current = _user32.GetForegroundWindow()
        target_thread = _user32.GetWindowThreadProcessId(handle, None)
        current_thread = _user32.GetWindowThreadProcessId(current, None)

        attached = False
        if current_thread and target_thread and current_thread != target_thread:
            attached = bool(_user32.AttachThreadInput(current_thread, target_thread, True))
        try:
            _user32.BringWindowToTop(handle)
            _user32.SetForegroundWindow(handle)
        finally:
            if attached:
                _user32.AttachThreadInput(current_thread, target_thread, False)
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if is_foreground(handle):
            return True, "brought to the front"
        time.sleep(0.05)

    # Losing the foreground race is normal and must be said plainly.
    return False, ("Windows would not let me bring that window forward -- it "
                   "blocks focus changes while another app is in use. Click it "
                   "once and I will carry on.")


def status(handle: int = 0) -> dict[str, Any]:
    handle = handle or int(_user32.GetForegroundWindow())
    return {"handle": handle, "foreground": is_foreground(handle),
            "minimized": bool(_user32.IsIconic(handle)) if handle else False}
