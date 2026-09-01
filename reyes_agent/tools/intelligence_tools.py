"""Agent-facing entry points for ZENO's integrated intelligence layer.

These tools only expose real, bounded services in ``intelligence.py``.  They
do not create a second search engine, mission runtime, or health poller.
"""
from __future__ import annotations

import json

from reyes_agent import intelligence
from reyes_agent.tools import register


@register(
    name="interrupt_work",
    description=("Stop or pause ZENO's active managed work. Use immediately when Divine says stop, wait, "
                 "pause, cancel, or corrects an active command. Completed work is preserved."),
    input_schema={"type": "object", "properties": {
        "action": {"type": "string", "enum": ["cancel", "pause"]},
        "correction": {"type": "string", "description": "Optional replacement intent after cancelling the old action."},
    }, "required": ["action"]},
    light=True,
)
def interrupt_work(action: str, correction: str = "") -> str:
    result = intelligence.get_runtime_control().interrupt(action=action, correction=correction)
    return (f"{result['action'].title()} requested for {len(result['cancelled_operations'])} active operation(s) "
            f"and {result['cancelled_agent_tasks']} specialist task(s). Completed work is preserved.")


@register(
    name="action_history",
    description="Show ZENO's recent factual action history, including whether each action is actually reversible.",
    input_schema={"type": "object", "properties": {"limit": {"type": "integer", "description": "1-100, default 10."}}},
    light=True,
)
def action_history(limit: int = 10) -> str:
    records = intelligence.action_history(limit)
    if not records:
        return "No ZENO actions have been recorded in this session history yet."
    return "\n".join(
        f"{item['id']} — {item['action']} {item['resource'] or ''} — "
        f"{'reversible' if item['reversible'] and not item['undone'] else 'not reversible'} — {item['result']}"
        for item in records
    )


@register(
    name="undo_last_actions",
    description=("Undo the most recent ZENO project-file write(s) only when their recorded before-state and current "
                 "file hash prove it is safe. Never claim external or destructive operations can be undone."),
    input_schema={"type": "object", "properties": {"count": {"type": "integer", "description": "1-10, default 1."}}},
    requires_confirmation=True,
)
def undo_last_actions(count: int = 1) -> str:
    result = intelligence.undo_last(count)
    if result["ok"]:
        return result["message"]
    reasons = "; ".join(item["reason"] for item in result.get("failures", []))
    return result["message"] + (f" {reasons}" if reasons else "")


@register(
    name="current_situation",
    description=("Get ZENO's permitted current context: active app/window when observable, current task/step, mission, "
                 "participants, recent command and active operations. Do not guess an ambiguous target."),
    input_schema={"type": "object", "properties": {}},
    light=True,
)
def current_situation() -> str:
    state = intelligence.situation()
    try:
        from reyes_agent import anticipation, awareness

        prediction = anticipation.predict_app()
        state = {
            **state,
            "observed": awareness.observe().as_dict(),
            "anticipation": {
                "readiness": anticipation.readiness(),
                "current_prediction": prediction.as_dict() if prediction else None,
            },
        }
    except Exception as exc:  # noqa: BLE001 -- unavailable context is explicit
        state = {**state, "observed": None, "anticipation": None,
                 "context_status": f"unavailable: {type(exc).__name__}"}
    return json.dumps(state, default=str)


@register(
    name="universal_search",
    description=("Search permitted ZENO memories, notes, workflow names and recorded task history together. "
                 "Each result states its source; ranking uses actual text match and recency, not invented semantic scores."),
    input_schema={"type": "object", "properties": {
        "query": {"type": "string"}, "limit": {"type": "integer", "description": "1-20, default 8."},
    }, "required": ["query"]},
    light=True,
)
def universal_search(query: str, limit: int = 8) -> str:
    results = intelligence.universal_search(query, limit=limit)
    if not results:
        return f"No permitted ZENO records matched '{query}'."
    return "\n".join(
        f"[{item['source']}] {item['label']} — {item.get('snippet', '')}" for item in results
    )


@register(
    name="remember_relationship",
    description=("Save an explicit owner-confirmed relationship in ZENO's personal knowledge graph, for example "
                 "Divine owns ZENO or STARK is the security agent. This supplements, never replaces, existing memory/notes."),
    input_schema={"type": "object", "properties": {
        "source": {"type": "string"}, "relation": {"type": "string"}, "target": {"type": "string"},
        "evidence": {"type": "string", "description": "Short owner-confirmed basis; do not invent one."},
    }, "required": ["source", "relation", "target"]},
    requires_confirmation=True,
)
def remember_relationship(source: str, relation: str, target: str, evidence: str = "owner-confirmed") -> str:
    item = intelligence.add_relationship(source, relation, target, evidence=evidence)
    return f"Saved relationship {item['id']}: {item['source']} — {item['relation']} → {item['target']}."


@register(
    name="search_relationships",
    description="Search the explicit personal knowledge graph and show the source, relation, target and evidence recorded for each result.",
    input_schema={"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}},
    light=True,
)
def search_relationships(query: str = "", limit: int = 20) -> str:
    records = intelligence.relationships(query, limit=limit)
    if not records:
        return "No matching explicit personal-knowledge relationships."
    return "\n".join(f"{item['id']}: {item['source']} — {item['relation']} → {item['target']} ({item['evidence']})" for item in records)


@register(
    name="forget_relationship",
    description="Delete an incorrect explicit personal knowledge-graph relationship by its ID. Requires confirmation because it removes remembered context.",
    input_schema={"type": "object", "properties": {"relationship_id": {"type": "string"}}, "required": ["relationship_id"]},
    requires_confirmation=True,
)
def forget_relationship(relationship_id: str) -> str:
    return "Deleted relationship." if intelligence.remove_relationship(relationship_id) else "No relationship with that ID exists."


@register(
    name="resolve_time",
    description="Resolve a supported natural-time expression such as yesterday, tomorrow, last Monday, or three hours from now with its exact timezone-aware timestamp.",
    input_schema={"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]},
    light=True,
)
def resolve_time(expression: str) -> str:
    result = intelligence.resolve_time(expression)
    return json.dumps(result)


@register(
    name="resolve_context_reference",
    description=("Resolve 'it', 'that app', 'this task', or a similar pronoun only when ZENO's observable "
                 "current situation contains one unique target. This never grants permission for a risky action."),
    input_schema={"type": "object", "properties": {
        "reference": {"type": "string"},
        "risk": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
    }, "required": ["reference"]},
    light=True,
)
def resolve_context_reference(reference: str, risk: str = "low") -> str:
    return json.dumps(intelligence.resolve_reference(reference, risk=risk))


@register(
    name="simulate_plan",
    description=("Show a non-executing plan preview for complex/high-risk work. It must be clearly identified as a simulation "
                 "and never changes files, browsers, desktop state, or missions."),
    input_schema={"type": "object", "properties": {
        "goal": {"type": "string"}, "steps": {"type": "array", "items": {"type": "string"}},
        "risk": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
        "files": {"type": "array", "items": {"type": "string"}},
    }, "required": ["goal", "steps"]},
    light=True,
)
def simulate_plan(goal: str, steps: list[str], risk: str = "medium", files: list[str] | None = None) -> str:
    return json.dumps(intelligence.simulate_plan(goal, steps, risk=risk, files=files), default=str)


@register(
    name="health_center",
    description=("Run ZENO's on-demand Health Center. It reports only real status from existing subsystems and may perform "
                 "no disruptive recovery unless the owner explicitly asks."),
    input_schema={"type": "object", "properties": {}},
    light=True,
)
def health_center() -> str:
    return json.dumps(intelligence.health(), default=str)


@register(
    name="capability_status",
    description="Check whether a ZENO capability is actually available, degraded, disabled, not configured, unavailable, partial, or in development before promising it.",
    input_schema={"type": "object", "properties": {"capability": {"type": "string", "description": "Optional capability name."}}},
    light=True,
)
def capability_status(capability: str = "") -> str:
    if capability.strip():
        try:
            from reyes_agent.workspace import get_workspace_service

            dynamic = get_workspace_service().health.capability_summary(capability)
            if dynamic.get("tools"):
                return json.dumps(dynamic)
        except Exception:
            pass
        result = intelligence.capability(capability)
        return json.dumps(result or {"capability": capability, "status": "UNAVAILABLE", "detail": "No registered capability by that name."})
    return json.dumps(intelligence.capabilities())


@register(
    name="save_mission_runtime_state",
    description=("Save observable state for an active mission so it can resume without repeating completed actions: goal, plan, "
                 "completed/pending steps, files, agents, decisions, blockers and verification evidence."),
    input_schema={"type": "object", "properties": {
        "mission_id": {"type": "integer"}, "goal": {"type": "string"},
        "plan": {"type": "array", "items": {"type": "string"}},
        "completed": {"type": "array", "items": {"type": "string"}},
        "pending": {"type": "array", "items": {"type": "string"}},
        "files": {"type": "array", "items": {"type": "string"}},
        "agents": {"type": "array", "items": {"type": "string"}},
        "decisions": {"type": "array", "items": {"type": "string"}},
        "errors": {"type": "array", "items": {"type": "string"}},
        "verification": {"type": "array", "items": {"type": "string"}},
    }, "required": ["mission_id"]},
)
def save_mission_runtime_state(mission_id: int, **state) -> str:
    saved = intelligence.persist_mission_state(mission_id, **state)
    return f"Saved resumable state for mission #{mission_id}: {len(saved.get('completed', []))} completed, {len(saved.get('pending', []))} pending step(s)."


@register(
    name="load_mission_runtime_state",
    description="Load the saved observable state of an unfinished mission before resuming it, so ZENO does not blindly repeat completed work.",
    input_schema={"type": "object", "properties": {"mission_id": {"type": "integer"}}, "required": ["mission_id"]},
)
def load_mission_runtime_state(mission_id: int) -> str:
    result = intelligence.load_mission_state(mission_id)
    return json.dumps(result) if result else f"Mission #{mission_id} has no saved resumable runtime state."
