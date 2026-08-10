"""TOSIN entry points for the optional Open Interpreter specialist."""

from __future__ import annotations

import json

from reyes_agent.coding_system import get_interpreter_client
from reyes_agent.tools import register


@register(
    name="coding_inspect",
    description="Ask the sandboxed coding specialist to inspect a repository, diagnose an error, or run a read-only review.",
    input_schema={"type": "object", "properties": {
        "goal": {"type": "string"}, "workspace": {"type": "string"}}, "required": ["goal"]},
)
def coding_inspect(goal: str, workspace: str = "") -> str:
    return json.dumps(get_interpreter_client().run(goal, workspace=workspace or None, read_only=True), default=str)


@register(
    name="coding_execute",
    description="Run a bounded, workspace-confined coding repair through Open Interpreter. This may modify files and requires confirmation.",
    input_schema={"type": "object", "properties": {
        "goal": {"type": "string"}, "workspace": {"type": "string"}}, "required": ["goal"]},
    requires_confirmation=True,
)
def coding_execute(goal: str, workspace: str = "") -> str:
    return json.dumps(get_interpreter_client().run(goal, workspace=workspace or None, read_only=False), default=str)
