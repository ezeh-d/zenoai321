"""Application Executor -- open the right window, once.

The requirement that shapes this module is "do not repeatedly open
duplicate windows". A build that opens Explorer at every file write, or a
browser tab per verification pass, is worse than one that opens nothing.

So every open here is recorded against its target, and a repeat request
within `_DEDUPE_SECONDS` reports the existing window instead of spawning
another. On Windows an already-open Explorer window for the same folder is
also detected before opening a new one.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

_lock = threading.Lock()
_opened: dict[str, float] = {}

# Long enough to absorb a retry loop or a chatty verification pass, short
# enough that the owner asking again a minute later really does get a window.
_DEDUPE_SECONDS = 90.0


def _recently_opened(key: str) -> bool:
    now = time.time()
    with _lock:
        for stale, when in list(_opened.items()):
            if now - when > _DEDUPE_SECONDS:
                _opened.pop(stale, None)
        last = _opened.get(key)
        if last is not None and now - last <= _DEDUPE_SECONDS:
            return True
        _opened[key] = now
    return False


def _explorer_already_showing(folder: Path) -> bool:
    """Ask Windows whether an Explorer window is already on this folder."""
    if sys.platform != "win32":
        return False
    script = (
        "$app = New-Object -ComObject Shell.Application; "
        "$app.Windows() | ForEach-Object { try { $_.Document.Folder.Self.Path } catch {} }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=12, check=False,
        )
    except Exception:  # noqa: BLE001 -- detection is an optimisation, never a blocker
        return False
    target = str(folder).rstrip("\\/").casefold()
    return any(line.strip().rstrip("\\/").casefold() == target
               for line in (result.stdout or "").splitlines())


def open_folder(path: Path | str) -> tuple[bool, str]:
    """Show a folder in the file manager."""
    folder = Path(path)
    if not folder.is_dir():
        return False, f"{folder} is not a folder that exists."
    key = f"folder:{str(folder.resolve()).casefold()}"
    if _recently_opened(key):
        return True, f"Explorer is already showing {folder}."
    if _explorer_already_showing(folder):
        return True, f"Explorer is already showing {folder}."
    try:
        if sys.platform == "win32":
            # explorer.exe returns a non-zero exit code even on success, so
            # its return value is deliberately not treated as an outcome.
            subprocess.Popen(["explorer", str(folder)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except OSError as exc:
        with _lock:
            _opened.pop(key, None)
        return False, f"Could not open {folder}: {exc}"
    return True, f"Opened {folder} in the file manager."


def open_url(url: str) -> tuple[bool, str]:
    """Open a URL in the default browser, without stacking tabs."""
    url = str(url or "").strip()
    if not url:
        return False, "No URL was given."
    key = f"url:{url.casefold()}"
    if _recently_opened(key):
        return True, f"{url} is already open in your browser."
    try:
        opened = webbrowser.open(url, new=2)
    except Exception as exc:  # noqa: BLE001
        with _lock:
            _opened.pop(key, None)
        return False, f"Could not open {url}: {exc}"
    if not opened:
        with _lock:
            _opened.pop(key, None)
        return False, f"No browser handler accepted {url}."
    return True, f"Opened {url} in your default browser."


def open_editor(path: Path | str) -> tuple[bool, str]:
    """Open the project in VS Code when it is installed.

    Reports plainly when it is not, rather than silently doing nothing --
    a step that claims to have opened an editor that is not installed is
    the exact failure mode this whole change is about.
    """
    import shutil

    folder = Path(path)
    if not folder.exists():
        return False, f"{folder} does not exist."
    code = shutil.which("code") or shutil.which("code-insiders")
    if not code:
        return False, "VS Code is not installed (no `code` on PATH)."
    key = f"editor:{str(folder.resolve()).casefold()}"
    if _recently_opened(key):
        return True, f"VS Code is already open on {folder}."
    try:
        subprocess.Popen([code, str(folder)], shell=False)
    except OSError as exc:
        with _lock:
            _opened.pop(key, None)
        return False, f"Could not start VS Code: {exc}"
    return True, f"Opened {folder} in VS Code."


def reveal_file(path: Path | str) -> tuple[bool, str]:
    """Select one file inside its folder."""
    target = Path(path)
    if not target.exists():
        return False, f"{target} does not exist."
    if sys.platform != "win32":
        return open_folder(target.parent)
    key = f"reveal:{str(target.resolve()).casefold()}"
    if _recently_opened(key):
        return True, f"{target.name} was already revealed."
    try:
        subprocess.Popen(["explorer", "/select,", os.path.normpath(str(target))])
    except OSError as exc:
        with _lock:
            _opened.pop(key, None)
        return False, f"Could not reveal {target}: {exc}"
    return True, f"Revealed {target.name} in Explorer."


def reset_dedupe() -> None:
    """Test hook -- forget what has been opened."""
    with _lock:
        _opened.clear()
