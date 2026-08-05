# commands.py

from __future__ import annotations

import difflib
import glob
import logging
import os
import re
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import quote_plus

# Config values are optional so this module still works standalone.
try:
    from config import BLOCKED_COMMANDS, CONFIRM_BEFORE_OVERWRITE
except ImportError:
    BLOCKED_COMMANDS = []
    CONFIRM_BEFORE_OVERWRITE = True

logger = logging.getLogger("reyes.commands")


# =========================================================
# PATHS
# =========================================================

DESKTOP_DIR = Path.home() / "Desktop"
DOWNLOADS_DIR = Path.home() / "Downloads"
DOCUMENTS_DIR = Path.home() / "Documents"

KNOWN_FOLDERS: dict[str, Path] = {
    "desktop": DESKTOP_DIR,
    "downloads": DOWNLOADS_DIR,
    "documents": DOCUMENTS_DIR,
}


# =========================================================
# APP DETECTION
# =========================================================

def find_app_path(*possible_paths: str) -> str | None:
    """
    Return the first application path that exists.
    """

    for possible_path in possible_paths:
        expanded_path = os.path.expandvars(possible_path)

        if os.path.exists(expanded_path):
            return expanded_path

    return None


def find_first_glob(*patterns: str) -> str | None:
    """
    Search several wildcard patterns and return the first match.
    """

    for pattern in patterns:
        matches = glob.glob(os.path.expandvars(pattern))

        if matches:
            matches.sort(reverse=True)
            return matches[0]

    return None


APPS: dict[str, str] = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
    "command prompt": "cmd.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "paint": "mspaint.exe",
    "task manager": "taskmgr.exe",
    "settings": "ms-settings:",  # handled specially in open_app
}


def _register(names: list[str], path: str | None) -> None:
    """
    Register an app under one or more names if it was found.
    """

    if not path:
        return

    for name in names:
        APPS[name] = path


# ---------- Browsers ----------

_register(
    ["chrome", "google chrome"],
    find_app_path(
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
    ),
)

_register(
    ["edge", "microsoft edge"],
    find_app_path(
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ),
)

_register(
    ["firefox"],
    find_app_path(
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
    ),
)

_register(
    ["brave"],
    find_app_path(
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe",
    ),
)

# ---------- Communication ----------

_register(
    ["slack"],
    find_app_path(
        r"%LOCALAPPDATA%\slack\slack.exe",
        r"%LOCALAPPDATA%\Programs\slack\slack.exe",
    )
    or find_first_glob(r"%LOCALAPPDATA%\slack\app-*\slack.exe"),
)

_register(
    ["discord"],
    find_app_path(
        r"%LOCALAPPDATA%\Discord\Update.exe",
        r"%LOCALAPPDATA%\Programs\Discord\Discord.exe",
    ),
)

_register(
    ["teams", "microsoft teams"],
    find_app_path(
        r"%LOCALAPPDATA%\Microsoft\WindowsApps\ms-teams.exe",
        r"%LOCALAPPDATA%\Microsoft\Teams\current\Teams.exe",
    ),
)

_register(
    ["whatsapp"],
    find_app_path(
        r"%LOCALAPPDATA%\WhatsApp\WhatsApp.exe",
        r"%LOCALAPPDATA%\Programs\WhatsApp\WhatsApp.exe",
    ),
)

_register(
    ["telegram"],
    find_app_path(
        r"%APPDATA%\Telegram Desktop\Telegram.exe",
        r"%LOCALAPPDATA%\Programs\Telegram Desktop\Telegram.exe",
    ),
)

_register(
    ["zoom"],
    find_app_path(
        r"%APPDATA%\Zoom\bin\Zoom.exe",
        r"%LOCALAPPDATA%\Zoom\bin\Zoom.exe",
    ),
)

# ---------- Development ----------

_register(
    ["vscode", "visual studio code", "code"],
    find_app_path(
        r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
        r"C:\Program Files\Microsoft VS Code\Code.exe",
    ),
)

_register(
    ["github desktop"],
    find_app_path(r"%LOCALAPPDATA%\GitHubDesktop\GitHubDesktop.exe"),
)

# ---------- Media ----------

_register(
    ["spotify"],
    find_app_path(
        r"%APPDATA%\Spotify\Spotify.exe",
        r"%LOCALAPPDATA%\Microsoft\WindowsApps\Spotify.exe",
    ),
)

_register(
    ["vlc"],
    find_app_path(
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
    ),
)

# ---------- Microsoft Office ----------

_OFFICE_APPS = {
    "word": "WINWORD.EXE",
    "excel": "EXCEL.EXE",
    "powerpoint": "POWERPNT.EXE",
    "outlook": "OUTLOOK.EXE",
    "onenote": "ONENOTE.EXE",
}

for _app_name, _executable_name in _OFFICE_APPS.items():
    _register(
        [_app_name],
        find_first_glob(
            rf"C:\Program Files\Microsoft Office\root\Office*\{_executable_name}",
            rf"C:\Program Files (x86)\Microsoft Office\root\Office*\{_executable_name}",
            rf"C:\Program Files\Microsoft Office\Office*\{_executable_name}",
            rf"C:\Program Files (x86)\Microsoft Office\Office*\{_executable_name}",
        ),
    )


# =========================================================
# APPLICATION CONTROL
# =========================================================

ALIASES: dict[str, str] = {
    "files": "file explorer",
    "file manager": "file explorer",
    "explorer": "file explorer",
    "google": "chrome",
    "browser": "chrome",
    "ms word": "word",
    "microsoft word": "word",
    "ms excel": "excel",
    "microsoft excel": "excel",
    "ppt": "powerpoint",
    "power point": "powerpoint",
    "ms teams": "teams",
    "visual studio": "vscode",
    "vs code": "vscode",
    "terminal": "command prompt",
}


def normalize_app_name(name: str) -> str:
    """
    Normalize common application aliases.
    """

    normalized = name.strip().lower()
    return ALIASES.get(normalized, normalized)


def _closest_app_name(name: str) -> str | None:
    """
    Suggest the closest known app name for a typo or mishearing.
    """

    matches = difflib.get_close_matches(name, APPS.keys(), n=1, cutoff=0.7)
    return matches[0] if matches else None


def open_app(name: str) -> str:
    """
    Open an installed desktop application.
    """

    app_name = normalize_app_name(name)

    if app_name not in APPS:
        suggestion = _closest_app_name(app_name)

        if suggestion:
            return (
                f"I could not find '{name}'. "
                f"Did you mean '{suggestion}'?"
            )

        return (
            f"I could not find '{name}' on this computer. "
            "The app may not be installed or its installation path may be different. "
            "Say 'list apps' to see what I detected."
        )

    target = APPS[app_name]

    try:
        # Windows Settings uses a URI, not an executable.
        if target.startswith("ms-settings"):
            os.startfile(target)
        else:
            subprocess.Popen(
                [target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        logger.info("Opened app: %s (%s)", app_name, target)
        return f"{app_name.title()} opened."

    except OSError as error:
        logger.error("Failed to open %s: %s", app_name, error)
        return f"I could not open {app_name}: {error}"


def _executable_for(app_name: str) -> str | None:
    """
    Work out the process executable name for closing an app.
    """

    known = {
        "notepad": "notepad.exe",
        "calculator": "CalculatorApp.exe",
        "calc": "CalculatorApp.exe",
        "chrome": "chrome.exe",
        "edge": "msedge.exe",
        "firefox": "firefox.exe",
        "brave": "brave.exe",
        "slack": "slack.exe",
        "discord": "Discord.exe",
        "teams": "ms-teams.exe",
        "whatsapp": "WhatsApp.exe",
        "telegram": "Telegram.exe",
        "zoom": "Zoom.exe",
        "vscode": "Code.exe",
        "word": "WINWORD.EXE",
        "excel": "EXCEL.EXE",
        "powerpoint": "POWERPNT.EXE",
        "outlook": "OUTLOOK.EXE",
        "onenote": "ONENOTE.EXE",
        "spotify": "Spotify.exe",
        "vlc": "vlc.exe",
        "paint": "mspaint.exe",
    }

    executable = known.get(app_name)

    if executable:
        return executable

    # Fallback: use the basename of the detected install path.
    path = APPS.get(app_name)

    if path and path.lower().endswith(".exe"):
        return os.path.basename(path)

    return None


def close_app(name: str) -> str:
    """
    Close an application by its executable name.
    """

    app_name = normalize_app_name(name)
    executable = _executable_for(app_name)

    if not executable:
        return f"I do not yet know how to close '{name}'."

    try:
        result = subprocess.run(
            ["taskkill", "/IM", executable],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode == 0:
            logger.info("Closed app: %s", app_name)
            return f"{app_name.title()} closed."

        return f"{app_name.title()} does not appear to be running."

    except OSError as error:
        logger.error("Failed to close %s: %s", app_name, error)
        return f"I could not close {app_name}: {error}"


def list_detected_apps() -> str:
    """
    Return all applications currently detected by REYES.
    """

    detected = sorted(set(APPS.keys()))

    return "Detected applications: " + ", ".join(detected)


# =========================================================
# FILE AND FOLDER OPERATIONS
# =========================================================

def sanitize_filename(name: str) -> str:
    """
    Remove characters that Windows does not allow in file names.
    """

    cleaned = re.sub(r'[\\/:*?"<>|]', "", name).strip()

    # Also strip trailing dots/spaces, which Windows rejects.
    return cleaned.rstrip(". ")


def create_folder(name: str, location: str = "desktop") -> str:
    """
    Create a folder in a safe known location.
    """

    folder_name = sanitize_filename(name) or "New Folder"

    base_directory = KNOWN_FOLDERS.get(location.lower(), DESKTOP_DIR)
    folder_path = base_directory / folder_name

    if folder_path.exists():
        return f"The folder '{folder_name}' already exists in {base_directory.name}."

    try:
        folder_path.mkdir(parents=True, exist_ok=True)
        logger.info("Created folder: %s", folder_path)
        return f"Folder '{folder_name}' created in {base_directory.name}."

    except OSError as error:
        logger.error("Failed to create folder %s: %s", folder_path, error)
        return f"I could not create the folder: {error}"


def create_text_file(name: str, content: str = "") -> str:
    """
    Create a text file on the desktop.
    """

    file_name = sanitize_filename(name)

    if not file_name:
        return "Please provide a valid file name."

    if not file_name.lower().endswith(".txt"):
        file_name += ".txt"

    file_path = DESKTOP_DIR / file_name

    if file_path.exists() and CONFIRM_BEFORE_OVERWRITE:
        return (
            f"The file '{file_name}' already exists. "
            "Confirmation is required before overwriting it."
        )

    try:
        file_path.write_text(content, encoding="utf-8")
        logger.info("Created text file: %s", file_path)
        return f"Text file '{file_name}' created on the Desktop."

    except OSError as error:
        logger.error("Failed to create file %s: %s", file_path, error)
        return f"I could not create the file: {error}"


def open_folder(name: str) -> str:
    """
    Open a standard Windows folder.
    """

    folder = KNOWN_FOLDERS.get(name.strip().lower())

    if not folder:
        return f"I do not recognize the folder '{name}'."

    try:
        os.startfile(folder)
        return f"{folder.name} opened."

    except OSError as error:
        logger.error("Failed to open folder %s: %s", folder, error)
        return f"I could not open {folder.name}: {error}"


# =========================================================
# WEB SEARCH
# =========================================================

def google_search(query: str) -> str:
    """
    Search Google in the default browser.
    """

    clean_query = query.strip()

    if not clean_query:
        return "Please tell me what to search for."

    webbrowser.open(f"https://www.google.com/search?q={quote_plus(clean_query)}")
    return f"Searching Google for '{clean_query}'."


def youtube_search(query: str) -> str:
    """
    Search YouTube in the default browser.
    """

    clean_query = query.strip()

    if not clean_query:
        return "Please tell me what to search for on YouTube."

    webbrowser.open(
        f"https://www.youtube.com/results?search_query={quote_plus(clean_query)}"
    )

    return f"Searching YouTube for '{clean_query}'."


def open_website(address: str) -> str:
    """
    Open a website.
    """

    clean_address = address.strip()

    if not clean_address:
        return "Please provide a website address."

    if not clean_address.startswith(("http://", "https://")):
        clean_address = "https://" + clean_address

    webbrowser.open(clean_address)
    return f"Opening {clean_address}."


# =========================================================
# SLACK
# =========================================================

def open_slack() -> str:
    """
    Open the Slack desktop application.
    """

    return open_app("slack")


def prepare_slack_message(recipient: str, message: str) -> str:
    """
    Prepare a Slack message for confirmation.

    Actual sending will be handled by the Slack integration module.
    """

    clean_recipient = recipient.strip()
    clean_message = message.strip()

    if not clean_recipient:
        return "Please specify a Slack channel or person."

    if not clean_message:
        return "Please specify the message to send."

    return (
        f"Ready to send this Slack message to '{clean_recipient}': "
        f"\"{clean_message}\". Please confirm before I send it."
    )


# =========================================================
# COMMAND PARSING
# =========================================================

def is_blocked_command(command: str) -> bool:
    """
    Safety net: block dangerous commands defined in config.
    """

    lowered = command.lower()

    return any(blocked.lower() in lowered for blocked in BLOCKED_COMMANDS)


def extract_send_message_command(command: str) -> tuple[str, str] | None:
    """
    Extract recipient and message from commands such as:

    send slack message to john saying hello
    message general on slack saying good morning
    """

    patterns = [
        r"^send (?:a )?slack message to (.+?) saying (.+)$",
        r"^send (?:a )?message to (.+?) on slack saying (.+)$",
        r"^message (.+?) on slack saying (.+)$",
        r"^tell (.+?) on slack (.+)$",
    ]

    for pattern in patterns:
        match = re.match(pattern, command, flags=re.IGNORECASE)

        if match:
            recipient = match.group(1).strip()
            message = match.group(2).strip()
            return recipient, message

    return None


def _extract_folder_command(command: str) -> tuple[str, str] | None:
    """
    Parse folder creation with an optional location, e.g.:

    create folder projects
    create folder invoices in documents
    create a folder called music in downloads
    """

    match = re.match(
        r"^create (?:a )?folder (?:called |named )?(.+?)"
        r"(?: in (desktop|downloads|documents))?$",
        command,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    name = match.group(1).strip()
    location = (match.group(2) or "desktop").lower()

    return name, location


def execute_command(command: str) -> str:
    """
    Execute a supported REYES desktop command.
    """

    clean_command = command.strip()

    if not clean_command:
        return "Please give me a command."

    if is_blocked_command(clean_command):
        logger.warning("Blocked dangerous command: %s", clean_command)
        return "That command is blocked for safety reasons."

    lower_command = clean_command.lower()

    slack_message = extract_send_message_command(clean_command)

    if slack_message:
        recipient, message = slack_message
        return prepare_slack_message(recipient, message)

    folder_command = _extract_folder_command(clean_command)

    if folder_command:
        name, location = folder_command
        return create_folder(name, location)

    if lower_command.startswith("open app "):
        return open_app(clean_command[9:])

    if lower_command.startswith(("open ", "launch ", "start ")):
        target = clean_command.split(" ", 1)[1].strip()

        if target.lower() in KNOWN_FOLDERS:
            return open_folder(target)

        if "." in target and " " not in target:
            return open_website(target)

        return open_app(target)

    if lower_command.startswith(("close ", "quit ", "exit ")):
        return close_app(clean_command.split(" ", 1)[1])

    if lower_command.startswith("create text file "):
        return create_text_file(clean_command[17:])

    if lower_command.startswith("search google for "):
        return google_search(clean_command[18:])

    if lower_command.startswith("google "):
        return google_search(clean_command[7:])

    if lower_command.startswith("search youtube for "):
        return youtube_search(clean_command[19:])

    if lower_command.startswith("youtube "):
        return youtube_search(clean_command[8:])

    if lower_command in {"open slack", "start slack"}:
        return open_slack()

    if lower_command in {
        "list apps",
        "show apps",
        "what apps can you open",
        "detected apps",
    }:
        return list_detected_apps()

    if lower_command in {"what is the date", "date", "today's date", "what day is it"}:
        return datetime.now().strftime("Today is %A, %d %B %Y.")

    if lower_command in {"what time is it", "time", "current time"}:
        return datetime.now().strftime("The time is %I:%M %p.")

    return (
        "I do not have a desktop command for that yet. "
        "I can open and close apps, create folders and files, search the web, "
        "and prepare Slack messages."
    )


# Compatibility with older router code
execute: Callable[[str], str] = execute_command