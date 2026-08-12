"""Serious mode, as things ZENO can be asked for."""

from __future__ import annotations

import json

from reyes_agent.tools import register


@register(name="set_serious_mode",
          description=("Turn ZENO's serious mode (Ultron) on or off. Use for "
                       "'activate Ultron', 'serious mode', 'go serious', "
                       "'return to ZENO', 'stand down', 'normal mode'. ZENO "
                       "remains the master assistant either way -- this "
                       "changes how he reasons and speaks, never what he is "
                       "permitted to do."),
          input_schema={"type": "object", "properties": {
              "mode": {"type": "string", "enum": ["ULTRON", "NORMAL"]}},
              "required": ["mode"]})
def set_serious_mode(mode: str) -> str:
    from reyes_agent import modes

    return json.dumps(modes.set_mode(mode, source="voice"), default=str)


@register(name="assistant_mode_status",
          description=("Report the current operating mode and live runtime "
                       "state: active agent, task, tool, voice state. Use for "
                       "'what's your status', 'show the current mission', "
                       "'who is working'."),
          input_schema={"type": "object", "properties": {}})
def assistant_mode_status() -> str:
    from reyes_agent import modes

    return json.dumps({**modes.status(),
                       "runtime": modes.runtime_state().as_dict()}, default=str)
