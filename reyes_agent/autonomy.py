"""Explicit autonomy levels mapped onto the existing permission authority."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from reyes_agent import permissions


class AutonomyLevel(IntEnum):
    TALK_ONLY = 0
    SAFE_AUTOMATION = 1
    STANDARD_ACTION = 2
    SENSITIVE = 3
    BLOCKED = 4


@dataclass(frozen=True)
class AutonomyDecision:
    level: AutonomyLevel
    allowed: bool
    requires_confirmation: bool
    reason: str

    def as_dict(self) -> dict:
        return {"level": int(self.level), "name": self.level.name,
                "allowed": self.allowed, "requires_confirmation": self.requires_confirmation,
                "reason": self.reason}


_READ_ONLY_PREFIXES = ("list_", "get_", "search_", "read_", "current_", "check_", "mcp_status")
_READ_ONLY_EXACT = {"system_health", "permission_status", "capability_status", "take_screenshot",
                    "browser_read", "browser_extract", "browser_screenshot", "coding_inspect", "mcp_read"}


def classify_tool(tool_name: str, *, requires_confirmation: bool = False) -> AutonomyDecision:
    name = str(tool_name or "")
    capability = permissions.capability_for_tool(name)
    state = permissions.state_for(capability) if capability else permissions.ENABLED
    if capability == "financial" or state == permissions.BLOCKED:
        return AutonomyDecision(AutonomyLevel.BLOCKED, False, False,
                                f"capability '{capability or name}' is structurally blocked")
    if requires_confirmation or state == permissions.CONFIRM:
        return AutonomyDecision(AutonomyLevel.SENSITIVE, True, True,
                                "the existing permission policy requires owner confirmation")
    if name in _READ_ONLY_EXACT or name.startswith(_READ_ONLY_PREFIXES):
        return AutonomyDecision(AutonomyLevel.SAFE_AUTOMATION, True, False,
                                "read-only or reversible low-risk action")
    return AutonomyDecision(AutonomyLevel.STANDARD_ACTION, True, False,
                            "normal action allowed by the active installation profile")


def talk_only() -> AutonomyDecision:
    return AutonomyDecision(AutonomyLevel.TALK_ONLY, True, False, "no tool execution requested")
