"""Agent health, read from the real supervisor.

`agent_runtime` already tracks liveness, failures, restarts and what each
worker is doing. This reports THAT rather than keeping a second, drifting
copy -- two health views that disagree are worse than one.
"""

from __future__ import annotations

from typing import Any

HEALTHY, DEGRADED, FAILED, STOPPED = "HEALTHY", "DEGRADED", "FAILED", "STOPPED"


def snapshot() -> dict[str, Any]:
    """Live health, or an honest 'cannot tell'."""
    try:
        from reyes_agent import agent_runtime

        raw = agent_runtime.health()
    except Exception as exc:  # noqa: BLE001
        return {"state": FAILED, "reason": f"agent runtime unavailable: {type(exc).__name__}",
                "agents": [], "running": False}

    running = bool(raw.get("running", False))
    working = list(raw.get("working_now", []) or [])
    failures = int(raw.get("tasks_failed", 0) or 0)
    alive = int(raw.get("workers_alive", 0) or 0)

    if not running:
        state = STOPPED
    elif alive == 0:
        state = FAILED
    elif failures and raw.get("last_error"):
        state = DEGRADED
    else:
        state = HEALTHY

    return {"state": state, "running": running, "workers_alive": alive,
            "working_now": working, "tasks_failed": failures,
            "last_error": str(raw.get("last_error", ""))[:200],
            "source": "agent_runtime.health()"}


def ok() -> bool:
    return snapshot()["state"] in {HEALTHY, DEGRADED}
