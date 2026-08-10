"""Deterministic wake/conversation state transitions."""

from __future__ import annotations

import threading
import time
from enum import Enum


class WakeState(str, Enum):
    SLEEPING = "SLEEPING"
    LISTENING_FOR_WAKE = "LISTENING_FOR_WAKE"
    ACTIVE = "ACTIVE"
    SPEAKING = "SPEAKING"
    PROCESSING = "PROCESSING"
    STANDBY = "STANDBY"


_ALLOWED = {
    WakeState.SLEEPING: {WakeState.LISTENING_FOR_WAKE, WakeState.STANDBY},
    WakeState.LISTENING_FOR_WAKE: {WakeState.ACTIVE, WakeState.SLEEPING, WakeState.STANDBY},
    WakeState.ACTIVE: {WakeState.PROCESSING, WakeState.SPEAKING, WakeState.LISTENING_FOR_WAKE, WakeState.STANDBY},
    WakeState.PROCESSING: {WakeState.SPEAKING, WakeState.ACTIVE, WakeState.LISTENING_FOR_WAKE, WakeState.STANDBY},
    WakeState.SPEAKING: {WakeState.ACTIVE, WakeState.LISTENING_FOR_WAKE, WakeState.STANDBY},
    WakeState.STANDBY: {WakeState.LISTENING_FOR_WAKE, WakeState.SLEEPING},
}


class WakeStateMachine:
    def __init__(self) -> None:
        self._state = WakeState.SLEEPING
        self._lock = threading.RLock()
        self._changed_at = time.time()

    @property
    def state(self) -> WakeState:
        with self._lock:
            return self._state

    def transition(self, target: WakeState | str, *, reason: str = "") -> WakeState:
        wanted = target if isinstance(target, WakeState) else WakeState(str(target))
        with self._lock:
            if wanted == self._state:
                return self._state
            if wanted not in _ALLOWED[self._state]:
                raise ValueError(f"Invalid wake transition {self._state.value} -> {wanted.value}")
            previous = self._state
            self._state = wanted
            self._changed_at = time.time()
        try:
            from reyes_agent import event_bus

            event_bus.publish("wake.state", {"from": previous.value, "to": wanted.value,
                                             "reason": str(reason)[:160]}, source="wake")
        except Exception:
            pass
        return wanted

    def snapshot(self) -> dict:
        with self._lock:
            return {"state": self._state.value, "changed_at": self._changed_at}
