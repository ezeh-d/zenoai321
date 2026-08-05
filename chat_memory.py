# chat_memory.py

import json
from datetime import datetime

from config import CHAT_HISTORY_FILE, MAX_CHAT_HISTORY_MESSAGES


def load_chat():
    """
    Load conversation history.
    """

    try:
        if not CHAT_HISTORY_FILE.exists():
            return []

        with open(CHAT_HISTORY_FILE, "r", encoding="utf-8") as file:
            return json.load(file)

    except (json.JSONDecodeError, OSError):
        return []


def save_chat(chat):
    """
    Save conversation history.
    """

    try:
        with open(CHAT_HISTORY_FILE, "w", encoding="utf-8") as file:
            json.dump(chat, file, indent=4, ensure_ascii=False)

    except OSError as error:
        print(f"[Chat Memory] Save Error: {error}")


def add_message(role, content):
    """
    Add a new message to chat history.
    """

    chat = load_chat()

    chat.append(
        {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
    )

    # Keep only the most recent messages
    if len(chat) > MAX_CHAT_HISTORY_MESSAGES:
        chat = chat[-MAX_CHAT_HISTORY_MESSAGES:]

    save_chat(chat)


def clear_chat():
    """
    Delete all conversation history.
    """

    save_chat([])


def get_recent_messages(limit=10):
    """
    Return the most recent chat messages.
    """

    chat = load_chat()
    return chat[-limit:]