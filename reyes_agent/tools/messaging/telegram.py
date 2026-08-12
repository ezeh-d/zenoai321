"""Telegram desktop, driven the same way Slack is.

The mechanics are identical -- open or focus, check the client is usable,
reach the conversation through the app's own search, compose, send, verify.
What differs is only the NAMES: the window title, the process, the shortcut
that opens search, and the words this client shows when it is signed out or
disconnected. Those are data, so they live here and the sequence lives in
router.py.

Telegram Desktop focuses search with Ctrl+F.

VERIFICATION IS THE SAME PROMISE. A message is SENT only when it is found in
the conversation afterwards. Pressing Enter is not evidence, on any platform.
"""

from __future__ import annotations

import time
from typing import Any

from reyes_agent.tools.messaging import desktop, models, slack as _shared

TITLES = ("Telegram", "Telegram Desktop")
PROCESSES = ("Telegram.exe",)
LAUNCH = "cmd /c start \"\" tg://"
SEARCH_KEYS = ('ctrl', 'f')

SIGNED_OUT_MARKERS = ("start messaging", "log in by phone number", "scan from mobile telegram")
OFFLINE_MARKERS = ("connecting...", "waiting for network", "updating...")


def open_app(trace: desktop.Trace) -> tuple[int, str]:
    return desktop.launch(LAUNCH, TITLES, PROCESSES, trace)


def check_state(handle: int, trace: desktop.Trace) -> str:
    started = time.perf_counter()
    text = _shared._window_text(handle)
    if any(marker in text for marker in SIGNED_OUT_MARKERS):
        trace.add("check_login", False, "Telegram is showing a sign-in screen",
                  (time.perf_counter() - started) * 1000)
        return models.AUTH_REQUIRED
    if any(marker in text for marker in OFFLINE_MARKERS):
        trace.add("check_online", False, "Telegram reports it is not connected",
                  (time.perf_counter() - started) * 1000)
        return models.PLATFORM_OFFLINE
    trace.add("check_ready", True, "signed in and connected",
              (time.perf_counter() - started) * 1000)
    return ""


def open_destination(handle: int, name: str,
                     trace: desktop.Trace) -> tuple[bool, str, list[str]]:
    started = time.perf_counter()
    wanted = (name or "").strip().lstrip("#").lower()
    if not wanted:
        trace.add("open_destination", False, "no destination given")
        return False, "", []

    desktop.hotkey(*SEARCH_KEYS)
    time.sleep(0.6)
    desktop.type_text(wanted)
    time.sleep(1.2)

    root = desktop.element_from_window(handle)
    matches = []
    for element in desktop.descendants(root, _shared.LIST_ITEM, limit=120):
        label = desktop.name_of(element).strip()
        if label and wanted in label.lower():
            matches.append(label)
    unique = list(dict.fromkeys(matches))
    exact = [m for m in unique if m.lstrip("#").lower().split()[:1] == [wanted]]
    if len(exact) > 1:
        desktop.press("escape")
        trace.add("open_destination", False,
                  f"{len(exact)} conversations match '{name}'",
                  (time.perf_counter() - started) * 1000)
        return False, "", exact[:6]

    desktop.press("enter")
    time.sleep(1.2)
    label = _shared._verify_open(handle, wanted)
    ok = bool(label)
    trace.add("open_destination", ok,
              f"opened '{label}'" if ok else f"could not confirm '{name}' opened",
              (time.perf_counter() - started) * 1000)
    return ok, label, unique[:6]


def compose(handle: int, message: str, trace: desktop.Trace) -> bool:
    return _shared.compose(handle, message, trace)


def send(handle: int, message: str, trace: desktop.Trace) -> tuple[str, bool, str]:
    return _shared.send(handle, message, trace)


def status() -> dict[str, Any]:
    ok, detail = desktop.available()
    handle, title = desktop.find_window(TITLES, PROCESSES)
    return {"state": "ONLINE" if ok else "UNAVAILABLE", "automation": detail,
            "running": bool(handle), "window": title,
            "navigation": "+".join(SEARCH_KEYS) + " search, then verified by window text",
            "no_coordinates": True}
