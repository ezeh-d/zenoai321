"""Watch ZENO's own workers, and know when to stop trying to fix them.

THE RULE THAT MATTERS
---------------------
"Never continuously restart a crashing process forever." A restart loop is
worse than the crash: it burns CPU, it fills the log with identical
failures, and it hides the fault behind a service that looks like it keeps
coming back. So every subsystem carries a circuit breaker.

    CLOSED     healthy, or recovering normally
    HALF_OPEN  one restart has been spent; watching whether it held
    OPEN       gave up. The subsystem is DEGRADED, the owner is told, and
               nothing restarts it again until they say so.

RECOVERY IS NOT THE SAME AS RESTARTING
--------------------------------------
    DETECT -> DIAGNOSE -> SAFE RESTART -> VERIFY -> recovered, or OPEN

The VERIFY step is what makes it honest. A restart that returns without
error is not a recovery; the subsystem has to report healthy afterwards. A
watchdog that counts attempts instead of outcomes will happily report a
dead service as recovered forever.

WHAT IT WATCHES
---------------
Subsystems register a `check` (is this healthy?) and optionally a `restart`.
A subsystem with no restart can still be monitored -- it simply goes
straight to DEGRADED, which is the truthful outcome for something nobody
knows how to revive.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

CLOSED = "CLOSED"
HALF_OPEN = "HALF_OPEN"
OPEN = "OPEN"

HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
FAILED = "FAILED"
UNKNOWN = "UNKNOWN"

# Restarts allowed before the breaker opens. Two: one for a transient
# failure, one for the retry that proves it was not transient.
MAX_RESTARTS = 2

# Restart successes older than this stop counting against the breaker, so a
# service that failed once a week ago is not treated as chronically broken.
BREAKER_RESET_S = 1800.0

# Do not hammer: minimum gap between restart attempts for one subsystem.
MIN_RESTART_GAP_S = 20.0

_lock = threading.RLock()
_registry: dict[str, "Subsystem"] = {}


@dataclass
class Subsystem:
    name: str
    check: Callable[[], bool]
    restart: Callable[[], bool] | None = None
    critical: bool = False

    breaker: str = CLOSED
    status: str = UNKNOWN
    restarts: int = 0
    last_restart_at: float = 0.0
    last_ok_at: float = 0.0
    last_error: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def recoverable(self) -> bool:
        return self.restart is not None and self.breaker != OPEN

    def note(self, event: str, detail: str = "") -> None:
        self.events.append({"at": time.time(), "event": event, "detail": detail[:300]})
        del self.events[:-20]          # bounded: a watchdog must not leak memory

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "breaker": self.breaker,
                "restarts": self.restarts, "critical": self.critical,
                "recoverable": self.recoverable, "last_error": self.last_error[:200],
                "last_ok_at": self.last_ok_at, "events": self.events[-5:]}


def register(name: str, check: Callable[[], bool], *,
             restart: Callable[[], bool] | None = None,
             critical: bool = False) -> Subsystem:
    with _lock:
        subsystem = Subsystem(name=name, check=check, restart=restart, critical=critical)
        _registry[name] = subsystem
        return subsystem


def unregister(name: str) -> None:
    with _lock:
        _registry.pop(name, None)


def _is_healthy(subsystem: Subsystem) -> tuple[bool, str]:
    """A check that raises is a failure, not a crash of the watchdog."""
    try:
        return bool(subsystem.check()), ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def _decay(subsystem: Subsystem) -> None:
    """Forgive old failures so a long-stable service is not stuck HALF_OPEN."""
    if (subsystem.restarts and subsystem.last_restart_at
            and (time.time() - subsystem.last_restart_at) > BREAKER_RESET_S
            and subsystem.status == HEALTHY):
        subsystem.restarts = 0
        subsystem.breaker = CLOSED
        subsystem.note("breaker_reset", "stable long enough to forget old failures")


def inspect(name: str = "") -> list[Subsystem]:
    with _lock:
        targets = [_registry[name]] if name and name in _registry else list(_registry.values())
    for subsystem in targets:
        healthy, error = _is_healthy(subsystem)
        if healthy:
            subsystem.status = HEALTHY
            subsystem.last_ok_at = time.time()
            _decay(subsystem)
        else:
            # DEGRADED means "ZENO gave up on this", which says strictly more
            # than FAILED. A routine health read must not quietly downgrade
            # that verdict back to an ordinary failure -- the breaker being
            # open is the thing the owner needs to keep seeing.
            subsystem.status = DEGRADED if subsystem.breaker == OPEN else FAILED
            subsystem.last_error = error or "check returned false"
    return targets


def heal(name: str = "") -> list[dict[str, Any]]:
    """One bounded pass: detect, diagnose, restart at most once, verify."""
    outcomes = []
    for subsystem in inspect(name):
        if subsystem.status == HEALTHY:
            continue

        subsystem.note("detected", subsystem.last_error)

        if subsystem.restart is None:
            subsystem.status = DEGRADED
            subsystem.note("no_recovery", "nothing knows how to restart this")
            outcomes.append({"name": subsystem.name, "action": "none",
                             "result": DEGRADED,
                             "detail": "no restart is defined for this subsystem"})
            continue

        if subsystem.breaker == OPEN:
            subsystem.status = DEGRADED
            outcomes.append({"name": subsystem.name, "action": "refused",
                             "result": DEGRADED,
                             "detail": ("the breaker is open -- I stopped restarting this "
                                        "after repeated failures and will not try again "
                                        "until you ask")})
            continue

        if (time.time() - subsystem.last_restart_at) < MIN_RESTART_GAP_S:
            outcomes.append({"name": subsystem.name, "action": "deferred",
                             "result": subsystem.status,
                             "detail": "restarted very recently; waiting before trying again"})
            continue

        if subsystem.restarts >= MAX_RESTARTS:
            subsystem.breaker = OPEN
            subsystem.status = DEGRADED
            subsystem.note("breaker_open", f"{subsystem.restarts} restarts did not hold")
            outcomes.append({"name": subsystem.name, "action": "gave_up", "result": DEGRADED,
                             "detail": (f"{subsystem.name} failed again after "
                                        f"{subsystem.restarts} restarts, so I have stopped "
                                        "restarting it rather than loop.")})
            continue

        # DETECT -> DIAGNOSE -> RESTART
        subsystem.restarts += 1
        subsystem.last_restart_at = time.time()
        subsystem.breaker = HALF_OPEN
        try:
            subsystem.restart()
            restarted, why = True, ""
        except Exception as exc:  # noqa: BLE001
            restarted, why = False, f"{type(exc).__name__}: {exc}"

        # VERIFY -- the step that stops "restarted" being mistaken for "fixed".
        healthy, error = _is_healthy(subsystem) if restarted else (False, why)
        if healthy:
            subsystem.status = HEALTHY
            subsystem.last_ok_at = time.time()
            subsystem.note("recovered", f"restart {subsystem.restarts} held")
            outcomes.append({"name": subsystem.name, "action": "restarted",
                             "result": HEALTHY,
                             "detail": f"{subsystem.name} is responding again"})
        else:
            subsystem.status = FAILED
            subsystem.last_error = error or why or "still failing after restart"
            subsystem.note("restart_failed", subsystem.last_error)
            if subsystem.restarts >= MAX_RESTARTS:
                subsystem.breaker = OPEN
                subsystem.status = DEGRADED
                subsystem.note("breaker_open", "restarts did not help")
            outcomes.append({"name": subsystem.name, "action": "restarted",
                             "result": subsystem.status, "detail": subsystem.last_error})
    return outcomes


def reset(name: str = "") -> None:
    """The owner clearing a tripped breaker. The only way back from OPEN."""
    with _lock:
        targets = [_registry[name]] if name and name in _registry else list(_registry.values())
    for subsystem in targets:
        subsystem.breaker = CLOSED
        subsystem.restarts = 0
        subsystem.status = UNKNOWN
        subsystem.note("reset", "breaker cleared by the owner")


def clear_registry() -> None:
    with _lock:
        _registry.clear()


def status() -> dict[str, Any]:
    subsystems = inspect()
    degraded = [s for s in subsystems if s.status in (DEGRADED, FAILED)]
    opened = [s for s in subsystems if s.breaker == OPEN]
    overall = HEALTHY
    if any(s.critical and s.status != HEALTHY for s in subsystems):
        overall = FAILED
    elif degraded:
        overall = DEGRADED
    return {
        "state": "ONLINE",
        "overall": overall,
        "watching": len(subsystems),
        "degraded": [s.name for s in degraded],
        "gave_up_on": [s.name for s in opened],
        "subsystems": [s.as_dict() for s in subsystems],
        "policy": {"max_restarts": MAX_RESTARTS, "breaker_reset_s": BREAKER_RESET_S,
                   "min_restart_gap_s": MIN_RESTART_GAP_S},
        "note": ("A restart only counts as a recovery if the subsystem reports healthy "
                 "afterwards. After repeated failures the breaker opens and ZENO stops "
                 "restarting rather than loop -- it says so instead."),
    }
