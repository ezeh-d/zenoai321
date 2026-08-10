"""Parse and redact Open Interpreter JSONL without retaining raw secrets."""

from __future__ import annotations

import json
from typing import Any

from reyes_agent.memory.privacy import redact


def parse_jsonl(output: str, *, limit: int = 60_000) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    final = ""
    for line in str(output or "").splitlines():
        clean = redact(line, limit=4000)
        try:
            item = json.loads(clean)
        except json.JSONDecodeError:
            if clean.strip():
                final = clean.strip()
            continue
        if not isinstance(item, dict):
            continue
        safe = {key: value for key, value in item.items() if key.casefold() not in {"environment", "env", "api_key", "token", "password"}}
        events.append(safe)
        candidate = safe.get("message") or safe.get("text") or safe.get("result")
        if isinstance(candidate, str):
            final = redact(candidate, limit=limit)
        if len(events) >= 300:
            break
    return {"events": events, "final": final[:limit], "event_count": len(events)}
