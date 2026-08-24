"""Per-tool circuit breakers -- fast protection with automatic recovery.

WHY (pack4 #82, #84, #125)
--------------------------
Reputation (``tool_reputation``) is a slow, fair rolling average -- good for
*ranking*. A breaker is the fast reflex: when a tool starts failing in a burst,
trip it OPEN so the executor/router stops calling it immediately, wait a
cooldown, then let a single probe through (HALF_OPEN). A probe success closes
it; a probe failure re-opens it. This is what stops a flapping provider from
burning every request while it's down, without permanently condemning it.

States: CLOSED (healthy) -> OPEN (quarantined, calls refused) -> HALF_OPEN
(cooldown elapsed, one probe allowed) -> CLOSED / OPEN.

Thread-safe, never raises, and time is injectable so it is tested without
sleeping.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

CLOSED = "CLOSED"
OPEN = "OPEN"
HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    def __init__(self, *, failure_threshold: int = 4, cooldown_s: float = 60.0,
                 clock: Callable[[], float] | None = None) -> None:
        self._threshold = max(1, int(failure_threshold))
        self._cooldown = max(0.0, float(cooldown_s))
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        # name -> {"fails": int, "opened_at": float, "probing": bool}
        self._state: dict[str, dict[str, Any]] = {}

    def _entry(self, name: str) -> dict[str, Any]:
        return self._state.setdefault(name, {"fails": 0, "opened_at": 0.0, "probing": False})

    def record(self, name: str, ok: bool) -> None:
        """Feed one outcome. Success closes the breaker; enough failures trip it."""
        try:
            key = str(name or "").strip()
            if not key:
                return
            with self._lock:
                entry = self._entry(key)
                if ok:
                    entry["fails"] = 0
                    entry["opened_at"] = 0.0
                    entry["probing"] = False
                else:
                    entry["probing"] = False
                    entry["fails"] += 1
                    if entry["fails"] >= self._threshold:
                        entry["opened_at"] = self._clock()
        except Exception:  # noqa: BLE001 -- protection must never break a caller
            pass

    def allow(self, name: str) -> bool:
        """True if a call to ``name`` should be attempted now. OPEN refuses until
        the cooldown elapses, then lets exactly one probe through."""
        try:
            key = str(name or "").strip()
            if not key:
                return True
            with self._lock:
                entry = self._state.get(key)
                if not entry or not entry["opened_at"]:
                    return True                                  # CLOSED
                if self._clock() - entry["opened_at"] >= self._cooldown:
                    if not entry["probing"]:
                        entry["probing"] = True                  # HALF_OPEN: one probe
                        return True
                    return False                                 # probe already in flight
                return False                                     # OPEN, cooling down
        except Exception:  # noqa: BLE001
            return True

    def is_open(self, name: str) -> bool:
        """True when calls are currently refused (OPEN and still cooling down)."""
        return self.state(name) == OPEN

    def state(self, name: str) -> str:
        with self._lock:
            entry = self._state.get(str(name or "").strip())
            if not entry or not entry["opened_at"]:
                return CLOSED
            if self._clock() - entry["opened_at"] >= self._cooldown:
                return HALF_OPEN
            return OPEN

    def reset(self, name: str | None = None) -> None:
        with self._lock:
            if name is None:
                self._state.clear()
            else:
                self._state.pop(str(name or "").strip(), None)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            names = list(self._state)
        return [{"name": n, "state": self.state(n)} for n in names]


_instance: CircuitBreaker | None = None
_instance_lock = threading.Lock()


def get_breaker() -> CircuitBreaker:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = CircuitBreaker()
        return _instance


def record(name: str, ok: bool) -> None:
    get_breaker().record(name, ok)


def allow(name: str) -> bool:
    return get_breaker().allow(name)


def is_open(name: str) -> bool:
    return get_breaker().is_open(name)
