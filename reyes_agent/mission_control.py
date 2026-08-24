"""Owner/developer Mission Control read model composed from real authorities."""
from __future__ import annotations

from typing import Any


class MissionControl:
    def snapshot(self) -> dict[str, Any]:
        from reyes_agent import agent_runtime, event_bus, microphone, permissions, provider_manager
        from reyes_agent.capability_snapshot import system_status
        from reyes_agent.capability_truth import get_truth, seed_baseline, seed_tool_registry
        from reyes_agent.evidence_ledger import get_evidence_ledger
        from reyes_agent.observability import get_tracer
        from reyes_agent.quality_score import get_quality_score
        from reyes_agent.resource_governor import get_resource_governor
        from reyes_agent.tools.missions import list_missions_dicts
        from reyes_agent.unified_session import get_session_state
        seed_baseline()
        seed_tool_registry()
        try:
            agents = agent_runtime.health()
        except Exception as exc:
            agents = {"state": "DEGRADED", "error": type(exc).__name__}
        try:
            missions = list_missions_dicts()
        except Exception:
            missions = []
        try:
            from reyes_agent.memory import get_memory_manager
            memory = get_memory_manager().status()
        except Exception as exc:
            memory = {"state": "DEGRADED", "error": type(exc).__name__}
        failures = [row for row in get_evidence_ledger().history(limit=100)
                    if row.get("verification") == "FAILED"][:25]
        session = get_session_state().snapshot()
        return {
            "OVERVIEW": system_status(),
            "DEVICES": session["connected_devices"],
            "CAPABILITIES": get_truth().dashboard(),
            "TOOLS": system_status().get("tools", 0),
            "AGENTS": agents,
            "TASKS": missions,
            "MODELS": provider_manager.status(),
            "VOICE": {"state": session["voice_state"], "microphone": microphone.runtime_status()},
            "MEMORY": memory,
            "PERMISSIONS": permissions.describe(),
            "OBSERVABILITY": get_tracer().snapshot(25),
            "QUALITY": get_quality_score().score(),
            "ERRORS": failures,
            "EVENTS": event_bus.runtime_stats(),
            "RESOURCES": get_resource_governor().evaluate(),
        }


_mission_control = MissionControl()


def get_mission_control() -> MissionControl:
    return _mission_control
