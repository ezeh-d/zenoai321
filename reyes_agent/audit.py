"""Tier 6: a visible, plain-text audit trail.

Every tool that actually runs, and every confirmation decision, gets one
line here -- what ran, with what input, what it returned, and when.
Plain text on purpose (per AGENT.md's own Tier 6 spec: "a plain log"),
so it's readable without REYES itself, greppable, and honest about what
happened when something surprises you.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from typing import Any

from reyes_agent import config
from reyes_agent.memory.privacy import redact

_LOG_DIR = config.VAULT_PATH / "07-System" / (
    "test-logs" if config.ZENO_ENV == "test" else "logs"
)
_LOG_PATH = _LOG_DIR / "audit.log"

_MAX_FIELD_CHARS = 300  # keep the log skimmable -- long results get truncated, not omitted
_MAX_LOG_BYTES = 5 * 1024 * 1024
_BACKUPS = 3
_lock = threading.RLock()
_SENSITIVE_KEYS = ("password", "passwd", "secret", "token", "api_key", "apikey",
                   "cookie", "credential", "private_key", "authorization")


def _sanitize(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if any(marker in key.casefold() for marker in _SENSITIVE_KEYS):
        return "[REDACTED]"
    if depth > 4:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {
            str(item_key)[:80]: _sanitize(item, key=str(item_key), depth=depth + 1)
            for item_key, item in list(value.items())[:80]
        }
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(item, depth=depth + 1) for item in list(value)[:80]]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    text = redact(str(value), limit=_MAX_FIELD_CHARS + 64)
    return text if len(text) <= _MAX_FIELD_CHARS else text[:_MAX_FIELD_CHARS] + "...[truncated]"


def _rotate_if_needed() -> None:
    try:
        if not _LOG_PATH.exists() or _LOG_PATH.stat().st_size < _MAX_LOG_BYTES:
            return
        oldest = _LOG_PATH.with_name(f"{_LOG_PATH.name}.{_BACKUPS}")
        oldest.unlink(missing_ok=True)
        for number in range(_BACKUPS - 1, 0, -1):
            source = _LOG_PATH.with_name(f"{_LOG_PATH.name}.{number}")
            if source.exists():
                source.replace(_LOG_PATH.with_name(f"{_LOG_PATH.name}.{number + 1}"))
        _LOG_PATH.replace(_LOG_PATH.with_name(f"{_LOG_PATH.name}.1"))
    except OSError:
        # Failing to rotate must not erase or interrupt the active audit log.
        pass


def log(event: str, **fields) -> None:
    try:
        with _lock:
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            _rotate_if_needed()
            now = time.time()
            entry = {
                "ts": datetime.fromtimestamp(now, UTC).isoformat(),
                "ts_epoch": now,
                "event": _sanitize(event),
            }
            entry.update({str(k)[:80]: _sanitize(v, key=str(k)) for k, v in fields.items()})
            with open(_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass  # the audit trail must never be why a turn fails
