"""Agent-facing controls for ZENO's durable, owner-approved skills."""

from __future__ import annotations

import json
from typing import Any

from reyes_agent.skills import manager, registry
from reyes_agent.tools import register


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _public(skill) -> dict[str, Any]:
    return {
        "skill_id": skill.skill_id,
        "name": skill.name,
        "description": skill.description,
        "state": skill.state,
        "version": skill.version,
        "observations": skill.observations,
        "confidence": skill.confidence,
        "runnable": skill.runnable,
        "required_tools": list(skill.required_tools),
        "steps": [{"action": step.action, "expect": step.expect,
                   "on_failure": step.on_failure} for step in skill.steps],
        "history": skill.history.as_dict(),
    }


@register(
    name="skill_list",
    description="List ZENO's real persisted skills and their approval/runnable state.",
    input_schema={"type": "object", "properties": {"state": {"type": "string"}}},
)
def skill_list(state: str = "") -> str:
    wanted = str(state or "").strip().upper()
    skills = registry.all_skills(wanted)
    return _json({"state": "READY" if skills else "EMPTY", "count": len(skills),
                  "skills": [_public(skill) for skill in skills]})


@register(
    name="skill_inspect",
    description="Inspect one persisted skill, including steps, evidence and run history.",
    input_schema={"type": "object", "properties": {"skill": {"type": "string"}},
                  "required": ["skill"]},
)
def skill_inspect(skill: str) -> str:
    found = registry.get(skill) or registry.by_name(skill)
    if found is None:
        return _json({"ok": False, "state": "FAILED", "error": f"No skill '{skill}'."})
    return _json({"state": "READY", "skill": _public(found)})


@register(
    name="skill_scan",
    description=("Scan existing action history for genuinely repeated workflows, persist "
                 "qualifying suggestions, and list what still needs owner approval."),
    input_schema={"type": "object", "properties": {}},
)
def skill_scan() -> str:
    created = manager.learn()
    suggestions = manager.suggest(limit=10)
    return _json({"state": "READY", "new_suggestions": len(created),
                  "suggestions": suggestions, "evidence": manager.status()["learner"]})


@register(
    name="skill_approve",
    description="Approve one learned skill after the owner reviews it. This makes it runnable.",
    input_schema={"type": "object", "properties": {"skill": {"type": "string"}},
                  "required": ["skill"]},
    requires_confirmation=True,
)
def skill_approve(skill: str) -> str:
    found = registry.get(skill) or registry.by_name(skill)
    if found is None:
        return _json({"ok": False, "state": "FAILED", "error": f"No skill '{skill}'."})
    ok, reason = manager.approve(found.skill_id, approved_by="owner")
    stored = registry.get(found.skill_id)
    verified = bool(ok and stored and stored.state == "APPROVED" and stored.runnable)
    return _json({"ok": verified, "state": "COMPLETED" if verified else "FAILED",
                  "verified": verified, "evidence": reason, "skill_id": found.skill_id})


@register(
    name="skill_disable",
    description="Disable a persisted skill without deleting its history.",
    input_schema={"type": "object", "properties": {"skill": {"type": "string"}},
                  "required": ["skill"]},
    requires_confirmation=True,
)
def skill_disable(skill: str) -> str:
    found = registry.get(skill) or registry.by_name(skill)
    if found is None:
        return _json({"ok": False, "state": "FAILED", "error": f"No skill '{skill}'."})
    ok, reason = manager.reject(found.skill_id, why="disabled by owner")
    stored = registry.get(found.skill_id)
    verified = bool(ok and stored and stored.state == "RETIRED" and not stored.runnable)
    return _json({"ok": verified, "state": "COMPLETED" if verified else "FAILED",
                  "verified": verified, "evidence": reason, "skill_id": found.skill_id})


@register(
    name="skill_delete",
    description="Permanently delete one persisted skill after owner confirmation.",
    input_schema={"type": "object", "properties": {"skill": {"type": "string"}},
                  "required": ["skill"]},
    requires_confirmation=True,
)
def skill_delete(skill: str) -> str:
    found = registry.get(skill) or registry.by_name(skill)
    if found is None:
        return _json({"ok": False, "state": "FAILED", "error": f"No skill '{skill}'."})
    deleted = registry.delete(found.skill_id)
    verified = bool(deleted and registry.get(found.skill_id) is None)
    return _json({"ok": verified, "state": "COMPLETED" if verified else "FAILED",
                  "verified": verified, "evidence": "Skill file no longer exists in the registry.",
                  "skill_id": found.skill_id})


@register(
    name="skill_run",
    description=("Run one owner-approved persisted skill through the ordinary permission gate. "
                 "Every step must return verified evidence or the run stops."),
    input_schema={"type": "object", "properties": {"skill": {"type": "string"}},
                  "required": ["skill"]},
    requires_confirmation=True,
)
def skill_run(skill: str) -> str:
    run = manager.run(skill)
    evidence = [{"action": step.action, "ok": step.ok, "attempts": step.attempts,
                 "skipped": step.skipped} for step in run.steps]
    return _json({"ok": run.ok, "state": "COMPLETED" if run.ok else "FAILED",
                  "verified": run.ok, "evidence": evidence, "skill_id": run.skill_id,
                  "name": run.name, "reason": run.reason,
                  "duration_s": round(run.duration_s, 2)})
