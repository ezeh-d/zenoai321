from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from config import MEMORY_FILE, NOTES_FILE


def load_memory() -> dict[str, Any]:
    """Load long-term personal memory from disk."""
    try:
        if not MEMORY_FILE.exists():
            return {}

        with MEMORY_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        return data if isinstance(data, dict) else {}

    except (json.JSONDecodeError, OSError) as error:
        print(f"[Memory] Load error: {error}")
        return {}


def save_memory(memory: dict[str, Any]) -> bool:
    """Save the complete long-term memory dictionary."""
    try:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)

        with MEMORY_FILE.open("w", encoding="utf-8") as file:
            json.dump(
                memory,
                file,
                indent=4,
                ensure_ascii=False,
            )

        return True

    except OSError as error:
        print(f"[Memory] Save error: {error}")
        return False


def normalize_key(key: str) -> str:
    """Normalize memory keys for consistent save and recall."""
    return " ".join(key.strip().lower().split())


def remember(key: str, value: Any) -> bool:
    """Save or update one personal memory entry."""
    normalized_key = normalize_key(key)

    if not normalized_key:
        return False

    memory = load_memory()

    memory[normalized_key] = {
        "value": value,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }

    return save_memory(memory)


def recall(key: str) -> Any | None:
    """Recall one saved memory value."""
    normalized_key = normalize_key(key)

    if not normalized_key:
        return None

    item = load_memory().get(normalized_key)

    if item is None:
        return None

    if isinstance(item, dict) and "value" in item:
        return item["value"]

    return item


def forget(key: str) -> bool:
    """Delete one saved memory entry."""
    normalized_key = normalize_key(key)

    if not normalized_key:
        return False

    memory = load_memory()

    if normalized_key not in memory:
        return False

    del memory[normalized_key]

    return save_memory(memory)


def list_memory() -> dict[str, Any]:
    """Return all saved memories as simple key-value pairs."""
    result: dict[str, Any] = {}

    for key, item in load_memory().items():
        if isinstance(item, dict) and "value" in item:
            result[key] = item["value"]
        else:
            result[key] = item

    return result


def search_memory(query: str) -> dict[str, Any]:
    """Search saved memory keys and values."""
    search_text = query.strip().lower()

    if not search_text:
        return {}

    matches: dict[str, Any] = {}

    for key, value in list_memory().items():
        if (
            search_text in key.lower()
            or search_text in str(value).lower()
        ):
            matches[key] = value

    return matches


def clear_memory() -> bool:
    """Delete all long-term personal memory entries."""
    return save_memory({})


def memory_exists(key: str) -> bool:
    """Return True when a memory key exists."""
    normalized_key = normalize_key(key)

    if not normalized_key:
        return False

    return normalized_key in load_memory()


def memory_count() -> int:
    """Return the number of saved personal memories."""
    return len(load_memory())


def save_note(note: str) -> bool:
    """Append a timestamped note to the notes file."""
    clean_note = note.strip()

    if not clean_note:
        return False

    try:
        NOTES_FILE.parent.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with NOTES_FILE.open("a", encoding="utf-8") as file:
            file.write(f"[{timestamp}] {clean_note}\n")

        return True

    except OSError as error:
        print(f"[Notes] Save error: {error}")
        return False


def load_notes() -> list[str]:
    """Load all saved notes."""
    try:
        if not NOTES_FILE.exists():
            return []

        with NOTES_FILE.open("r", encoding="utf-8") as file:
            return [
                line.rstrip("\n")
                for line in file
                if line.strip()
            ]

    except OSError as error:
        print(f"[Notes] Load error: {error}")
        return []


def clear_notes() -> bool:
    """Delete all saved notes."""
    try:
        NOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
        NOTES_FILE.write_text("", encoding="utf-8")
        return True

    except OSError as error:
        print(f"[Notes] Clear error: {error}")
        return False