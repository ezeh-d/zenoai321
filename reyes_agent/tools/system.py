"""Desktop control tools -- REYES's hands on the actual machine.

Read-only / low-risk tools (list, read, open an app or folder) run
immediately. Anything matching the "confirm before acting" list from
AGENT.md -- deleting, moving files, running arbitrary commands -- is
registered with requires_confirmation=True and goes through the Tier 6
gate in reyes_agent/confirmation.py instead of running on the spot.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import psutil

from reyes_agent.tools import register

_MAX_LIST = 200
_MAX_READ_CHARS = 6000
_WM_CLOSE = 0x0010

# Remote/local app closing is deliberately narrower than app launching.  A
# launch typo normally fails; a close typo aimed at the shell or ZENO itself
# can destroy the user's session.  Match exact process basenames only and do
# not accept paths, PIDs, executable names, or caller-supplied commands.
_CLOSE_APP_PROCESSES: dict[str, frozenset[str]] = {
    "chrome": frozenset({"chrome.exe"}),
    "google chrome": frozenset({"chrome.exe"}),
    "edge": frozenset({"msedge.exe"}),
    "microsoft edge": frozenset({"msedge.exe"}),
    "firefox": frozenset({"firefox.exe"}),
    "notepad": frozenset({"notepad.exe"}),
    "calculator": frozenset({"calculator.exe", "calculatorapp.exe"}),
    "visual studio code": frozenset({"code.exe"}),
    "vs code": frozenset({"code.exe"}),
    "vscode": frozenset({"code.exe"}),
    "word": frozenset({"winword.exe"}),
    "microsoft word": frozenset({"winword.exe"}),
    "excel": frozenset({"excel.exe"}),
    "powerpoint": frozenset({"powerpnt.exe"}),
    "spotify": frozenset({"spotify.exe"}),
    "slack": frozenset({"slack.exe"}),
    "discord": frozenset({"discord.exe"}),
    "telegram": frozenset({"telegram.exe"}),
    "whatsapp": frozenset({"whatsapp.exe"}),
}
# Launch verification may safely recognise Explorer even though close_app
# must never be allowed to close the Windows shell.  Keep the two policies
# separate so adding launch evidence cannot widen destructive control.
_OPEN_APP_PROCESSES: dict[str, frozenset[str]] = {
    **_CLOSE_APP_PROCESSES,
    "explorer": frozenset({"explorer.exe"}),
    "file explorer": frozenset({"explorer.exe"}),
}
_PROTECTED_CLOSE_NAMES = frozenset({
    "zeno", "zeno.exe", "reyes", "reyes.exe", "python", "python.exe",
    "pythonw", "pythonw.exe", "webview", "webview2", "msedgewebview2",
    "msedgewebview2.exe", "explorer", "explorer.exe", "file explorer", "windows explorer",
    "shell", "desktop", "system", "winlogon", "services", "lsass", "dwm",
})


def _visible_windows() -> list[tuple[int, int, str]]:
    """Return visible top-level ``(hwnd, pid, title)`` rows on Windows."""
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        rows: list[tuple[int, int, str]] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def visit(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            rows.append((int(hwnd), int(pid.value), buffer.value))
            return True

        user32.EnumWindows(callback_type(visit), 0)
        return rows
    except Exception:  # noqa: BLE001 -- process evidence remains available
        return []


def _verify_app_open(expected: str, before_pids: set[int], *, timeout_s: float = 6.0) -> str:
    target = Path(str(expected)).stem.casefold().replace(".exe", "").strip()
    compact = "".join(ch for ch in target if ch.isalnum())
    known_processes = {
        name.casefold()
        for alias, names in _OPEN_APP_PROCESSES.items()
        if alias == target
        for name in names
    }
    deadline = time.monotonic() + max(0.2, timeout_s)
    while time.monotonic() < deadline:
        processes: dict[int, str] = {}
        for process in psutil.process_iter(["pid", "name"]):
            try:
                name = str(process.info.get("name") or "")
                processes[int(process.info["pid"])] = name
            except (psutil.Error, OSError, ValueError):
                continue
        for hwnd, pid, title in _visible_windows():
            title_compact = "".join(ch for ch in title.casefold() if ch.isalnum())
            process_name = processes.get(pid, "")
            process_compact = "".join(
                ch for ch in Path(process_name).stem.casefold() if ch.isalnum())
            exact_known_process = process_name.casefold() in known_processes
            title_matches = compact and len(compact) >= 4 and compact in title_compact
            new_matching_process = (
                pid not in before_pids and compact and
                (process_compact == compact or
                 (len(compact) >= 5 and compact in process_compact)))
            if exact_known_process or title_matches or new_matching_process:
                return (f"visible window '{title[:100]}' (HWND {hwnd}, PID {pid}) "
                        f"owned by {process_name or 'a matching app'} exists")
        time.sleep(0.1)
    return ""


def _matching_close_windows(process_names: frozenset[str]) -> list[tuple[int, int, str]]:
    """Visible top-level windows owned by an exact allow-listed process.

    Window titles are not used for identity: a Chrome tab titled "Notepad"
    must never be mistaken for Notepad.  Process lookup failure simply omits
    that window, failing closed rather than guessing.
    """
    matches: list[tuple[int, int, str]] = []
    wanted = {name.casefold() for name in process_names}
    for hwnd, pid, title in _visible_windows():
        try:
            process_name = str(psutil.Process(pid).name() or "").casefold()
        except (psutil.Error, OSError, ValueError):
            continue
        if process_name in wanted:
            matches.append((hwnd, pid, title))
    return matches


def _post_close_message(hwnd: int) -> bool:
    """Ask one Windows GUI window to close gracefully; never kill its PID."""
    if os.name != "nt" or not hwnd:
        return False
    try:
        import ctypes

        return bool(ctypes.windll.user32.PostMessageW(int(hwnd), _WM_CLOSE, 0, 0))
    except Exception:  # noqa: BLE001 -- native failure is reported by close_app
        return False


@register(
    name="close_app",
    description=(
        "Gracefully close visible windows for one explicitly allow-listed application. "
        "Never terminates a process and never closes ZENO, Python, WebView2, Explorer, "
        "or the Windows shell. The application's own save/discard prompt remains visible "
        "when there is unsaved work."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "enum": sorted(_CLOSE_APP_PROCESSES),
                "description": "Allow-listed application name; paths, PIDs and commands are rejected.",
            },
        },
        "required": ["name"],
        "additionalProperties": False,
    },
    requires_confirmation=True,
)
def close_app(name: str, *, timeout_s: float = 5.0) -> str:
    """Post ``WM_CLOSE`` and verify the visible windows actually disappear.

    ``WM_CLOSE`` lets the application show its normal save/discard prompt.  A
    remaining window is therefore an honest incomplete result, not a reason
    to escalate to ``taskkill`` or ``Process.terminate``.
    """
    requested = " ".join(str(name or "").split()).casefold()
    if requested in _PROTECTED_CLOSE_NAMES:
        return f"Blocked: '{requested}' is a protected ZENO or Windows host and was not closed."
    process_names = _CLOSE_APP_PROCESSES.get(requested)
    if process_names is None:
        return "Blocked: that application is not in ZENO's close allow-list. Nothing ran."

    windows = _matching_close_windows(process_names)
    if not windows:
        return f"Failed: no visible {requested} window was found; no process was terminated."

    requested_handles = {hwnd for hwnd, _pid, _title in windows}
    posted = {hwnd for hwnd in requested_handles if _post_close_message(hwnd)}
    if posted != requested_handles:
        return (f"Failed: Windows accepted {len(posted)} of {len(requested_handles)} graceful "
                f"close request(s) for {requested}; no process was terminated.")

    deadline = time.monotonic() + max(0.2, min(float(timeout_s), 10.0))
    remaining: set[int] = requested_handles
    while time.monotonic() < deadline:
        remaining = {
            hwnd for hwnd, _pid, _title in _matching_close_windows(process_names)
            if hwnd in requested_handles
        }
        if not remaining:
            return (f"Closed '{requested}'; postcondition verified: "
                    f"{len(requested_handles)} visible window(s) closed gracefully.")
        time.sleep(0.1)

    return (f"Failed: {len(remaining)} {requested} window(s) remain open, possibly for an "
            "unsaved-work prompt; no process was terminated.")


@register(
    name="list_dir",
    description="List files/folders in a directory. Read-only.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Folder path to list."},
        },
        "required": ["path"],
    },
)
def list_dir(path: str) -> str:
    path = os.path.expanduser(path)
    if not os.path.isdir(path):
        return f"'{path}' is not a folder (or doesn't exist)."
    entries = sorted(os.listdir(path))[:_MAX_LIST]
    if not entries:
        return f"'{path}' is empty."
    lines = []
    for name in entries:
        full = os.path.join(path, name)
        lines.append(f"{'[dir] ' if os.path.isdir(full) else ''}{name}")
    return "\n".join(lines)


@register(
    name="read_file",
    description="Read a text file's contents. Read-only.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to read."},
        },
        "required": ["path"],
    },
)
def read_file(path: str) -> str:
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        return f"'{path}' is not a file (or doesn't exist)."
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read(_MAX_READ_CHARS + 1)
    except OSError as exc:
        return f"Couldn't read '{path}': {exc}"
    if len(text) > _MAX_READ_CHARS:
        return text[:_MAX_READ_CHARS] + f"\n... [truncated, file is longer]"
    return text


def _resolve_start_app(name: str) -> tuple[str, str] | None:
    """Look the name up in the Start Menu app list (Get-StartApps) and
    return (display_name, AppID) of the best match -- this is what makes
    Store/UWP apps like WhatsApp, Spotify, and Phone Link launchable by
    name, since those have no plain .exe that os.startfile can find.
    Exact-ish match preferred, else first app whose name contains it.
    """
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-StartApps | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=15,
        ).stdout
        import json as _json

        apps = _json.loads(out) if out.strip() else []
        if isinstance(apps, dict):
            apps = [apps]
    except Exception:  # noqa: BLE001
        return None

    want = name.strip().lower()
    exact = [a for a in apps if a.get("Name", "").lower() == want]
    starts = [a for a in apps if a.get("Name", "").lower().startswith(want)]
    contains = [a for a in apps if want in a.get("Name", "").lower()]
    for bucket in (exact, starts, contains):
        if bucket:
            return bucket[0].get("Name"), bucket[0].get("AppID")
    return None


@register(
    name="open_app",
    description=(
        "Launch an application by name (e.g. 'notepad', 'chrome', "
        "'whatsapp', 'spotify') or full path. Resolves Store/UWP apps via "
        "the Start Menu too, so it isn't limited to classic .exe programs. "
        "ONLY use when the user explicitly asks to open/launch/start that "
        "app -- never as a side effect of answering an unrelated question."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name_or_path": {
                "type": "string",
                "description": "Application name (resolved via Windows/Start Menu) or a full path.",
            },
        },
        "required": ["name_or_path"],
    },
    light=True,
)
def open_app(name_or_path: str) -> str:
    before_pids = {process.pid for process in psutil.process_iter(["pid"])}
    # Direct launch first -- fastest for classic apps and full paths.
    try:
        os.startfile(name_or_path)  # noqa: S606 -- Windows app launch, not shell exec
        evidence = _verify_app_open(name_or_path, before_pids)
        if evidence:
            return f"Opened '{name_or_path}'; postcondition verified: {evidence}."
        return (f"Failed: the launch request for '{name_or_path}' returned, but ZENO "
                "could not verify a matching visible Windows window.")
    except OSError:
        pass

    # Fall back to Start Menu resolution for Store/UWP apps that have no
    # plain executable name (WhatsApp, Spotify, Phone Link, etc.).
    resolved = _resolve_start_app(name_or_path)
    if not resolved:
        return f"Couldn't find an app matching '{name_or_path}'."
    display, app_id = resolved
    try:
        os.startfile(f"shell:AppsFolder\\{app_id}")  # noqa: S606
        evidence = _verify_app_open(display, before_pids)
        if evidence:
            return f"Opened '{display}'; postcondition verified: {evidence}."
        return (f"Failed: the launch request for '{display}' returned, but ZENO "
                "could not verify a matching visible Windows window.")
    except OSError as exc:
        return f"Found '{display}' but couldn't launch it: {exc}"


@register(
    name="open_path",
    description="Open a file/folder in Explorer. Only when the user asks to see/open it.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File or folder path to open."},
        },
        "required": ["path"],
    },
)
def open_path(path: str) -> str:
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return f"'{path}' doesn't exist."
    try:
        os.startfile(path)  # noqa: S606
        return (f"Open request for '{path}' was accepted and the target exists; "
                "the resulting application/window was not independently verified.")
    except OSError as exc:
        return f"Couldn't open '{path}': {exc}"


@register(
    name="list_processes",
    description="List running process names. Read-only.",
    input_schema={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max processes to return. Default 30."},
        },
    },
)
def list_processes(limit: int = 30) -> str:
    try:
        limit = int(limit) if limit is not None else 30
    except (TypeError, ValueError):
        limit = 30
    names = sorted({p.info["name"] for p in psutil.process_iter(["name"]) if p.info["name"]})
    return "\n".join(names[:limit])


@register(
    name="delete_file",
    description="Permanently delete one file. This is irreversible and retains ZENO's high-impact confirmation safeguard.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to delete."},
        },
        "required": ["path"],
    },
    requires_confirmation=True,
)
def delete_file(path: str) -> str:
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        return f"'{path}' is not a file (or doesn't exist) -- nothing deleted."
    try:
        os.remove(path)
        return f"Deleted '{path}'."
    except OSError as exc:
        return f"Couldn't delete '{path}': {exc}"


@register(
    name="move_file",
    description="Move or rename one normal user file. A clear owner command authorizes a non-overwriting move directly.",
    input_schema={
        "type": "object",
        "properties": {
            "src": {"type": "string", "description": "Current file path."},
            "dst": {"type": "string", "description": "Destination path."},
        },
        "required": ["src", "dst"],
    },
    requires_confirmation=True,
)
def move_file(src: str, dst: str) -> str:
    import shutil

    src = os.path.expanduser(src)
    dst = os.path.expanduser(dst)
    if not os.path.isfile(src):
        return f"'{src}' is not a file (or doesn't exist) -- nothing moved."
    try:
        shutil.move(src, dst)
        return f"Moved '{src}' -> '{dst}'."
    except OSError as exc:
        return f"Couldn't move '{src}' to '{dst}': {exc}"


@register(
    name="run_command",
    description=(
        "Run one bounded shell command. Use only inside the owner's requested "
        "development/system task; destructive disk, financial, credential and "
        "security-changing commands remain blocked or high-impact."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The command to run."},
        },
        "required": ["command"],
    },
    requires_confirmation=True,
)
def run_command(command: str) -> str:
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30
        )
    except subprocess.TimeoutExpired:
        return f"Command timed out after 30s: {command}"
    output = (result.stdout or "") + (result.stderr or "")
    output = output.strip()[:_MAX_READ_CHARS]
    return f"Exit code {result.returncode}.\n{output}" if output else f"Exit code {result.returncode}. No output."


@register(
    name="media_control",
    description=(
        "Control music/media playback system-wide -- Spotify or whatever "
        "app currently holds media focus, same as a keyboard's hardware "
        "media keys. Use for play/pause, skip, previous, volume, and mute. "
        "To start a specific player like Spotify first, use open_app."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "play_pause",
                    "next",
                    "previous",
                    "volume_up",
                    "volume_down",
                    "mute",
                ],
                "description": "The media action to perform.",
            },
        },
        "required": ["action"],
    },
    light=True,
)
def media_control(action: str) -> str:
    try:
        import pyautogui
    except ImportError as exc:
        return f"pyautogui isn't available: {exc}"

    key_map = {
        "play_pause": "playpause",
        "next": "nexttrack",
        "previous": "prevtrack",
        "volume_up": "volumeup",
        "volume_down": "volumedown",
        "mute": "volumemute",
    }
    key = key_map.get(action)
    if not key:
        return f"Unknown media action '{action}'. Valid: {', '.join(key_map)}."
    pyautogui.press(key)
    return f"Sent '{action}' -- goes to whichever app currently holds media focus (Spotify, a browser tab, etc), same as a physical media key."


@register(
    name="send_slack_message",
    description=(
        "Attempt to send a message to a person or channel using the Slack desktop app "
        "already installed and logged in on this computer. Opens Slack, "
        "uses its Ctrl+K quick switcher to jump to the target, types the "
        "message, and presses send. Desktop automation cannot prove that "
        "Slack selected the intended recipient, so the result remains "
        "unverified until a real Slack API connection is configured. A current "
        "authenticated owner command using SEND/TELL authorizes that exact "
        "recipient and message; a draft request never sends."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Person or channel to message, e.g. 'John Smith' or '#general'.",
            },
            "message": {"type": "string", "description": "The message text to send."},
        },
        "required": ["target", "message"],
    },
    requires_confirmation=True,
)
def send_slack_message(target: str, message: str) -> str:
    import time

    try:
        import pyautogui
    except ImportError as exc:
        return f"pyautogui isn't available: {exc}"

    try:
        os.startfile("slack")
    except OSError as exc:
        return f"Couldn't open Slack: {exc}"

    time.sleep(2.5)  # let the app come to the foreground
    pyautogui.hotkey("ctrl", "k")  # Slack's built-in "Jump to" quick switcher
    time.sleep(0.6)
    pyautogui.typewrite(target, interval=0.02)
    time.sleep(1.0)
    pyautogui.press("enter")  # select the top match in the switcher
    time.sleep(1.0)
    pyautogui.typewrite(message, interval=0.01)
    pyautogui.press("enter")  # send

    return (
        f"Slack desktop automation pressed send for target '{target}', but no "
        "recipient or delivery evidence was available. The action is unverified; "
        "check Slack before relying on it."
    )


# Only browsers actually found here get offered by name -- no point
# claiming "Firefox" works when it isn't installed on this machine.
_BROWSER_CANDIDATES = {
    "chrome": [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ],
    "edge": [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
    ],
    "firefox": [
        os.path.expandvars(r"%ProgramFiles%\Mozilla Firefox\firefox.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe"),
    ],
    "brave": [
        os.path.expandvars(r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ],
}


def _installed_browsers() -> dict[str, str]:
    found = {}
    for name, paths in _BROWSER_CANDIDATES.items():
        path = next((p for p in paths if os.path.isfile(p)), None)
        if path:
            found[name] = path
    return found


@register(
    name="web_search",
    description=(
        "Search the web for something by opening it in a browser. Defaults "
        "to Chrome; pass 'browser' to use a specific one (edge, firefox, "
        "brave) if the user names one and it's actually installed. This "
        "opens a real search results page for the user to read -- it does "
        "NOT fetch or read results back into the conversation, REYES has "
        "no browsing/scraping tool for that. Use when the user asks to "
        "search/look something up online."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for."},
            "browser": {
                "type": "string",
                "description": "Which browser to use, e.g. 'chrome', 'edge', 'firefox'. Default: chrome.",
            },
        },
        "required": ["query"],
    },
    light=True,
)
def web_search(query: str, browser: str = "chrome") -> str:
    import urllib.parse

    url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
    installed = _installed_browsers()
    requested = (browser or "chrome").strip().lower()

    path = installed.get(requested)
    used = requested if path else None
    if not path and installed:
        # Asked-for browser isn't installed -- fall back to whatever is,
        # preferring chrome, rather than failing outright.
        used = "chrome" if "chrome" in installed else next(iter(installed))
        path = installed[used]

    try:
        if path:
            subprocess.Popen([path, url])
        else:
            os.startfile(url)  # noqa: S606 -- last resort: OS-registered default browser
    except OSError as exc:
        return f"Couldn't open the browser: {exc}"

    note = ""
    if requested != "chrome" and used != requested:
        note = f" ({browser} isn't installed here, used {used or 'the system default'} instead)"
    label = used or "the default browser"
    return (
        f"Opened a search for {query!r} in {label}.{note} REYES can't read "
        "the results itself -- no browsing tool for that yet -- so take a "
        "look at the page directly."
    )


@register(
    name="show_map",
    description=(
        "Open Google Maps to a place, address, or 'A to B' directions in "
        "the browser. Use when the user asks to see a map, find a location, "
        "or get directions somewhere."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "Place/address, or 'from X to Y' for directions."},
        },
        "required": ["location"],
    },
    light=True,
)
def show_map(location: str) -> str:
    import urllib.parse

    loc = location.strip()
    low = loc.lower()
    # Google's keyless embed endpoint (maps.google.com/maps?...&output=embed)
    # renders straight inside REYES's own panel via an iframe -- no browser
    # tab, no API key.
    if " to " in low and (low.startswith("from ") or "directions" in low):
        cleaned = loc[5:] if low.startswith("from ") else loc
        parts = cleaned.split(" to ", 1)
        embed = (
            "https://maps.google.com/maps?"
            f"saddr={urllib.parse.quote(parts[0].strip())}"
            f"&daddr={urllib.parse.quote(parts[1].strip())}&output=embed"
        )
    else:
        embed = f"https://maps.google.com/maps?q={urllib.parse.quote(loc)}&output=embed"

    try:
        from reyes_agent import notification_bus

        notification_bus.publish({"type": "show_map", "location": loc, "embed_url": embed})
    except Exception as exc:  # noqa: BLE001
        return f"Couldn't display the map: {exc}"
    return f"Showing a map of '{loc}' in the REYES panel."


@register(
    name="get_news",
    description=(
        "Fetch current news headlines -- top stories, or about a specific "
        "topic/place if given -- and read them back. Unlike web_search this "
        "actually returns the headlines into the conversation. Use when the "
        "user asks what's happening, for the news, or news about something."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Optional topic/place, e.g. 'football', 'Nigeria'. Blank = top headlines."},
            "limit": {"type": "integer", "description": "How many headlines. Default 6."},
        },
    },
    light=True,
)
def get_news(topic: str = "", limit: int = 6) -> str:
    import urllib.parse
    import xml.etree.ElementTree as ET

    import requests

    try:
        limit = max(1, min(15, int(limit)))
    except (TypeError, ValueError):
        limit = 6
    if topic.strip():
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(topic.strip())}&hl=en-US&gl=US&ceid=US:en"
    else:
        url = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as exc:  # noqa: BLE001
        return f"Couldn't fetch the news: {exc}"
    items = root.findall(".//item")[:limit]
    if not items:
        return "No headlines came back."
    lines = []
    headlines = []
    for it in items:
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        source = (it.findtext("source") or "").strip()
        if title:
            lines.append(f"- {title}")
            headlines.append({"title": title, "link": link, "source": source})
    label = f"Top headlines about '{topic.strip()}'" if topic.strip() else "Top headlines"

    # News workspace overlay -- same notification_bus -> SSE -> panel
    # pattern as show_map, so headlines get a real readable panel in the
    # REYES UI instead of only a spoken/captioned list.
    try:
        from reyes_agent import notification_bus

        notification_bus.publish({"type": "workspace_news", "topic": label, "headlines": headlines})
    except Exception:  # noqa: BLE001
        pass

    return f"{label}:\n" + "\n".join(lines)


@register(
    name="send_telegram_message",
    description=(
        "Send a message to the user's own Telegram, via REYES's bot "
        "(@Reyes3_boss_bot). Only sends to the one chat already set up "
        "for this user -- not a general Telegram messaging tool for "
        "other people or chats. A current authenticated owner SEND command "
        "authorizes that exact message without a duplicate prompt; drafting "
        "alone never sends."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "The message text to send."},
        },
        "required": ["message"],
    },
    requires_confirmation=True,
)
def send_telegram_message(message: str) -> str:
    from reyes_agent import config

    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_NOTIFY_CHAT_ID:
        return "Telegram isn't configured -- missing TELEGRAM_BOT_TOKEN or TELEGRAM_NOTIFY_CHAT_ID in .env."

    import requests

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": config.TELEGRAM_NOTIFY_CHAT_ID, "text": message},
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        return f"Couldn't send the Telegram message: {exc}"
    except (TypeError, ValueError) as exc:
        return f"Telegram returned an invalid response: {exc}"

    result = payload.get("result", {}) if isinstance(payload, dict) else {}
    message_id = result.get("message_id") if isinstance(result, dict) else None
    if payload.get("ok") is not True or not isinstance(message_id, int):
        description = payload.get("description", "missing message confirmation") if isinstance(payload, dict) else "invalid response"
        return f"Telegram did not confirm the message: {description}"

    return (
        f"Telegram accepted the message as ID {message_id}; postcondition verified "
        "from the authenticated provider response."
    )


# --- ZENO Hands ---------------------------------------------------------
# Expose the existing gated/verified computer.agentic engine (type / press keys
# / click by description / scroll) as brain tools. Imported here -- next to the
# other desktop-control tools -- so the shared tool loader registers them without
# a second edit to tools/__init__.py.
from reyes_agent.tools import hands_tools as _hands_tools  # noqa: E402,F401


# ZENO Live News: the multi-source, de-duplicated, recency+quality-ranked news
# pipeline exposed as the `live_news` tool. Imported here so the shared loader
# registers it (reuses news_engine + the same RSS source as get_news).
from reyes_agent.tools import news_tools as _news_tools  # noqa: E402,F401


# ZENO Sports Intelligence: evidence-based match prediction (Elo + Poisson).
from reyes_agent.tools import sports_tools as _sports_tools  # noqa: E402,F401


# ZENO Career Intelligence: analysis (scoring/ATS/scam) over the paid_work engine.
from reyes_agent.tools import career_intelligence_tools as _career_intel  # noqa: E402,F401


# ZENO Spatial Memory (eMEM adapter): structured tools to remember where objects
# are, recall last-known locations, and query spatial events by place/time/meaning.
# Imported here so the shared loader registers them; the backend is optional and
# degrades gracefully if eMEM is unavailable.
from reyes_agent.tools import spatial_tools as _spatial_tools  # noqa: E402,F401
