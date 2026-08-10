"""One contextual constitution layered on the existing permission engine."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import Any

from reyes_agent import permissions

ALLOW, CONFIRM, DENY = "ALLOW", "CONFIRM", "DENY"
_CRITICAL_MARKERS = ("transfer", "payment", "purchase", "place_trade", "password", "credential", "disable_security", "unlock_door", "disarm_alarm")


@dataclass(frozen=True)
class Decision:
    effect: str
    risk: str
    capability: str
    reason: str
    source: str = "zeno"

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def decide(action: str, *, context: dict[str, Any] | None = None) -> Decision:
    name = (action or "").strip().casefold()
    capability = permissions.capability_for_tool(name) or "read_only"
    if capability == "financial" or any(marker in name for marker in _CRITICAL_MARKERS):
        return Decision(DENY, "CRITICAL", capability, "critical action is never automatic")
    state = permissions.check(name)
    if state == permissions.BLOCKED:
        return Decision(DENY, "BLOCKED", capability, "blocked by ZENO permission profile")
    if state == permissions.CONFIRM:
        return Decision(CONFIRM, "SENSITIVE", capability, "permission profile requires owner confirmation")
    if context and context.get("irreversible"):
        return Decision(CONFIRM, "SENSITIVE", capability, "caller marked action irreversible")
    return Decision(ALLOW, "READ_ONLY" if capability == "read_only" else "STANDARD", capability, "allowed by existing ZENO permission authority")


def status() -> dict[str, Any]:
    opa_enabled = os.environ.get("ZENO_OPA_ENABLED", "").casefold() in {"1", "true", "yes", "on"}
    return {"state": "ONLINE", "authority": "reyes_agent.permissions", "opa_enabled": opa_enabled,
            "opa_available": bool(shutil.which("opa")), "default_effect": "CONFIRM for undeclared consequential capabilities",
            "financial": "DENY", "polling": False}
