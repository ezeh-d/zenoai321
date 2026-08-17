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


@register(name="learn_my_voice",
          description=("Learn the owner's voice so ZENO can tell him from "
                       "other people in the room. Listens through whichever "
                       "microphone is live and collects several spoken "
                       "recordings. Use for 'learn my voice', 'enrol my "
                       "voice', 'know my voice'."),
          input_schema={"type": "object", "properties": {}})
def learn_my_voice() -> str:
    from reyes_agent.identity.speaker.capture import enrol_from_live_microphone

    return json.dumps(enrol_from_live_microphone(), default=str)


@register(name="voice_profile_status",
          description="Whether ZENO has learned the owner's voice yet.",
          input_schema={"type": "object", "properties": {}})
def voice_profile_status() -> str:
    from reyes_agent.identity.speaker.capture import status

    return json.dumps(status(), default=str)
