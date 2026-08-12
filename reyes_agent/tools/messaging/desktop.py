"""Shared Windows UI Automation for chat apps. No blind coordinates.

    "Avoid code such as pyautogui.click(423, 182)"

Agreed, and not merely as style. A coordinate is a claim about where
something was on one machine at one moment; it silently becomes a claim about
whatever is at that pixel next time. Clicking 423,182 in Slack could hit a
channel, a person, or a "delete" control depending on scroll position -- and
the automation cannot tell which, so it reports success either way.

Everything here addresses elements through UIA: by control type, by name, by
the accessibility tree. When a control cannot be found, that is an ERROR with
a name, not a coordinate to guess at.

WHY EVERY CHAT APP CAN SHARE THIS
---------------------------------
Slack, Discord, WhatsApp and Telegram desktop clients all present the same
three UIA shapes: a search/jump control, a list of conversations, and an edit
control for composing. They differ in what those elements are CALLED, which
is data, not logic. So the mechanics live here and each adapter supplies its
own names.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

# How long to wait for an app to become usable. Slack cold-starts slowly on
# a laptop; failing at 5s would report "not found" for an app that was simply
# still loading, which is a lie of impatience.
LAUNCH_TIMEOUT_S = 45.0
UI_TIMEOUT_S = 12.0
POLL_S = 0.4


@dataclass
class Step:
    name: str
    ok: bool = False
    detail: str = ""
    took_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"step": self.name, "ok": self.ok, "detail": self.detail,
                "took_ms": round(self.took_ms, 1)}


@dataclass
class Trace:
    """The record of what was actually done, so a failure can name its step."""
    steps: list[Step] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "", took_ms: float = 0.0) -> Step:
        step = Step(name, ok, detail, took_ms)
        self.steps.append(step)
        return step

    @property
    def failing(self) -> str:
        for step in self.steps:
            if not step.ok:
                return step.name
        return ""

    def as_list(self) -> list[dict[str, Any]]:
        return [s.as_dict() for s in self.steps]


def _uia():
    """The comtypes UIA client, or None. Never raises."""
    try:
        import comtypes.client

        return comtypes.client.CreateObject(
            "{ff48dba4-60ef-4201-aa87-54103eef594e}",
            interface=__import__("comtypes.gen.UIAutomationClient",
                                 fromlist=["IUIAutomation"]).IUIAutomation)
    except Exception:  # noqa: BLE001
        return None


def running_processes(names: tuple[str, ...]) -> list[int]:
    """PIDs of a running app, so a second instance is never launched."""
    try:
        import psutil

        wanted = {n.lower() for n in names}
        return [p.pid for p in psutil.process_iter(["name"])
                if (p.info.get("name") or "").lower() in wanted]
    except Exception:  # noqa: BLE001
        return []


def find_window(titles: tuple[str, ...],
                process_names: tuple[str, ...] = ()) -> tuple[int, str]:
    """(handle, title) of the app's window. (0,'') if it has none.

    TITLE ALONE IS NOT ENOUGH. Slack on this machine is a Microsoft Store
    package whose MainWindowTitle is EMPTY -- searching for "Slack" finds
    nothing while Slack is plainly running. So the process is the fallback
    lookup: a window with no title is still a window.
    """
    try:
        from reyes_agent.computer import window

        for want in titles:
            for handle, title in window.find_by_title(want):
                if handle:
                    return handle, title
    except Exception:  # noqa: BLE001
        pass

    for pid in running_processes(process_names):
        try:
            from reyes_agent.computer import window

            handle = window.handle_of_pid(pid)
            if handle:
                return handle, window.title_of(handle) or f"pid {pid}"
        except Exception:  # noqa: BLE001
            continue
    return 0, ""


def store_app_launch(package_prefix: str) -> str:
    """A launch command for a Microsoft Store app, or ''.

    Store apps live under C:\\Program Files\\WindowsApps, which is ACL'd so
    the exe cannot simply be run. The supported way in is the AppsFolder
    shell namespace, keyed by package family name.
    """
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f"(Get-AppxPackage -Name '*{package_prefix}*' | "
             "Select-Object -First 1).PackageFamilyName"],
            capture_output=True, text=True, timeout=25,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        family = (done.stdout or "").strip().splitlines()
        family = family[-1].strip() if family else ""
        if family:
            return f"explorer.exe shell:AppsFolder\\{family}!{package_prefix}"
    except Exception:  # noqa: BLE001
        pass
    return ""


def launch(command: str, titles: tuple[str, ...], process_names: tuple[str, ...],
           trace: Trace) -> tuple[int, str]:
    """Focus the app if it is already up; start it only if it is not.

        "If Slack is already running: do not launch another instance."

    A second instance is not harmless -- some clients open a fresh window
    with no conversation selected, so automation aimed at the first one then
    types into the wrong place.
    """
    started = time.perf_counter()
    handle, title = find_window(titles, process_names)
    if handle:
        activated = _activate(handle)
        trace.add("open_app", activated,
                  f"already running; focused existing window '{title}'",
                  (time.perf_counter() - started) * 1000)
        return handle, title

    if running_processes(process_names):
        # Running but no window -- usually minimised to tray. Re-invoking the
        # launcher asks the existing instance to show itself.
        trace.add("open_app_hidden", True, "process running without a window")

    try:
        subprocess.Popen(command, shell=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as exc:  # noqa: BLE001
        trace.add("open_app", False, f"could not start: {type(exc).__name__}: {exc}",
                  (time.perf_counter() - started) * 1000)
        return 0, ""

    deadline = time.time() + LAUNCH_TIMEOUT_S
    while time.time() < deadline:
        handle, title = find_window(titles, process_names)
        if handle:
            _activate(handle)
            trace.add("open_app", True, f"launched; window '{title}'",
                      (time.perf_counter() - started) * 1000)
            return handle, title
        time.sleep(POLL_S)

    trace.add("open_app", False,
              f"no window appeared within {LAUNCH_TIMEOUT_S:.0f}s",
              (time.perf_counter() - started) * 1000)
    return 0, ""


def _activate(handle: int) -> bool:
    try:
        from reyes_agent.computer import window

        ok, _detail = window.activate(handle)
        return bool(ok)
    except Exception:  # noqa: BLE001
        return False


def element_from_window(handle: int):
    """The UIA root element for a window handle."""
    uia = _uia()
    if uia is None or not handle:
        return None
    try:
        return uia.ElementFromHandle(handle)
    except Exception:  # noqa: BLE001
        return None


def descendants(element, control_type: int | None = None, limit: int = 4000):
    """Every descendant, optionally filtered by control type.

    The filter is pushed into the UIA condition rather than applied in
    Python. That distinction cost 86 seconds once: building the full cache
    and filtering afterwards is where the time goes, not the loop.
    """
    uia = _uia()
    if uia is None or element is None:
        return []
    try:
        if control_type is None:
            condition = uia.CreateTrueCondition()
        else:
            condition = uia.CreatePropertyCondition(30003, control_type)
        found = element.FindAll(4, condition)   # 4 = TreeScope_Descendants
        return [found.GetElement(i) for i in range(min(found.Length, limit))]
    except Exception:  # noqa: BLE001
        return []


def name_of(element) -> str:
    try:
        return str(element.CurrentName or "")
    except Exception:  # noqa: BLE001
        return ""


def value_of(element) -> str:
    """The text inside an edit control, via the Value pattern."""
    try:
        pattern = element.GetCurrentPattern(10002)   # ValuePattern
        if pattern:
            import comtypes.gen.UIAutomationClient as client

            return str(pattern.QueryInterface(client.IUIAutomationValuePattern)
                       .CurrentValue or "")
    except Exception:  # noqa: BLE001
        pass
    return ""


def set_focus(element) -> bool:
    try:
        element.SetFocus()
        return True
    except Exception:  # noqa: BLE001
        return False


def type_text(text: str) -> bool:
    """Type into whatever has focus, as a human would.

    Deliberately NOT the Value pattern: many chat composers are rich-text
    surfaces where setting Value writes text the app never notices, so the
    send button stays disabled and Enter does nothing. Typing goes through
    the same input path a person uses.
    """
    try:
        import pyautogui

        pyautogui.write(text, interval=0.012)
        return True
    except Exception:  # noqa: BLE001
        return False


def press(*keys: str) -> bool:
    try:
        import pyautogui

        for key in keys:
            pyautogui.press(key)
            time.sleep(0.05)
        return True
    except Exception:  # noqa: BLE001
        return False


def hotkey(*keys: str) -> bool:
    try:
        import pyautogui

        pyautogui.hotkey(*keys)
        return True
    except Exception:  # noqa: BLE001
        return False


def wait_for(predicate, timeout_s: float = UI_TIMEOUT_S):
    """Poll until a predicate returns something truthy, or give up."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except Exception:  # noqa: BLE001
            pass
        time.sleep(POLL_S)
    return None


def available() -> tuple[bool, str]:
    """Can this machine drive a desktop app at all."""
    missing = []
    if _uia() is None:
        missing.append("comtypes UI Automation")
    try:
        import pyautogui  # noqa: F401
    except Exception:  # noqa: BLE001
        missing.append("pyautogui")
    if missing:
        return False, "missing: " + ", ".join(missing)
    return True, "UI Automation and input available"
