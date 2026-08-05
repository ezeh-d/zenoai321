"""Bound active conversation memory and archive inactive turns to disk."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from reyes_agent import config


MAX_ACTIVE_HISTORY = max(20, int(os.environ.get("ZENO_ACTIVE_HISTORY", "120")))
_ARCHIVE_PATH = config.VAULT_PATH / "07-System" / "session" / "conversation_archive.jsonl"
_archive_lock = threading.Lock()


def trim_history(history: list[dict[str, Any]], max_messages: int = MAX_ACTIVE_HISTORY) -> int:
    """Archive and remove old turns, preserving a user-message boundary.

    The provider already windows outbound history, but retaining every old
    message in the process made long-running sessions grow without bound.
    This is called only from background conversation work while the caller's
    history lock is held.
    """
    limit = max(20, int(max_messages))
    if len(history) <= limit:
        return 0

    cut = len(history) - limit
    # Begin the retained list with a user turn where possible, rather than a
    # dangling tool result from the previous turn.
    for index in range(cut, len(history)):
        if history[index].get("role") == "user":
            cut = index
            break
    archived = history[:cut]
    if not archived:
        return 0

    record = {"archived_at": time.time(), "messages": archived}
    try:
        _ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _archive_lock, _ARCHIVE_PATH.open("a", encoding="utf-8") as archive:
            archive.write(json.dumps(record, default=str) + "\n")
    except OSError:
        # Memory safety still wins if the archive location is temporarily
        # unavailable. Session recovery retains its independent recent tail.
        pass
    del history[:cut]
    return len(archived)


def snapshot() -> dict[str, Any]:
    try:
        size = _ARCHIVE_PATH.stat().st_size
    except OSError:
        size = 0
    return {"active_history_limit": MAX_ACTIVE_HISTORY, "archive_bytes": size}
