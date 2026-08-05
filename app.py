from __future__ import annotations

import glob
import os
import shutil
import subprocess
from pathlib import Path


# =========================================================
# PATH HELPERS
# =========================================================

def find_app_path(*possible_paths: str) -> str | None:
    """
    Return the first existing application path.
    """
    for possible_path in possible_paths:
        expanded = os.path.expandvars(possible_path)

        if os.path.isfile(expanded):
            return expanded

    return None


def find_first_match(*patterns: str) -> str | None:
    """
    Return the first executable matching one of the wildcard patterns.
    """
    for pattern in patterns:
        expanded_pattern = os.path.expandvars(pattern)
        matches = glob.glob(expanded_pattern)

        if matches:
            matches.sort(reverse=True)

            for match in matches:
                if os.path.isfile(match):
                    return match

    return None


def find_command(command: str) -> str | None:
    """
    Find an executable available through the Windows PATH.
    """
    return shutil.which(command)


# =========================================================
# BUILT-IN WINDOWS APPLICATIONS
# =========================================================

APPS: dict[str, str] = {}

_builtin_apps = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "cmd": "cmd.exe",
    "command prompt": "cmd.exe",
    "powershell": "powershell.exe",
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
    "task manager": "taskmgr.exe",
}

for app_name, executable in _builtin_apps.items():
    APPS[app_name] = find_command(executable) or executable


# =========================================================
# BROWSERS
# =========================================================

chrome_path = find_app_path(
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
)

if chrome_path:
    APPS["chrome"] = chrome_path
    APPS["google chrome"] = chrome_path


edge_path = find_app_path(
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)

if edge_path:
    APPS["edge"] = edge_path
    APPS["microsoft edge"] = edge_path


firefox_path = find_app_path(
    r"C:\Program Files\Mozilla Firefox\firefox.exe",
    r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
)

if firefox_path:
    APPS["firefox"] = firefox_path


# =========================================================
# DEVELOPMENT TOOLS
# =========================================================

vscode_path = find_app_path(
    r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
    r"C:\Program Files\Microsoft VS Code\Code.exe",
    r"C:\Program Files (x86)\Microsoft VS Code\Code.exe",
)

if vscode_path:
    APPS["vscode"] = vscode_path
    APPS["visual studio code"] = vscode_path
    APPS["vs code"] = vscode_path
    APPS["code"] = vscode_path


# =========================================================
# COMMUNICATION APPLICATIONS
# =========================================================

slack_path = (
    find_app_path(
        r"%LOCALAPPDATA%\slack\slack.exe",
        r"%LOCALAPPDATA%\Programs\slack\slack.exe",
    )
    or find_first_match(
        r"%LOCALAPPDATA%\slack\app-*\slack.exe",
    )
)

if slack_path:
    APPS["slack"] = slack_path


discord_path = (
    find_app_path(
        r"%LOCALAPPDATA%\Programs\Discord\Discord.exe",
    )
    or find_first_match(
        r"%LOCALAPPDATA%\Discord\app-*\Discord.exe",
    )
)

if discord_path:
    APPS["discord"] = discord_path


telegram_path = find_app_path(
    r"%APPDATA%\Telegram Desktop\Telegram.exe",
    r"%LOCALAPPDATA%\Programs\Telegram Desktop\Telegram.exe",
)

if telegram_path:
    APPS["telegram"] = telegram_path


whatsapp_path = find_app_path(
    r"%LOCALAPPDATA%\WhatsApp\WhatsApp.exe",
    r"%LOCALAPPDATA%\Programs\WhatsApp\WhatsApp.exe",
)

if whatsapp_path:
    APPS["whatsapp"] = whatsapp_path


# =========================================================
# MEDIA APPLICATIONS
# =========================================================

spotify_path = find_app_path(
    r"%APPDATA%\Spotify\Spotify.exe",
    r"%LOCALAPPDATA%\Microsoft\WindowsApps\Spotify.exe",
)

if spotify_path:
    APPS["spotify"] = spotify_path


vlc_path = find_app_path(
    r"C:\Program Files\VideoLAN\VLC\vlc.exe",
    r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
)

if vlc_path:
    APPS["vlc"] = vlc_path


# =========================================================
# MICROSOFT OFFICE
# =========================================================

_office_executables = {
    "word": "WINWORD.EXE",
    "excel": "EXCEL.EXE",
    "powerpoint": "POWERPNT.EXE",
    "outlook": "OUTLOOK.EXE",
    "onenote": "ONENOTE.EXE",
}

for app_name, executable_name in _office_executables.items():
    app_path = find_first_match(
        rf"C:\Program Files\Microsoft Office\root\Office*\{executable_name}",
        rf"C:\Program Files (x86)\Microsoft Office\root\Office*\{executable_name}",
        rf"C:\Program Files\Microsoft Office\Office*\{executable_name}",
        rf"C:\Program Files (x86)\Microsoft Office\Office*\{executable_name}",
    )

    if app_path:
        APPS[app_name] = app_path


# =========================================================
# NAME NORMALIZATION
# =========================================================

def normalize_app_name(name: str) -> str:
    """
    Convert common aliases into canonical application names.
    """
    normalized = name.strip().lower()

    aliases = {
        "google": "chrome",
        "browser": "chrome",
        "files": "file explorer",
        "file manager": "file explorer",
        "windows explorer": "file explorer",
        "terminal": "powershell",
        "windows terminal": "powershell",
        "visual studio": "vscode",
        "visual studio code": "vscode",
        "vs code": "vscode",
        "microsoft word": "word",
        "ms word": "word",
        "microsoft excel": "excel",
        "ms excel": "excel",
        "microsoft powerpoint": "powerpoint",
        "ms powerpoint": "powerpoint",
        "ppt": "powerpoint",
    }

    return aliases.get(normalized, normalized)


# =========================================================
# OPEN APPLICATION
# =========================================================

def open_app(name: str) -> str:
    """
    Open an installed application.
    """
    app_name = normalize_app_name(name)

    if not app_name:
        return "Please tell me which application to open."

    app_path = APPS.get(app_name)

    if not app_path:
        return (
            f"I could not find '{name}' on this computer. "
            "It may not be installed, or its installation path may be different."
        )

    try:
        subprocess.Popen(
            [app_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )

        return f"Opening {app_name.title()}."

    except FileNotFoundError:
        return (
            f"I found the entry for {app_name}, but Windows could not "
            "locate its executable."
        )

    except OSError as error:
        return f"I could not open {app_name}: {error}"


# =========================================================
# CLOSE APPLICATION
# =========================================================

PROCESS_NAMES = {
    "notepad": "notepad.exe",
    "calculator": "CalculatorApp.exe",
    "paint": "mspaint.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "file explorer": "explorer.exe",
    "task manager": "taskmgr.exe",
    "chrome": "chrome.exe",
    "edge": "msedge.exe",
    "firefox": "firefox.exe",
    "vscode": "Code.exe",
    "slack": "slack.exe",
    "discord": "Discord.exe",
    "whatsapp": "WhatsApp.exe",
    "telegram": "Telegram.exe",
    "spotify": "Spotify.exe",
    "vlc": "vlc.exe",
    "word": "WINWORD.EXE",
    "excel": "EXCEL.EXE",
    "powerpoint": "POWERPNT.EXE",
    "outlook": "OUTLOOK.EXE",
    "onenote": "ONENOTE.EXE",
}


def close_app(name: str) -> str:
    """
    Close an application by its Windows process name.
    """
    app_name = normalize_app_name(name)
    process_name = PROCESS_NAMES.get(app_name)

    if not process_name:
        return f"I do not yet know how to close '{name}'."

    try:
        result = subprocess.run(
            ["taskkill", "/F", "/IM", process_name],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode == 0:
            return f"{app_name.title()} closed."

        return f"{app_name.title()} does not appear to be running."

    except OSError as error:
        return f"I could not close {app_name}: {error}"


# =========================================================
# APPLICATION LIST
# =========================================================

def get_detected_apps() -> list[str]:
    """Return all detected and supported application names."""
    return sorted(set(APPS.keys()))


def list_detected_apps() -> str:
    """Return a readable detected-application list."""
    detected = get_detected_apps()

    if not detected:
        return "I did not detect any supported applications."

    return "Detected applications: " + ", ".join(detected)


if __name__ == "__main__":
    print(list_detected_apps())