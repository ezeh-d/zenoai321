"""The FAST path: known commands that need no perception.

"Open Chrome" does not require looking at the screen -- ZENO already has
`open_app`, `open_path`, `set_volume` and friends, and they are faster and
more reliable than any agentic loop. This module routes to those EXISTING
tools rather than reimplementing them.

A request matching nothing here escalates to the agentic path. That is the
whole division of labour, and it is why perception stays cheap: it is only
paid for when it is genuinely needed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# request pattern -> (tool name, argument name)
_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"^(?:please\s+)?(?:open|launch|start|run)\s+(?:the\s+)?(?:app\s+)?"
                r"(?P<arg>[\w .+-]{2,60})$", re.I), "open_app", "name_or_path"),
    (re.compile(r"^(?:open|show)\s+(?:the\s+)?(?:folder|file|path)\s+(?P<arg>.+)$", re.I),
     "open_path", "path"),
    (re.compile(r"^(?:set|change|turn)\s+(?:the\s+)?volume\s+(?:to\s+)?(?P<arg>\d{1,3})%?$", re.I),
     "set_volume", "level"),
    (re.compile(r"^(?:take\s+a\s+)?screenshot$", re.I), "take_screenshot", ""),
    (re.compile(r"^lock\s+(?:the\s+)?(?:screen|computer|pc)$", re.I), "lock_screen", ""),
    (re.compile(r"^(?P<arg>play|pause|next track|previous track|mute)$", re.I),
     "media_control", "action"),
]


@dataclass
class FastResult:
    handled: bool
    ok: bool = False
    tool: str = ""
    result: str = ""
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"handled": self.handled, "ok": self.ok, "tool": self.tool,
                "result": self.result[:400], "reason": self.reason}


def match(request: str) -> tuple[str, dict] | None:
    """Which deterministic tool serves this request, if any."""
    text = " ".join(str(request or "").strip().split()).rstrip(".!")
    for pattern, tool, argument in _PATTERNS:
        found = pattern.match(text)
        if not found:
            continue
        if not argument:
            return tool, {}
        value = (found.groupdict().get("arg") or "").strip()
        if tool == "set_volume":
            try:
                return tool, {argument: int(value)}
            except ValueError:
                return None
        return tool, {argument: value}
    return None


def run(request: str) -> FastResult:
    """Execute via the EXISTING gated tool path -- never a private shortcut.

    Going through `run_tool` means the permission engine, the confirmation
    gate and the audit trail all still apply exactly as they do for a typed
    request.
    """
    found = match(request)
    if found is None:
        return FastResult(False, reason="no deterministic command matches this request")
    tool, arguments = found
    try:
        from reyes_agent.tools import TOOLS, run_tool
    except Exception as exc:  # noqa: BLE001
        return FastResult(False, reason=f"tool registry unavailable: {exc}")
    if tool not in TOOLS:
        return FastResult(False, tool=tool, reason=f"'{tool}' is not registered")
    try:
        result = run_tool(tool, arguments)
    except Exception as exc:  # noqa: BLE001 -- a tool failure is a result, not a crash
        return FastResult(True, False, tool=tool, reason=f"{type(exc).__name__}: {exc}")
    text = str(result)
    folded = text.casefold().lstrip()
    ok = not (folded.startswith(("error", "blocked", "queued"))
              or "has not run" in folded or "nothing ran" in folded)
    return FastResult(True, ok, tool=tool, result=text,
                      reason="" if ok else "the gated tool did not execute")
