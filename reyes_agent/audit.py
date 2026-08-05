"""Tier 6: a visible, plain-text audit trail.

Every tool that actually runs, and every confirmation decision, gets one
line here -- what ran, with what input, what it returned, and when.
Plain text on purpose (per AGENT.md's own Tier 6 spec: "a plain log"),
so it's readable without REYES itself, greppable, and honest about what
happened when something surprises you.
"""

from __future__ import annotations

import json
import time

from reyes_agent import config

_LOG_DIR = config.VAULT_PATH / "07-System" / "logs"
_LOG_PATH = _LOG_DIR / "audit.log"

_MAX_FIELD_CHARS = 300  # keep the log skimmable -- long results get truncated, not omitted


def _clip(value) -> str:
    text = str(value)
    return text if len(text) <= _MAX_FIELD_CHARS else text[:_MAX_FIELD_CHARS] + "...[truncated]"


def log(event: str, **fields) -> None:
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        entry = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event}
        entry.update({k: _clip(v) for k, v in fields.items()})
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # the audit trail must never be why a turn fails
