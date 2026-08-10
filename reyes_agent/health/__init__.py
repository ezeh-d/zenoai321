"""ZENO watching its own workers.

`processes` measures ZENO's own process tree with psutil. `watchdog`
decides what to do about a failure -- and, crucially, when to stop trying:
after repeated failed restarts the breaker opens, the subsystem is marked
DEGRADED and the owner is told, rather than a restart loop hiding the fault.

This complements `system_health.py`, which reports what each subsystem says
about itself. This one acts on it.
"""

from __future__ import annotations

from reyes_agent.health import processes            # no intra-package deps
from reyes_agent.health import watchdog             # independent

__all__ = ["processes", "watchdog", "register", "heal", "inspect", "status"]

register = watchdog.register
heal = watchdog.heal
inspect = watchdog.inspect


def status() -> dict:
    """Both halves: what is running, and what ZENO is doing about it."""
    return {"state": "ONLINE",
            "processes": processes.status(),
            "watchdog": watchdog.status()}
