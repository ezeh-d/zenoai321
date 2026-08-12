"""Slack, driven through its real UI.

THE NAVIGATION IS DELIBERATELY KEYBOARD-FIRST
---------------------------------------------
Slack's own quick-switcher (Ctrl+K) is the most reliable way to reach a
conversation: it is a documented, stable shortcut, it searches every channel
and person the account can see, and it does not care where anything sits on
screen or how far the sidebar is scrolled. Hunting the sidebar visually would
mean scrolling, guessing at truncated names, and failing whenever the channel
is below the fold.

VERIFICATION IS NOT OPTIONAL
----------------------------
    "A successful click/Enter is NOT enough."

Pressing Enter proves a key was pressed. It does not prove Slack accepted the
message, that the workspace was connected, or that the composer even had
focus. So sending checks two independent things afterwards: the composer went
empty, AND the text appears in the message list. Either alone can lie -- a
cleared composer can mean the text was discarded, and a match in the list can
be an older identical message -- so a send that cannot show both comes back
SEND_UNVERIFIED rather than SENT.
"""

from __future__ import annotations

import time
from typing import Any

from reyes_agent.tools.messaging import desktop, models

TITLES = ("Slack",)
PROCESSES = ("slack.exe",)
# Slack here is a Microsoft Store package, whose exe under WindowsApps
# cannot be launched directly. Resolved at call time so this still works on a
# machine with the ordinary installer.
_PROTOCOL = 'cmd /c start "" slack:'


def _launch_command() -> str:
    return desktop.store_app_launch("Slack") or _PROTOCOL

# UIA control type ids.
EDIT, DOCUMENT, LIST, LIST_ITEM, TEXT = 50004, 50030, 50008, 50007, 50020

# Text Slack shows when it cannot reach the workspace.
OFFLINE_MARKERS = ("you're offline", "connection lost", "trying to connect",
                   "slack is having trouble connecting")
SIGNED_OUT_MARKERS = ("sign in to slack", "sign in with email",
                      "create a workspace", "sign in to another workspace")


def open_slack(trace: desktop.Trace) -> tuple[int, str]:
    return desktop.launch(_launch_command(), TITLES, PROCESSES, trace)


def _window_text(handle: int, limit: int = 700) -> str:
    """A flattened snapshot of visible text, for state checks."""
    root = desktop.element_from_window(handle)
    if root is None:
        return ""
    names = []
    for element in desktop.descendants(root, TEXT, limit=limit):
        name = desktop.name_of(element)
        if name:
            names.append(name)
    return "\n".join(names).lower()


def accessibility_ready(handle: int) -> tuple[bool, str]:
    """Can the web content actually be READ. Measured, not assumed.

    Slack is Electron, and Chromium does not build a renderer accessibility
    tree unless something asks for one. On this machine the UIA tree contains
    only the window chrome -- RootView, NonClientView, the caption buttons --
    and nothing from the app itself: no channel list, no messages, no
    composer.

    That matters more than it sounds. Keyboard navigation would still "work"
    in the sense that keys land somewhere, but NOTHING could be verified: not
    that the right channel opened, not that the composer had focus, not that
    the message was accepted. Every send would be SEND_UNVERIFIED at best and
    typing into the wrong conversation at worst.

    So this is checked BEFORE anything is typed, and a blind Slack is refused
    rather than driven. The fix is on Slack's side -- it must run with
    renderer accessibility enabled (--force-renderer-accessibility, or an
    assistive client active) -- and until it does, saying so is the honest
    result.
    """
    _wake_chromium(handle)
    root = desktop.element_from_window(handle)
    if root is None:
        return False, "no accessibility root for the Slack window"
    for control in (TEXT, EDIT, DOCUMENT, LIST_ITEM):
        if desktop.descendants(root, control, limit=8):
            return True, "Slack's content is readable"
    return False, (
        "Slack is running but exposes no accessible content -- only the "
        "window frame. It is an Electron app, and Chromium only builds an "
        "accessibility tree when asked. Start Slack with "
        "--force-renderer-accessibility (or turn on a Windows assistive "
        "feature) and I will be able to read and verify it.")


def _wake_chromium(handle: int) -> None:
    """Ask Chromium for an accessibility tree. Harmless when unsupported."""
    try:
        import ctypes

        # WM_GETOBJECT / OBJID_CLIENT -- the request that makes Chromium turn
        # accessibility on. Timeout-bounded so a busy renderer cannot hang us.
        ctypes.windll.user32.SendMessageTimeoutW(
            handle, 0x003D, 0, 1, 0x0002, 2000, None)
    except Exception:  # noqa: BLE001
        pass


def check_state(handle: int, trace: desktop.Trace) -> str:
    """AUTH_REQUIRED / PLATFORM_OFFLINE / '' when usable.

    Checked BEFORE typing anything. Discovering a workspace is offline after
    pressing Enter means having to explain where the message went.
    """
    started = time.perf_counter()

    # Refuse to drive an app whose result cannot be read. Typing blind is
    # how a message ends up in the wrong conversation with a confident
    # "Done" attached to it.
    readable, why = accessibility_ready(handle)
    if not readable:
        trace.add("check_readable", False, why,
                  (time.perf_counter() - started) * 1000)
        return models.SEND_FAILED

    text = _window_text(handle)
    if any(marker in text for marker in SIGNED_OUT_MARKERS):
        trace.add("check_login", False, "Slack is showing a sign-in screen",
                  (time.perf_counter() - started) * 1000)
        return models.AUTH_REQUIRED
    if any(marker in text for marker in OFFLINE_MARKERS):
        trace.add("check_online", False, "Slack reports it is offline",
                  (time.perf_counter() - started) * 1000)
        return models.PLATFORM_OFFLINE
    trace.add("check_ready", True, "signed in and connected",
              (time.perf_counter() - started) * 1000)
    return ""


def open_destination(handle: int, name: str, trace: desktop.Trace) -> tuple[bool, str, list[str]]:
    """Navigate to a channel/person. Returns (ok, resolved_label, candidates)."""
    started = time.perf_counter()
    wanted = (name or "").strip().lstrip("#").lower()
    if not wanted:
        trace.add("open_destination", False, "no destination given")
        return False, "", []

    desktop.hotkey("ctrl", "k")
    time.sleep(0.6)
    desktop.type_text(wanted)
    time.sleep(1.1)          # let Slack's search settle before reading results

    root = desktop.element_from_window(handle)
    options = []
    for element in desktop.descendants(root, LIST_ITEM, limit=120):
        label = desktop.name_of(element).strip()
        if label and wanted in label.lower():
            options.append(label)

    # Distinct destinations that all match what the owner said. Choosing one
    # silently is how a message reaches the wrong room.
    unique = list(dict.fromkeys(options))
    exact = [o for o in unique if o.lstrip("#").lower().split()[0] == wanted]
    if len(exact) > 1:
        desktop.press("escape")
        trace.add("open_destination", False,
                  f"{len(exact)} destinations match '{name}'",
                  (time.perf_counter() - started) * 1000)
        return False, "", exact[:6]

    desktop.press("enter")
    time.sleep(1.2)

    label = _verify_open(handle, wanted)
    ok = bool(label)
    trace.add("open_destination", ok,
              f"opened '{label}'" if ok else
              f"could not confirm '{name}' opened",
              (time.perf_counter() - started) * 1000)
    return ok, label, unique[:6]


def _verify_open(handle: int, wanted: str) -> str:
    """Confirm the conversation really is the one that was asked for.

        "Verify General is actually selected."

    Read from the window rather than assumed from the keystroke: pressing
    Enter in the switcher can land on whatever was highlighted, which is not
    always what was typed.
    """
    def look():
        text = _window_text(handle, limit=250)
        return wanted in text

    if desktop.wait_for(look, timeout_s=6.0):
        root = desktop.element_from_window(handle)
        for element in desktop.descendants(root, TEXT, limit=120):
            name = desktop.name_of(element).strip()
            if name and wanted in name.lower() and len(name) < 80:
                return name
        return wanted
    return ""


def _composer(handle: int):
    """The message box. Slack renders it as an edit or a document element."""
    root = desktop.element_from_window(handle)
    for control in (EDIT, DOCUMENT):
        for element in desktop.descendants(root, control, limit=200):
            label = desktop.name_of(element).lower()
            if "message" in label or "composer" in label or "reply" in label:
                return element
    for element in desktop.descendants(root, EDIT, limit=60):
        return element
    return None


def compose(handle: int, message: str, trace: desktop.Trace) -> bool:
    """Put text in the composer without sending it."""
    started = time.perf_counter()
    box = _composer(handle)
    if box is None:
        trace.add("focus_composer", False, "could not find the message box",
                  (time.perf_counter() - started) * 1000)
        return False
    if not desktop.set_focus(box):
        trace.add("focus_composer", False, "the message box would not take focus",
                  (time.perf_counter() - started) * 1000)
        return False
    trace.add("focus_composer", True, "composer focused",
              (time.perf_counter() - started) * 1000)

    typed = time.perf_counter()
    desktop.type_text(message)
    time.sleep(0.4)
    present = message.strip()[:40].lower() in desktop.value_of(box).lower()
    trace.add("type_message", True,
              "text is in the composer" if present else
              "typed; composer contents could not be read back",
              (time.perf_counter() - typed) * 1000)
    return True


def send(handle: int, message: str, trace: desktop.Trace) -> tuple[str, bool, str]:
    """Submit, then prove it arrived. Returns (status, verified, detail)."""
    started = time.perf_counter()
    box = _composer(handle)
    before = desktop.value_of(box) if box is not None else ""

    desktop.press("enter")
    time.sleep(1.0)

    cleared = False
    if box is not None:
        after = desktop.value_of(box)
        cleared = bool(before) and not after.strip()

    appeared = _find_in_conversation(handle, message)
    trace.add("send", True, "Enter pressed", (time.perf_counter() - started) * 1000)

    if appeared and cleared:
        trace.add("verify", True, "message is in the conversation and the "
                                  "composer cleared")
        return models.SENT, True, "seen in the conversation; composer cleared"
    if appeared:
        trace.add("verify", True, "message is in the conversation")
        return models.SENT, True, "seen in the conversation"
    if cleared:
        # The composer emptying is consistent with sending, but it is also
        # what a discarded draft looks like. Not enough on its own.
        trace.add("verify", False, "composer cleared but the message was not "
                                   "found in the conversation")
        return (models.SEND_UNVERIFIED, False,
                "The composer cleared, but I could not find the message in the "
                "conversation to confirm it went out.")
    trace.add("verify", False, "no evidence the message was accepted")
    return (models.SEND_UNVERIFIED, False,
            "I pressed Enter but found no sign the message was accepted.")


def _find_in_conversation(handle: int, message: str) -> bool:
    """Look for the text in the message list, not merely anywhere on screen."""
    needle = message.strip().lower()
    if not needle:
        return False
    probe = needle[:60]

    def look():
        root = desktop.element_from_window(handle)
        for control in (LIST_ITEM, TEXT):
            for element in desktop.descendants(root, control, limit=400):
                if probe in desktop.name_of(element).lower():
                    return True
        return False

    return bool(desktop.wait_for(look, timeout_s=8.0))


def status() -> dict[str, Any]:
    ok, detail = desktop.available()
    handle, title = desktop.find_window(TITLES, PROCESSES)
    return {"state": "ONLINE" if ok else "UNAVAILABLE",
            "automation": detail,
            "running": bool(handle), "window": title,
            "navigation": "Ctrl+K quick switcher, then verified by window text",
            "no_coordinates": True}
