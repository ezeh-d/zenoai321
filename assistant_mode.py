# assistant_mode.py

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from config import DATA_DIR


MODE_FILE = Path(DATA_DIR) / "assistant_mode.json"

VALID_MODES = {
    "normal",
    "serious",
}

DEFAULT_MODE = "normal"

_mode_lock = Lock()


def _load_saved_mode() -> str:
    """
    Load the last selected mode from disk.
    """

    try:
        if not MODE_FILE.exists():
            return DEFAULT_MODE

        with MODE_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        mode = str(data.get("mode", DEFAULT_MODE)).lower()

        if mode in VALID_MODES:
            return mode

    except (OSError, json.JSONDecodeError, TypeError):
        pass

    return DEFAULT_MODE


_current_mode = _load_saved_mode()


def _save_mode(mode: str) -> bool:
    """
    Save the selected mode so REYES remembers it after restart.
    """

    try:
        MODE_FILE.parent.mkdir(parents=True, exist_ok=True)

        with MODE_FILE.open("w", encoding="utf-8") as file:
            json.dump(
                {"mode": mode},
                file,
                indent=4,
            )

        return True

    except OSError as error:
        print(f"[Mode Save Error] {error}")
        return False


def get_mode() -> str:
    """
    Return the current REYES response mode.
    """

    with _mode_lock:
        return _current_mode


def set_mode(mode: str) -> bool:
    """
    Change the REYES response mode.
    """

    global _current_mode

    clean_mode = mode.lower().strip()

    if clean_mode not in VALID_MODES:
        return False

    with _mode_lock:
        _current_mode = clean_mode
        _save_mode(clean_mode)

    return True


def enable_serious_mode() -> str:
    """
    Enable serious mode.
    """

    set_mode("serious")

    return (
        "Serious mode activated. "
        "Responses will now be direct, concise, and professional."
    )


def enable_normal_mode() -> str:
    """
    Return REYES to normal conversational mode.
    """

    set_mode("normal")

    return "Normal mode activated."


def is_serious_mode() -> bool:
    """
    Return True when serious mode is active.
    """

    return get_mode() == "serious"


def get_mode_description() -> str:
    """
    Return a user-readable description of the active mode.
    """

    if is_serious_mode():
        return (
            "Serious mode is active. "
            "I will respond directly and professionally."
        )

    return (
        "Normal mode is active. "
        "I will respond naturally and conversationally."
    )


def get_mode_prompt() -> str:
    """
    Return additional instructions for the AI model.
    """

    if is_serious_mode():
        return """
SERIOUS MODE IS ACTIVE.

Response rules:
- Be direct, professional, and concise.
- Do not make jokes.
- Do not use emojis.
- Do not use exaggerated enthusiasm.
- Do not add motivational filler.
- Do not repeat the user's request unnecessarily.
- Give the answer or action result immediately.
- Use short explanations unless detail is necessary.
- Clearly report errors, risks, and limitations.
""".strip()

    return """
NORMAL MODE IS ACTIVE.

Response rules:
- Be helpful, natural, and conversational.
- Keep responses clear and practical.
- Friendly wording is allowed.
- Avoid unnecessary verbosity.
""".strip()