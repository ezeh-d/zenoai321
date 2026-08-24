"""Agent2Agent (A2A) trust & permission abstraction (pack5 #2-10).

The real A2A wire protocol (a2a-python) is a deferred provider; what matters
first, and what lives here, is the SAFETY layer it must plug into: every remote
agent has a trust level, a new one is quarantined (read-only, no sensitive data,
no side effects), and A2A can never bypass ZENO's permissions. Capability cards
and task contracts are validated as data. Pure logic, thread-safe, never raises.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

# Trust levels (pack5 #4), weakest to strongest.
BLOCKED = "BLOCKED"
UNKNOWN = "UNKNOWN"
PARTNER = "PARTNER"
REMOTE_TRUSTED = "REMOTE_TRUSTED"
LOCAL_TRUSTED = "LOCAL_TRUSTED"
_LEVELS = {BLOCKED, UNKNOWN, PARTNER, REMOTE_TRUSTED, LOCAL_TRUSTED}

# Actions an external agent might attempt. `may()` decides per trust level.
READ = "read"
DISCOVER = "discover"
SIDE_EFFECT = "side_effect"
SENSITIVE_DATA = "sensitive_data"

# What each trust level may do. A new (UNKNOWN) agent is quarantined (#10):
# read-only, no sensitive data, no external side effects.
_ALLOWED = {
    BLOCKED: set(),
    UNKNOWN: {READ, DISCOVER},
    PARTNER: {READ, DISCOVER, SIDE_EFFECT},
    REMOTE_TRUSTED: {READ, DISCOVER, SIDE_EFFECT},
    LOCAL_TRUSTED: {READ, DISCOVER, SIDE_EFFECT, SENSITIVE_DATA},
}


@dataclass
class CapabilityCard:
    """What an external agent advertises (pack5 #3)."""
    name: str
    description: str = ""
    capabilities: tuple[str, ...] = ()
    modalities: tuple[str, ...] = ("text",)
    authentication: str = ""
    supported_tasks: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "capabilities": list(self.capabilities),
                "modalities": list(self.modalities),
                "authentication": self.authentication,
                "supported_tasks": list(self.supported_tasks)}


@dataclass
class RemoteAgent:
    agent_id: str
    card: CapabilityCard
    publisher: str = ""
    endpoint: str = ""
    trust: str = UNKNOWN

    def as_dict(self) -> dict[str, Any]:
        return {"agent_id": self.agent_id, "publisher": self.publisher,
                "endpoint": self.endpoint, "trust": self.trust,
                "card": self.card.as_dict()}


# Required fields on a remote task contract (pack5 #5).
_TASK_FIELDS = ("task_id", "goal", "inputs", "allowed_tools",
                "deadline", "budget", "expected_output")


class A2ARegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._agents: dict[str, RemoteAgent] = {}

    def register_agent(self, agent_id: str, card: CapabilityCard, *,
                       publisher: str = "", endpoint: str = "",
                       trust: str = UNKNOWN) -> RemoteAgent:
        """Register (or refresh) a remote agent. New agents are QUARANTINED at
        UNKNOWN unless an explicit higher trust is supplied by the owner."""
        aid = str(agent_id or "").strip()
        level = trust if trust in _LEVELS else UNKNOWN
        with self._lock:
            agent = RemoteAgent(aid, card, str(publisher), str(endpoint), level)
            self._agents[aid] = agent
            return agent

    def set_trust(self, agent_id: str, trust: str) -> bool:
        if trust not in _LEVELS:
            return False
        with self._lock:
            agent = self._agents.get(str(agent_id or "").strip())
            if agent is None:
                return False
            agent.trust = trust
            return True

    def block(self, agent_id: str) -> bool:
        return self.set_trust(agent_id, BLOCKED)

    def trust_of(self, agent_id: str) -> str:
        with self._lock:
            agent = self._agents.get(str(agent_id or "").strip())
            return agent.trust if agent else UNKNOWN

    def may(self, agent_id: str, action: str) -> bool:
        """Whether a remote agent may perform an action. This NEVER widens what
        ZENO's own permission engine allows -- it only ever narrows (#2)."""
        return action in _ALLOWED.get(self.trust_of(agent_id), set())

    def permissions(self, agent_id: str) -> dict[str, bool]:
        allowed = _ALLOWED.get(self.trust_of(agent_id), set())
        return {a: (a in allowed) for a in (READ, DISCOVER, SIDE_EFFECT, SENSITIVE_DATA)}

    def discover(self) -> list[dict[str, Any]]:
        """Approved (non-blocked) agents ZENO knows about. Discovery is not
        trust (#7): a discovered agent is still UNKNOWN until promoted."""
        with self._lock:
            return [a.as_dict() for a in self._agents.values() if a.trust != BLOCKED]

    def validate_task(self, contract: dict[str, Any]) -> tuple[bool, str]:
        """A remote task must be a complete contract before ZENO runs it (#5)."""
        if not isinstance(contract, dict):
            return False, "task contract must be an object"
        missing = [f for f in _TASK_FIELDS if f not in contract]
        if missing:
            return False, f"missing task fields: {', '.join(missing)}"
        return True, ""

    def validate_result(self, agent_id: str, result: Any) -> tuple[bool, str]:
        """Remote output is validated before ZENO acts on it (#6). A blocked
        agent's result is rejected outright; otherwise require non-empty data."""
        if self.trust_of(agent_id) == BLOCKED:
            return False, "result from a blocked agent"
        if result is None or (isinstance(result, (str, list, dict)) and len(result) == 0):
            return False, "empty result"
        return True, ""

    def forget(self, agent_id: str) -> bool:
        with self._lock:
            return self._agents.pop(str(agent_id or "").strip(), None) is not None


_instance: A2ARegistry | None = None
_instance_lock = threading.Lock()


def get_registry() -> A2ARegistry:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = A2ARegistry()
        return _instance
