"""Defense / presentation mode as a ZENO tool -- one command to get demo-ready."""

from __future__ import annotations

import json

from reyes_agent.tools import register


@register(
    name="defense_mode",
    description="Prepare ZENO for a live SCHOOL DEFENSE / DEMO / PRESENTATION "
                "(this is NOT about security or lockdown). ALWAYS call this tool "
                "for 'defense mode', 'presentation mode', 'defence mode', 'demo "
                "mode', 'get ready for my defense/demo' -- do not just role-play a "
                "reply. Turning it ON warms the brain so the first question is "
                "fast, enters presentation conversation so lecturers/guests can "
                "talk (the owner can still interrupt), and returns a readiness "
                "check (mic/STT/TTS/tools/AI/agents). Low-risk; runs immediately.",
    input_schema={"type": "object", "properties": {
        "action": {"type": "string", "enum": ["on", "off", "status"],
                   "description": "on = activate, off = deactivate, status = readiness only."},
    }, "required": []},
)
def defense_mode(action: str = "on") -> str:
    from reyes_agent import defense_mode as dm

    action = str(action or "on").strip().lower()
    if action in ("off", "deactivate", "stop", "exit", "normal"):
        return json.dumps(dm.deactivate(source="voice"), default=str)
    if action in ("status", "check", "ready", "readiness"):
        return json.dumps({"defense_mode": dm.is_active(), "readiness": dm.readiness()},
                          default=str)
    return json.dumps(dm.activate(source="voice"), default=str)
