"""Owner-facing read-only tools for ZENO's operational control plane."""
from __future__ import annotations

import json
import time

from reyes_agent.tools import register


@register(name="zeno_doctor",
          description=("Diagnose ZENO or one named capability using real dependency, device, "
                       "authentication, health and evidence state. Use for 'diagnose yourself' "
                       "or 'why did this capability fail'."),
          input_schema={"type": "object", "properties": {
              "capability": {"type": "string"}}})
def zeno_doctor(capability: str = "") -> str:
    from reyes_agent.doctor import get_doctor
    return json.dumps(get_doctor().diagnose(capability), default=str)


@register(name="capability_diagnose",
          description=("Report the exact availability state and dependency root cause for a "
                       "specific ZENO capability. Does not execute it."),
          input_schema={"type": "object", "properties": {
              "capability": {"type": "string"}}, "required": ["capability"]})
def capability_diagnose(capability: str) -> str:
    from reyes_agent.capability_truth import get_truth
    return json.dumps(get_truth().diagnose(capability), default=str)


@register(name="evidence_history",
          description=("Read ZENO's redacted, verified action history: what it did, what an "
                       "agent ran, or why a command failed."),
          input_schema={"type": "object", "properties": {
              "command_id": {"type": "string"}, "agent": {"type": "string"},
              "capability": {"type": "string"}, "hours": {"type": "number"},
              "limit": {"type": "integer"}}})
def evidence_history(command_id: str = "", agent: str = "", capability: str = "",
                   hours: float = 24, limit: int = 50) -> str:
    from reyes_agent.evidence_ledger import get_evidence_ledger
    since = time.time() - max(0.0, float(hours)) * 3600
    return json.dumps(get_evidence_ledger().history(command_id=command_id, agent=agent,
                      capability=capability, since=since, limit=limit), default=str)


@register(name="mission_control_status",
          description=("Open/read ZENO Mission Control's real devices, capabilities, tools, "
                       "agents, tasks, permissions, traces, resources, errors and quality."),
          input_schema={"type": "object", "properties": {}})
def mission_control_status() -> str:
    from reyes_agent.mission_control import get_mission_control
    return json.dumps(get_mission_control().snapshot(), default=str)


@register(name="zeno_quality_score",
          description=("Show ZENO's quality score calculated only from measured telemetry. "
                       "Unmeasured dimensions are reported as unknown, never invented."),
          input_schema={"type": "object", "properties": {}})
def zeno_quality_score() -> str:
    from reyes_agent.quality_score import get_quality_score
    return json.dumps(get_quality_score().score(), default=str)
