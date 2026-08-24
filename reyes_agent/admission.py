"""Resource admission control -- say no before the laptop falls over (pack5 #18-24).

Heavy work (a local model, a vision job, a browser session, the GPU) has a
finite budget. This gates how many run at once per resource class: when the
budget is full the next request is REJECTED (backpressure #18) rather than
queued forever or allowed to thrash the machine. Voice-critical classes are
reserved and always admitted, so STOP/VAD/turn-detection stay responsive even
under load (#20, #118). Non-blocking, thread-safe, never raises.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

# Default per-class concurrency budgets. Tune per machine via `configure`.
_DEFAULT_BUDGETS = {
    "heavy_model": 2,
    "vision": 1,
    "gpu": 1,
    "browser": 3,
    "background": 4,
    "indexing": 2,
}

# Always admitted, never counted -- interactivity must not be starved (#118).
_RESERVED = {"voice", "stop", "vad", "turn_detection", "interactive"}


@dataclass(frozen=True)
class Ticket:
    resource_class: str
    reserved: bool


class Rejected(RuntimeError):
    def __init__(self, resource_class: str, limit: int) -> None:
        super().__init__(f"'{resource_class}' is at capacity ({limit}); try again shortly.")
        self.resource_class = resource_class
        self.limit = limit


class AdmissionController:
    def __init__(self, budgets: dict[str, int] | None = None) -> None:
        self._lock = threading.RLock()
        self._budgets = dict(_DEFAULT_BUDGETS)
        if budgets:
            for name, limit in budgets.items():
                self._budgets[str(name)] = max(0, int(limit))
        self._active: dict[str, int] = {}

    def configure(self, resource_class: str, limit: int) -> None:
        with self._lock:
            self._budgets[str(resource_class)] = max(0, int(limit))

    def limit(self, resource_class: str) -> int:
        return self._budgets.get(str(resource_class), _DEFAULT_BUDGETS.get(str(resource_class), 1))

    def in_use(self, resource_class: str) -> int:
        with self._lock:
            return self._active.get(str(resource_class), 0)

    def try_admit(self, resource_class: str) -> Ticket | None:
        """Admit one unit of work, or None if the class is full (backpressure)."""
        cls = str(resource_class or "").strip()
        if not cls:
            return Ticket("", reserved=True)
        if cls in _RESERVED:
            return Ticket(cls, reserved=True)      # never gated
        with self._lock:
            used = self._active.get(cls, 0)
            if used >= self.limit(cls):
                return None
            self._active[cls] = used + 1
            return Ticket(cls, reserved=False)

    def release(self, ticket: Ticket | None) -> None:
        if ticket is None or ticket.reserved or not ticket.resource_class:
            return
        with self._lock:
            used = self._active.get(ticket.resource_class, 0)
            if used > 0:
                self._active[ticket.resource_class] = used - 1

    @contextmanager
    def admit(self, resource_class: str) -> Iterator[Ticket]:
        """`with admission.admit("vision"): ...` -- raises Rejected if full."""
        ticket = self.try_admit(resource_class)
        if ticket is None:
            raise Rejected(str(resource_class), self.limit(resource_class))
        try:
            yield ticket
        finally:
            self.release(ticket)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            classes = sorted(set(self._budgets) | set(self._active))
            return [{"resource_class": c, "in_use": self._active.get(c, 0),
                     "limit": self.limit(c),
                     "reserved": c in _RESERVED} for c in classes]


_instance: AdmissionController | None = None
_instance_lock = threading.Lock()


def get_admission() -> AdmissionController:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = AdmissionController()
        return _instance
