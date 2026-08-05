
from __future__ import annotations

BLOCKED = ("bypass security", "disable antivirus", "steal password", "send money without confirmation", "format drive")
CONFIRM = ("delete ", "send email", "send message", "purchase ", "pay ", "submit form")

def assess(text: str) -> tuple[str, str]:
    lower = text.lower()
    if any(x in lower for x in BLOCKED):
        return "blocked", "That action is blocked for safety."
    if any(x in lower for x in CONFIRM):
        return "confirm", "That action needs your confirmation before execution."
    return "allow", ""
