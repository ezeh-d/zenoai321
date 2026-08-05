"""Agent-facing entry points for explicit workflow teaching and replay."""

from __future__ import annotations

from reyes_agent.tools import register
from reyes_agent.workflow_engine import get_workflow_engine


@register(
    name="workflow_teach",
    description=(
        "Control ZENO's owner-demonstrated workflow learning. Use action=start "
        "when the owner says 'learn/show you how I do this'; action=stop when "
        "they say 'stop learning'; then ask for a name and use review/save. "
        "Teaching records only replayable structure, never typed text, passwords, "
        "clipboard contents, or cookies."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["start", "pause", "resume", "stop", "review", "save", "discard", "status", "list"]},
            "name": {"type": "string", "description": "Required to save a reviewed workflow."},
        },
        "required": ["action"],
    },
)
def workflow_teach(action: str, name: str = "") -> str:
    engine = get_workflow_engine()
    operation = (action or "").strip().lower()
    if operation == "start":
        return engine.start_teaching()
    if operation == "pause":
        return engine.pause_teaching()
    if operation == "resume":
        return engine.resume_teaching()
    if operation == "stop":
        return engine.stop_teaching()
    if operation == "review":
        return engine.review()
    if operation == "save":
        return engine.save(name)
    if operation == "discard":
        return engine.discard_teaching()
    if operation == "status":
        status = engine.status()
        return f"Workflow mode: {status['mode']}. Recorded steps: {status['draft_steps']}. {status.get('prompt', '')}".strip()
    if operation == "list":
        workflows = engine.list_workflows()
        return "No saved workflows." if not workflows else "\n".join(
            f"- {item['name']} ({item['steps']} step(s), id {item['id']})" for item in workflows
        )
    return "Unknown workflow teaching action."


@register(
    name="workflow_run",
    description=(
        "Run, resume, pause, or cancel a named owner-approved workflow. Use "
        "this when the owner asks ZENO to repeat a task they previously taught, "
        "for example 'prepare the morning report'. If it reports that confirmation "
        "is needed, ask the owner and then call workflow_confirm only after a clear yes."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["start", "resume", "pause", "cancel"]},
            "name": {"type": "string", "description": "Saved workflow name, required except while pausing/cancelling the active run."},
        },
        "required": ["action"],
    },
)
def workflow_run(action: str, name: str = "") -> str:
    engine = get_workflow_engine()
    operation = (action or "").strip().lower()
    if operation == "start":
        return engine.start_run(name)
    if operation == "resume":
        return engine.resume_run(name)
    if operation == "pause":
        return engine.pause_run()
    if operation == "cancel":
        return engine.cancel_run()
    return "Unknown workflow run action."


@register(
    name="workflow_confirm",
    description=(
        "Confirm a workflow run that explicitly reported a permission requirement. "
        "Call only after the owner clearly approves that specific replay."
    ),
    input_schema={
        "type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]
    },
    requires_confirmation=True,
)
def workflow_confirm(name: str) -> str:
    return get_workflow_engine().confirm_run(name)
