"""Panel Request API, exposed as a tool -- lets a summoned specialist ask
for a workspace through the one authoritative Panel Manager (master prompt
s62-64) instead of inventing its own window. Agent identity is inferred
from the call stack (subagents._active_specialist), never trusted from a
model-supplied parameter, so a specialist cannot claim to be a different
agent and borrow its panel ownership.
"""

from __future__ import annotations

from reyes_agent import panels
from reyes_agent.tools import register


@register(
    name="request_panel",
    description=(
        "Ask ZENO's Panel Manager to open/focus a workspace useful for the CURRENT task -- e.g. requesting the Files "
        "panel to show a document, or the browser panel while researching. Only request a panel when it materially "
        "helps the task; a normal reply needs no panel. Use teaching_board for the Teaching Whiteboard specifically -- "
        "that already opens it. panel_type must be a registered panel (see the panel registry)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "panel_type": {"type": "string", "description": "e.g. 'files', 'browser', 'security', 'work', 'notifications'."},
            "reason": {"type": "string", "description": "One short phrase: why this panel helps right now."},
        },
        "required": ["panel_type"],
    },
    light=True,
)
def request_panel(panel_type: str, reason: str = "") -> str:
    from reyes_agent.tools.subagents import _active_specialist

    agent = _active_specialist() or "zeno"
    result = panels.request_panel(agent, panel_type, reason=reason)
    if not result.get("granted"):
        return result.get("reason", "Could not open that panel.")
    return f"{result['definition']['title']} is open."
