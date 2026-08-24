"""Authoritative conversational presence for explicitly summoned agents.

The specialist runtime remains the authority for *work*.  This module owns
only the much smaller question "which specialists did the owner invite into
the current conversation?".  Keeping that distinction prevents a visual
summon from starting an idle worker thread or duplicating the agent engine.

Real task/speech state still arrives through :mod:`event_bus`; the desktop,
Mini Orb and phone all project the same records and lifecycle events.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any


_ALIASES: dict[str, str] = {
    "hermes": "hermes_comm", "communications": "hermes_comm",
    "security guy": "stark", "security agent": "stark",
    "academic agent": "kate", "teacher": "kate",
    "research agent": "aris", "researcher": "aris",
    "coding agent": "tosin", "developer": "tosin",
    "strategy agent": "ultron", "strategist": "ultron",
    "analytics agent": "oracle", "data agent": "oracle",
    "creative agent": "zeal", "designer": "zeal",
    "vision agent": "nova", "mission control": "atlas",
    "wellbeing agent": "helios", "gaming agent": "apex",
}
_COUNCIL = ("stark", "kate", "oracle", "ultron", "aris")
_TERMINAL = {"success", "error", "standby"}
_STATES = {
    "idle", "listening", "acknowledging", "thinking", "speaking",
    "working", "happy", "confused", "concerned", "serious", "success",
    "error", "standby", "waiting",
}


@dataclass
class Presence:
    agent: str
    state: str = "listening"
    expression: str = "acknowledging"
    current_task: str = ""
    joined_at: float = 0.0
    updated_at: float = 0.0
    persistent: bool = True

    def public(self) -> dict[str, Any]:
        row = asdict(self)
        row["active"] = self.state != "standby"
        return row


class AgentPresenceManager:
    """Bounded, thread-safe session presence; never creates agent workers."""

    def __init__(self, *, maximum: int = 8) -> None:
        self._maximum = max(1, min(int(maximum), 12))
        self._lock = threading.RLock()
        self._active: dict[str, Presence] = {}
        self._last_addressed = ""

    @staticmethod
    def resolve(value: str) -> str:
        from reyes_agent import agent_runtime

        clean = " ".join(re.sub(r"[^a-z0-9_ ]+", " ", str(value or "").casefold()).split())
        clean = _ALIASES.get(clean, clean.replace(" ", "_"))
        if clean == "zeno" or clean not in agent_runtime.AGENT_ROLES:
            return ""
        return clean

    def summon(self, names: list[str] | tuple[str, ...], *, source: str = "owner") -> dict[str, Any]:
        now = time.time()
        joined: list[str] = []
        already: list[str] = []
        with self._lock:
            for raw in names:
                agent = self.resolve(raw)
                if not agent:
                    continue
                if agent in self._active:
                    already.append(agent)
                    self._last_addressed = agent
                    continue
                if len(self._active) >= self._maximum:
                    break
                self._active[agent] = Presence(
                    agent=agent, joined_at=now, updated_at=now,
                    state="listening", expression="acknowledging")
                self._last_addressed = agent
                joined.append(agent)
        for agent in joined:
            self._publish("agent.joined", {
                "agent": agent, "state": "listening", "visual_state": "waiting",
                "expression": "acknowledging", "emotion": "curious",
                "persistent": True, "requested_by": source,
            })
        if joined:
            try:
                from reyes_agent.unified_session import get_session_state
                get_session_state().update(source="agent_presence", notify=False,
                                           active_agents=self.active_ids())
            except Exception:
                pass
        return {"joined": joined, "already_active": already,
                "active_agents": self.active_ids()}

    def summon_council(self, *, source: str = "owner") -> dict[str, Any]:
        result = self.summon(list(_COUNCIL), source=source)
        self._publish("agent.council_joined", {
            "agents": result["active_agents"], "state": "listening",
            "requested_by": source,
        })
        return result

    def dismiss(self, names: list[str] | tuple[str, ...], *, source: str = "owner") -> dict[str, Any]:
        removed: list[str] = []
        with self._lock:
            for raw in names:
                agent = self.resolve(raw)
                if agent and self._active.pop(agent, None) is not None:
                    removed.append(agent)
            if self._last_addressed in removed:
                self._last_addressed = next(reversed(self._active), "")
        for agent in removed:
            self._publish("agent.standby", {
                "agent": agent, "state": "standby", "visual_state": "standby",
                "expression": "neutral", "requested_by": source,
            })
            self._publish("agent.removed", {"agent": agent, "requested_by": source})
        if removed:
            try:
                from reyes_agent.unified_session import get_session_state
                get_session_state().update(source="agent_presence", notify=False,
                                           active_agents=self.active_ids())
            except Exception:
                pass
        return {"removed": removed, "active_agents": self.active_ids()}

    def standby_all(self, *, source: str = "owner") -> dict[str, Any]:
        with self._lock:
            names = list(self._active)
        return self.dismiss(names, source=source)

    def observe_event(self, event: Any) -> None:
        """Update an explicitly-present participant from a real lifecycle event."""
        event_type = str(getattr(event, "type", "") or (event.get("type", "") if isinstance(event, dict) else ""))
        payload = getattr(event, "payload", None)
        if payload is None and isinstance(event, dict):
            payload = event.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        agent = self.resolve(str(payload.get("agent") or payload.get("to") or ""))
        if not agent or event_type in {"agent.joined", "agent.standby", "agent.removed"}:
            return
        state = str(payload.get("visual_state") or payload.get("state") or "").casefold()
        if not state:
            if event_type in {"agent.task_started", "agent.thinking"}:
                state = "thinking"
            elif event_type == "agent.working":
                state = "working"
            elif event_type == "agent.speaking":
                state = "speaking"
            elif event_type == "agent.voice_stopped":
                state = "listening"
            elif event_type == "agent.task_finished":
                state = "error" if payload.get("ok") is False else "success"
        if state not in _STATES:
            return
        with self._lock:
            presence = self._active.get(agent)
            if presence is None:
                return
            presence.state = state
            presence.expression = str(payload.get("emotion") or payload.get("expression") or state)[:32]
            presence.current_task = " ".join(str(payload.get("task") or presence.current_task).split())[:180]
            presence.updated_at = time.time()
            self._last_addressed = agent

    def active_ids(self) -> list[str]:
        with self._lock:
            return list(self._active)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema": 1,
                "generated_at": time.time(),
                "active_agents": [row.public() for row in self._active.values()],
                "last_addressed": self._last_addressed,
                "maximum": self._maximum,
            }

    @staticmethod
    def _publish(event_type: str, payload: dict[str, Any]) -> None:
        try:
            from reyes_agent import event_bus

            event_bus.publish(event_type, payload, source="agent_presence")
        except Exception:
            pass


_manager: AgentPresenceManager | None = None
_manager_lock = threading.Lock()


def get_agent_presence() -> AgentPresenceManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = AgentPresenceManager()
    return _manager


def reset_for_tests() -> AgentPresenceManager:
    global _manager
    with _manager_lock:
        _manager = AgentPresenceManager()
        return _manager


def _mentioned_agents(text: str) -> list[str]:
    manager = get_agent_presence()
    normalized = " ".join(re.sub(r"[^a-z0-9_ ]+", " ", text.casefold()).split())
    found: list[tuple[int, str]] = []
    candidates = set(_ALIASES) | set(__import__("reyes_agent.agent_runtime", fromlist=["AGENT_ROLES"]).AGENT_ROLES)
    for candidate in candidates:
        match = re.search(rf"\b{re.escape(candidate.replace('_', ' '))}\b", normalized)
        if match:
            resolved = manager.resolve(candidate)
            if resolved:
                found.append((match.start(), resolved))
    return list(dict.fromkeys(agent for _index, agent in sorted(found)))


def handle_command(message: str) -> str | None:
    """Handle only explicit summon/dismiss language; return ``None`` otherwise."""
    text = " ".join(str(message or "").split())
    normalized = " ".join(re.sub(r"[^a-z0-9_ ]+", " ", text.casefold()).split())
    if not normalized:
        return None
    manager = get_agent_presence()

    # ZENO standby belongs to the existing wake/conversation state machine.
    if re.search(r"\bzeno\b.*\bstandby\b|\bstandby\b.*\bzeno\b", normalized):
        return None
    if re.search(r"\b(?:all agents|everyone|the council)\b.*\b(?:standby|dismiss|leave|go)\b", normalized):
        result = manager.standby_all()
        return "All summoned agents are standing by." if result["removed"] else "No sub-agent is currently summoned."

    names = _mentioned_agents(normalized)
    dismissing = bool(re.search(r"\b(?:standby|dismiss|send back|can go|may go|leave us|that s all)\b", normalized))
    summoning = bool(re.search(
        r"\b(?:call|bring|get|summon|invite|join|need|speak with|talk to|let me speak with)\b",
        normalized))
    if dismissing and names:
        result = manager.dismiss(names)
        if not result["removed"]:
            return "Those agents are already on standby."
        labels = [name.replace("hermes_comm", "Hermes").replace("_", " ").upper() for name in result["removed"]]
        return f"{' and '.join(labels)} {'are' if len(labels) > 1 else 'is'} standing by."
    if summoning and re.search(r"\b(?:the |full )?council\b", normalized):
        result = manager.summon_council()
        return ("The Council is here." if result["joined"] else
                "The Council participants are already here.")
    if summoning and names:
        result = manager.summon(names)
        if not result["joined"]:
            return "They are already here."
        labels = [name.replace("hermes_comm", "Hermes").replace("_", " ").upper() for name in result["joined"]]
        return f"{' and '.join(labels)} {'are' if len(labels) > 1 else 'is'} here."
    return None
