"""Where each capability sits in its life, and how critical it is (pack5 #135-138).

A capability is not simply on or off. It moves DISCOVERED -> TRIAL -> CANARY ->
PRODUCTION, can slip to DEGRADED and recover, and is eventually DEPRECATED ->
RETIRED. Its criticality (CORE/IMPORTANT/OPTIONAL/EXPERIMENTAL) decides how much
the rest of the system should care when it wobbles. This is a small validated
state machine so a capability can't teleport from DISCOVERED to PRODUCTION
without passing the gate.
"""

from __future__ import annotations

import threading
from typing import Any

# Lifecycle states (pack5 #135).
DISCOVERED = "DISCOVERED"
TRIAL = "TRIAL"
CANARY = "CANARY"
PRODUCTION = "PRODUCTION"
DEGRADED = "DEGRADED"
DEPRECATED = "DEPRECATED"
RETIRED = "RETIRED"

# Criticality (pack5 #138).
CORE = "CORE"
IMPORTANT = "IMPORTANT"
OPTIONAL = "OPTIONAL"
EXPERIMENTAL = "EXPERIMENTAL"
_CRITICALITY = {CORE, IMPORTANT, OPTIONAL, EXPERIMENTAL}

# Allowed transitions. RETIRED is terminal; anything may be RETIRED (a kill).
_TRANSITIONS = {
    DISCOVERED: {TRIAL, RETIRED},
    TRIAL: {CANARY, DISCOVERED, RETIRED},
    CANARY: {PRODUCTION, TRIAL, RETIRED},
    PRODUCTION: {DEGRADED, DEPRECATED, RETIRED},
    DEGRADED: {PRODUCTION, DEPRECATED, RETIRED},
    DEPRECATED: {RETIRED, PRODUCTION},
    RETIRED: set(),
}


class CapabilityLifecycle:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state: dict[str, str] = {}
        self._criticality: dict[str, str] = {}

    def register(self, name: str, *, criticality: str = OPTIONAL,
                 state: str = DISCOVERED) -> None:
        key = _norm(name)
        if not key:
            return
        crit = criticality if criticality in _CRITICALITY else OPTIONAL
        st = state if state in _TRANSITIONS else DISCOVERED
        with self._lock:
            self._state.setdefault(key, st)
            self._criticality[key] = crit

    def can_transition(self, name: str, new_state: str) -> bool:
        with self._lock:
            current = self._state.get(_norm(name), DISCOVERED)
        return new_state in _TRANSITIONS.get(current, set())

    def transition(self, name: str, new_state: str) -> tuple[bool, str]:
        """Move a capability. Returns (ok, reason). Invalid jumps are refused."""
        key = _norm(name)
        if new_state not in _TRANSITIONS:
            return False, f"unknown state {new_state!r}"
        with self._lock:
            current = self._state.get(key, DISCOVERED)
            if new_state == current:
                return True, "already there"
            if new_state not in _TRANSITIONS.get(current, set()):
                return False, f"{current} -> {new_state} is not allowed"
            self._state[key] = new_state
            return True, f"{current} -> {new_state}"

    def state(self, name: str) -> str:
        with self._lock:
            return self._state.get(_norm(name), DISCOVERED)

    def criticality(self, name: str) -> str:
        with self._lock:
            return self._criticality.get(_norm(name), OPTIONAL)

    def is_production(self, name: str) -> bool:
        return self.state(name) == PRODUCTION

    def mark_degraded(self, name: str) -> None:
        self.transition(name, DEGRADED)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [{"name": n, "state": self._state[n],
                     "criticality": self._criticality.get(n, OPTIONAL)}
                    for n in sorted(self._state)]


def _norm(name: str) -> str:
    return str(name or "").strip()


_instance: CapabilityLifecycle | None = None
_instance_lock = threading.Lock()


def get_lifecycle() -> CapabilityLifecycle:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = CapabilityLifecycle()
        return _instance
