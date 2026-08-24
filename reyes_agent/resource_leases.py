"""Exclusive, self-expiring leases on shared resources.

WHY (pack4 #110-#113, #28)
--------------------------
When more than one agent or worker can act at once, two of them must never drive
the same browser tab, edit the same file, or fight over the same desktop window.
A lease makes a resource single-writer: one holder at a time, everyone else is
told it's busy (and by whom). Leases carry a TTL so a crashed holder can't lock a
resource forever -- an expired lease is free. Re-acquiring your own lease just
extends it.

Resource ids are arbitrary strings, namespaced by convention:
``browser:tab:<id>``, ``file:<path>``, ``window:<title>``, ``gpu:0``.

Thread-safe, injectable clock for deterministic tests, never raises into a
caller (acquire returns None on contention; it does not throw).
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator

DEFAULT_TTL_S = 120.0


@dataclass(frozen=True)
class Lease:
    resource: str
    holder: str
    acquired_at: float
    expires_at: float

    def as_dict(self) -> dict[str, Any]:
        return {"resource": self.resource, "holder": self.holder,
                "acquired_at": round(self.acquired_at, 3),
                "expires_at": round(self.expires_at, 3)}


class ResourceBusy(RuntimeError):
    def __init__(self, resource: str, holder: str | None) -> None:
        super().__init__(f"'{resource}' is held by {holder or 'another worker'}.")
        self.resource = resource
        self.holder = holder


class LeaseManager:
    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._leases: dict[str, Lease] = {}

    def _active(self, resource: str) -> Lease | None:
        lease = self._leases.get(resource)
        if lease is None:
            return None
        if lease.expires_at <= self._clock():
            del self._leases[resource]          # expired -> free
            return None
        return lease

    def acquire(self, resource: str, holder: str,
                ttl_s: float = DEFAULT_TTL_S) -> Lease | None:
        """Grant an exclusive lease, or None if someone else holds it. Re-acquiring
        your own lease extends it."""
        res = str(resource or "").strip()
        who = str(holder or "").strip()
        if not res or not who:
            return None
        now = self._clock()
        with self._lock:
            active = self._active(res)
            if active is not None and active.holder != who:
                return None                      # held by someone else
            lease = Lease(res, who, now, now + max(0.0, float(ttl_s)))
            self._leases[res] = lease
            return lease

    def release(self, resource: str, holder: str) -> bool:
        """Release a lease you hold. True if you held it. Idempotent."""
        res = str(resource or "").strip()
        who = str(holder or "").strip()
        with self._lock:
            lease = self._leases.get(res)
            if lease is not None and lease.holder == who:
                del self._leases[res]
                return True
            return False

    def holder_of(self, resource: str) -> str | None:
        with self._lock:
            active = self._active(str(resource or "").strip())
            return active.holder if active else None

    def is_free(self, resource: str) -> bool:
        with self._lock:
            return self._active(str(resource or "").strip()) is None

    def active_leases(self) -> list[dict[str, Any]]:
        with self._lock:
            # Materialise, dropping any that have expired.
            live = [self._active(r) for r in list(self._leases)]
            return [lease.as_dict() for lease in live if lease is not None]

    @contextmanager
    def hold(self, resource: str, holder: str,
             ttl_s: float = DEFAULT_TTL_S) -> Iterator[Lease]:
        """`with leases.hold("file:/x", "kate"): ...` -- raises ResourceBusy if
        another holder owns it, and always releases on exit."""
        lease = self.acquire(resource, holder, ttl_s)
        if lease is None:
            raise ResourceBusy(str(resource), self.holder_of(str(resource)))
        try:
            yield lease
        finally:
            self.release(resource, holder)


_instance: LeaseManager | None = None
_instance_lock = threading.Lock()


def get_leases() -> LeaseManager:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = LeaseManager()
        return _instance
