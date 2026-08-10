"""One registry over ZENO's real agents -- not a second agent system.

WHAT THIS IS
------------
`agent_teams` already defines the specialists and their bounded workers.
`agent_runtime` already supervises them with health, restart, cancellation
and task submission. `worker_pool` already provides priorities, deadlines
and backpressure. Those work.

What was missing was ONE place to ask "who exists, what are they for, and
are they healthy" without knowing which of the three modules owns which
half of the answer. This is that place. It holds no agent state of its own.

MICROSOFT AGENT FRAMEWORK
-------------------------
`ZENO_AGENT_FRAMEWORK_ENABLED` is an adapter seam, off by default. MAF is a
capable orchestrator, but running it alongside the existing supervisor would
mean two schedulers with two views of which agent is busy -- which is how a
task gets executed twice. If it is ever switched on it must REPLACE the
backend here, not run beside it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ZENO is the executive. Everything else is a specialist it may delegate to.
EXECUTIVE = "ZENO"


@dataclass
class AgentInfo:
    name: str
    role: str = ""
    workers: list[str] = field(default_factory=list)
    status: str = "unknown"
    busy: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "role": self.role, "workers": self.workers,
                "status": self.status, "busy": self.busy}


def _teams() -> dict[str, list]:
    try:
        from reyes_agent import agent_teams

        return agent_teams.teams()
    except Exception:  # noqa: BLE001 -- a missing team map is not a crash
        return {}


def _health() -> dict[str, Any]:
    try:
        from reyes_agent import agent_runtime

        return agent_runtime.health()
    except Exception:  # noqa: BLE001
        return {}


def agents() -> list[AgentInfo]:
    """Every specialist ZENO can delegate to, with live status."""
    health = _health()
    working = set(health.get("working_now", []) or [])
    known = _teams()

    infos: list[AgentInfo] = []
    for parent, workers in sorted(known.items()):
        infos.append(AgentInfo(
            name=parent,
            role=getattr(workers[0], "role", "") if workers else "",
            workers=[getattr(w, "name", str(w)) for w in workers],
            status="working" if parent in working else "idle",
            busy=parent in working,
        ))
    return infos


def names() -> list[str]:
    return [a.name for a in agents()]


def get(name: str) -> AgentInfo | None:
    wanted = str(name or "").strip().casefold()
    return next((a for a in agents() if a.name.casefold() == wanted), None)


def describe() -> dict[str, Any]:
    """Registry snapshot for diagnostics and the mobile API."""
    from reyes_agent import integrations

    listed = agents()
    return {
        "executive": EXECUTIVE,
        "specialists": [a.as_dict() for a in listed],
        "count": len(listed),
        "busy": sum(1 for a in listed if a.busy),
        "backend": ("microsoft-agent-framework" if integrations.AGENT_FRAMEWORK_ENABLED
                    else "zeno agent_teams + agent_runtime + worker_pool"),
        "agent_framework_enabled": integrations.AGENT_FRAMEWORK_ENABLED,
        "agent_framework_installed": integrations.available("agent_framework"),
        "note": ("ZENO is the executive and decides delegation. This registry reports the "
                 "existing supervisor's state; it does not schedule anything itself."),
    }
