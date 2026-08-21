"""Read-only operating projection for ZENO's Agent Space.

The canonical registry, supervisor, teams, confirmation queue and Event Bus
already exist.  This module owns none of them: it joins their observable state
into one bounded, privacy-safe response for the desktop and phone views.
"""
from __future__ import annotations

import re
import time
from typing import Any


_IDENTITIES: dict[str, dict[str, str]] = {
    "zeno": {"name": "ZENO", "color": "#719bff", "icon": "core"},
    "aris": {"name": "ARIS", "color": "#3ddc7a", "icon": "research"},
    "tosin": {"name": "TOSIN", "color": "#a855f7", "icon": "code"},
    "stark": {"name": "STARK", "color": "#ef4444", "icon": "shield"},
    "ava": {"name": "AVA", "color": "#e11d48", "icon": "target"},
    "zeal": {"name": "ZEAL", "color": "#f5c518", "icon": "creative"},
    "titan": {"name": "TITAN", "color": "#f97316", "icon": "business"},
    "apex": {"name": "APEX", "color": "#22d3ee", "icon": "gaming"},
    "nova": {"name": "NOVA", "color": "#f472b6", "icon": "vision"},
    "hermes_comm": {"name": "HERMES", "color": "#c8d0dc", "icon": "message"},
    "oracle": {"name": "ORACLE", "color": "#06b6d4", "icon": "analytics"},
    "kate": {"name": "KATE", "color": "#6366f1", "icon": "education"},
    "ultron": {"name": "ULTRON", "color": "#b91c1c", "icon": "strategy"},
    "atlas": {"name": "ATLAS", "color": "#3b5a8a", "icon": "mission"},
    "helios": {"name": "HELIOS", "color": "#10b981", "icon": "wellness"},
    "jarvis": {"name": "JARVIS", "color": "#52e7ff", "icon": "systems"},
}
_FALLBACK_COLORS = ("#38bdf8", "#c084fc", "#fb7185", "#fbbf24", "#34d399", "#60a5fa")
_VISIBLE_EVENTS = {
    "agent.handoff", "agent.message", "agent.task_queued", "agent.task_started",
    "agent.task_finished", "agent.worker_started", "agent.worker_finished",
    "agent.speaking", "agent.voice_stopped", "agent.restarting", "agent.restarted",
    "agent.joined", "agent.state_changed", "agent.expression_changed",
    "agent.standby", "agent.removed",
}
_SAFE_PAYLOAD = {
    "agent", "parent", "worker", "from", "to", "task_id", "task", "role",
    "tool", "outcome", "ok", "state", "visual_state", "status", "summary",
    "duration_ms", "capability",
}
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|secret|password|passwd|token|authorization|cookie)\b\s*[=:]\s*\S+"
)


def _identity(agent_id: str) -> dict[str, str]:
    known = _IDENTITIES.get(agent_id)
    if known:
        return dict(known)
    color = _FALLBACK_COLORS[sum(ord(char) for char in agent_id) % len(_FALLBACK_COLORS)]
    return {"name": agent_id.replace("_", " ").upper(), "color": color, "icon": "agent"}


def _safe_text(value: Any, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())[: max(0, limit)]
    if not text:
        return ""
    try:
        from reyes_agent.security.privacy import detector

        for hit in reversed(detector.detect(text)):
            text = text[: hit.start] + "[private]" + text[hit.end :]
    except Exception:  # noqa: BLE001 -- the operating view must stay available
        pass
    return _SECRET_ASSIGNMENT.sub(r"\1=[private]", text)


def _event_rows(limit: int) -> list[dict[str, Any]]:
    from reyes_agent import agent_runtime, agent_teams, event_bus

    valid_agents = {"zeno", *agent_runtime.AGENT_ROLES}
    valid_agents.update(worker.name for workers in agent_teams.teams().values() for worker in workers)

    rows: list[dict[str, Any]] = []
    for event in reversed(event_bus.history(limit=max(60, min(400, limit * 5)), event_type="agent")):
        if event.get("type") not in _VISIBLE_EVENTS:
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        raw_source = payload.get("from") or payload.get("parent") or payload.get("agent") or "zeno"
        raw_target = payload.get("to") or payload.get("worker") or (
            payload.get("agent") if str(raw_source).casefold() == "zeno" else "zeno"
        )
        source = str(raw_source).strip().casefold()
        target = str(raw_target).strip().casefold()
        if source not in valid_agents or target not in valid_agents:
            # Test probes and unknown producers remain in the durable Event
            # Bus/Timeline, but they are not members of the Agent Space. Check
            # this before the more expensive privacy scan.
            continue
        clean: dict[str, Any] = {}
        for key in _SAFE_PAYLOAD:
            if key not in payload:
                continue
            value = payload[key]
            clean[key] = value if isinstance(value, (bool, int, float)) else _safe_text(value)
        rows.append({
            "id": event.get("id"), "timestamp": event.get("ts"),
            "time": event.get("ts_human", ""), "type": event.get("type", ""),
            "source": source, "target": target, "task_id": clean.get("task_id", ""),
            "summary": clean.get("summary") or clean.get("task") or clean.get("status") or "",
            "status": clean.get("outcome") or clean.get("visual_state") or clean.get("state") or (
                "DONE" if clean.get("ok") is True else "FAILED" if clean.get("ok") is False else "UPDATE"
            ),
            "payload": clean,
        })
        if len(rows) >= limit:
            break
    rows.reverse()
    return rows


def _voice_map() -> dict[str, dict[str, Any]]:
    try:
        from reyes_agent import voice_manager

        return {row["agent"]: {
            "configured": bool(row.get("voice_id")),
            "own_voice": bool(row.get("own_voice")),
            "using_fallback": bool(row.get("using_fallback")),
            "description": row.get("description", ""),
        } for row in voice_manager.registry()}
    except Exception:  # noqa: BLE001
        return {}


def _pending_approvals() -> list[dict[str, Any]]:
    try:
        from reyes_agent import confirmation

        return [{
            "id": item.id, "tool": _safe_text(item.tool_name, 80),
            "description": _safe_text(item.description, 180), "status": item.status,
            "created_at": item.created_at, "owner": "zeno",
        } for item in confirmation.list_pending()[:30]]
    except Exception:  # noqa: BLE001
        return []


def snapshot(*, event_limit: int = 60, phone: bool = False) -> dict[str, Any]:
    """Return one truthful bounded view over the existing runtime."""
    from reyes_agent import agent_presence, agent_runtime, agent_teams
    from reyes_agent.tools.subagents import _SPECIALISTS

    runtime = agent_runtime.health()
    teams = agent_teams.describe()
    voices = _voice_map()
    runtime_by_id = {row["agent"]: row for row in runtime.get("agents", [])}
    explicit_presence = agent_presence.get_agent_presence().snapshot()
    explicit_by_id = {row["agent"]: row for row in explicit_presence["active_agents"]}
    agents: list[dict[str, Any]] = []
    active: list[str] = []
    for agent_id, role in agent_runtime.AGENT_ROLES.items():
        observed = runtime_by_id.get(agent_id, {})
        status, reason = agent_runtime.presence_status(observed) if observed else (
            agent_runtime.S_OFFLINE, "no runtime snapshot"
        )
        display_state = {
            agent_runtime.ONLINE: "READY",
            agent_runtime.S_WORKING: "ACTIVE",
            agent_runtime.S_THINKING: "BUSY",
            agent_runtime.S_DELEGATING: "ROUTING",
            agent_runtime.S_ERROR: "ERROR",
            agent_runtime.S_OFFLINE: "REGISTERED",
        }.get(status, str(status or "REGISTERED").upper())
        if observed and not observed.get("healthy", True):
            display_state = "DEGRADED"
        if observed.get("state") == agent_runtime.WORKING:
            active.append(agent_id)
        explicit = explicit_by_id.get(agent_id)
        if explicit and agent_id not in active:
            active.append(agent_id)
        runtime_working = observed.get("state") == agent_runtime.WORKING
        projected_state = ("WORKING" if runtime_working else
                           str(explicit.get("state", "listening")).upper()
                           if explicit else display_state)
        team = teams.get("parents", {}).get(agent_id, {"workers": [], "count": 0})
        spec = _SPECIALISTS.get(agent_id) or {}
        identity = _identity(agent_id)
        row = {
            "id": agent_id, **identity, "role": role,
            "description": _safe_text(spec.get("description", ""), 260),
            "state": projected_state,
            "state_reason": (_safe_text(reason, 160) if runtime_working else
                             "explicitly summoned into the current conversation"
                             if explicit else _safe_text(reason, 160)),
            "runtime_state": observed.get("state", "standby"),
            "alive": bool(observed.get("alive")), "healthy": bool(observed.get("healthy", True)),
            "speaking": False, "routed": agent_id in active,
            "active_task_count": int(bool(observed.get("current_task"))) + int(observed.get("queue_depth", 0) or 0),
            "current_task": _safe_text((observed.get("current_task", "") if runtime_working else "")
                                       or (explicit or {}).get("current_task")
                                       or observed.get("current_task", "")),
            "last_task": _safe_text(observed.get("last_task", "")),
            "queue_depth": observed.get("queue_depth", 0),
            "heartbeat_age_s": observed.get("heartbeat_age_s"),
            "tasks_completed": observed.get("tasks_completed", 0),
            "tasks_failed": observed.get("tasks_failed", 0),
            "last_error": _safe_text(observed.get("last_error", ""), 180),
            "voice": voices.get(agent_id, {"configured": False, "own_voice": False,
                                             "using_fallback": False, "description": ""}),
            "allowed_tools": sorted(str(tool) for tool in spec.get("tools", set())),
            "workers": team.get("workers", []), "worker_count": team.get("count", 0),
        }
        if phone:
            row = {key: row[key] for key in (
                "id", "name", "color", "role", "state", "speaking", "routed",
                "active_task_count", "current_task", "healthy",
            )}
        agents.append(row)

    events = _event_rows(max(10, min(100, event_limit)))
    now = time.time()
    speaking: set[str] = set()
    voice_decided: set[str] = set()
    for event in reversed(events):
        agent_id = str(event.get("payload", {}).get("agent") or "")
        if not agent_id or agent_id in voice_decided:
            continue
        if now - float(event.get("timestamp") or 0) > 120:
            continue
        if event["type"] == "agent.speaking":
            speaking.add(agent_id)
            voice_decided.add(agent_id)
        elif event["type"] == "agent.voice_stopped":
            voice_decided.add(agent_id)
    for row in agents:
        row["speaking"] = row["id"] in speaking
        if row["speaking"]:
            row["state"] = "TALKING"

    approvals = _pending_approvals()
    participants = list(dict.fromkeys(active + [event["source"] for event in events[-20:]
                                                if event["source"] not in {"", "zeno"}]))
    participants = [agent_id for agent_id in participants if agent_id in agent_runtime.AGENT_ROLES]
    return {
        "schema": 1, "generated_at": now,
        "master": {"id": "zeno", **_identity("zeno"), "role": "Executive Orchestrator",
                   "state": "ROUTING" if active else "READY",
                   "policy_controller": True, "final_synthesizer": True},
        "owner": "divine", "agents": agents, "active_agents": active,
        "active_specialist": explicit_presence.get("last_addressed") or (active[0] if active else ""),
        "council": {"active": len(active) > 1, "participants": participants,
                    "current_speaker": next(iter(speaking), ""),
                    "final_authority": "zeno"},
        "events": events, "approvals": approvals,
        "presence": explicit_presence,
        "summary": {"registered": len(agents), "alive": runtime.get("agents_alive", 0),
                    "active": len(active), "queued": runtime.get("queued_tasks", 0),
                    "workers": teams.get("total_workers", 0), "pending_approvals": len(approvals)},
        "source": "agent_runtime + agent_teams + event_bus + confirmation + voice_manager",
    }


def agent_detail(agent_id: str) -> dict[str, Any] | None:
    wanted = str(agent_id or "").strip().casefold()
    view = snapshot(event_limit=100)
    return next((row for row in view["agents"] if row["id"] == wanted), None)
