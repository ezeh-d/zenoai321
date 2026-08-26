"""Thin tools exposing the native, lazy Charm Engine to ZENO's shared brain."""

from __future__ import annotations

import json
from typing import Any

from reyes_agent.tools import register


_MODES = [
    "Natural", "Smooth", "Sweet", "Flirty", "Playful", "Funny", "Witty",
    "Romantic", "Confident", "Gentleman", "Cheeky", "Deep", "Serious",
    "Pidgin Smooth",
]
_FEATURES = [
    "reply", "opener", "compliment", "humor", "storytelling", "recovery",
    "after_send", "simulator", "voice_coach",
]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _engine():
    from reyes_agent.charm.engine import get_charm_engine

    return get_charm_engine()


def _conversation(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item).strip())[-20:]
    text = str(value or "").strip()
    return tuple(line.strip() for line in text.splitlines() if line.strip())[-20:]


@register(
    name="charm_reply",
    description=(
        "Draft and rank 1-5 context-aware reply options in a selected Charm mode. "
        "Use for 'give me a smooth reply', 'make this sweeter', 'best reply', or "
        "'give me three options'. This NEVER sends a message; sending always remains "
        "a separate explicit owner action."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "instruction": {"type": "string"},
            "conversation": {"type": "array", "items": {"type": "string"}},
            "mode": {"type": "string", "enum": _MODES},
            "count": {"type": "integer", "minimum": 1, "maximum": 5},
            "intensity": {"type": "integer", "minimum": 0, "maximum": 100},
            "relationship": {"type": "string"},
            "objective": {"type": "string"},
            "include_scores": {"type": "boolean"},
            "session_id": {"type": "string"},
        },
        "required": ["instruction"],
    },
    audit_private=True,
)
def charm_reply(
    instruction: str,
    conversation: list[str] | tuple[str, ...] = (),
    mode: str | None = None,
    count: int = 3,
    intensity: int | None = None,
    relationship: str = "",
    objective: str = "",
    include_scores: bool = True,
    session_id: str = "default",
) -> str:
    result = _engine().reply(
        instruction,
        _conversation(conversation),
        mode=mode,
        count=count,
        intensity=intensity,
        relationship=relationship,
        objective=objective,
        include_scores=include_scores,
        session_id=session_id,
    )
    return _json(result.as_dict())


@register(
    name="charm_analyze",
    description=(
        "Analyze a supplied conversation locally for tone, reciprocity, momentum, "
        "dry replies, unanswered messages, discomfort, and whether to CONTINUE, "
        "WAIT, MATCH, PULL_BACK, or ABORT. Generates no reply and sends nothing."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "conversation": {"type": "array", "items": {"type": "string"}},
            "relationship": {"type": "string"},
            "session_id": {"type": "string"},
        },
        "required": ["conversation"],
    },
    light=True,
    audit_private=True,
)
def charm_analyze(
    conversation: list[str] | tuple[str, ...], relationship: str = "",
    session_id: str = "default",
) -> str:
    return _json(_engine().analyze(
        _conversation(conversation),
        relationship,
        session_id=session_id,
        emit_event=True,
    ).as_dict())


@register(
    name="charm_set_mode",
    description="Set the Charm style and optional intensity for one bounded conversation session.",
    input_schema={
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": _MODES},
            "intensity": {"type": "integer", "minimum": 0, "maximum": 100},
            "session_id": {"type": "string"},
        },
        "required": ["mode"],
    },
)
def charm_set_mode(mode: str, intensity: int | None = None, session_id: str = "default") -> str:
    return _json(_engine().set_mode(session_id, mode, intensity))


@register(
    name="charm_status",
    description="Show the selected Charm mode and bounded session counts; never returns a private transcript.",
    input_schema={
        "type": "object",
        "properties": {"session_id": {"type": "string"}},
    },
    light=True,
)
def charm_status(session_id: str = "default") -> str:
    return _json(_engine().status(session_id))


@register(
    name="charm_feedback",
    description=(
        "Record bounded feedback for a real candidate ID produced in this session. "
        "Does not store the conversation or train an external service."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "candidate_id": {"type": "string"},
            "outcome": {"type": "string"},
            "session_id": {"type": "string"},
        },
        "required": ["candidate_id", "outcome"],
    },
    audit_private=True,
)
def charm_feedback(candidate_id: str, outcome: str, session_id: str = "default") -> str:
    accepted = _engine().feedback(session_id, candidate_id, outcome)
    return _json({
        "accepted": accepted,
        "candidate_id": candidate_id,
        "message": "Feedback recorded." if accepted else "Unknown candidate ID; nothing was stored.",
    })


@register(
    name="charm_coach",
    description=(
        "Use a specific Charm coaching feature: opener, compliment, humor, storytelling, "
        "recovery, after-send review, simulator, or voice coach. Produces advice or drafts "
        "only and never sends or starts another microphone."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "instruction": {"type": "string"},
            "feature": {"type": "string", "enum": _FEATURES},
            "conversation": {"type": "array", "items": {"type": "string"}},
            "mode": {"type": "string", "enum": _MODES},
            "count": {"type": "integer", "minimum": 1, "maximum": 5},
            "intensity": {"type": "integer", "minimum": 0, "maximum": 100},
            "relationship": {"type": "string"},
            "objective": {"type": "string"},
            "session_id": {"type": "string"},
        },
        "required": ["instruction", "feature"],
    },
    audit_private=True,
)
def charm_coach(
    instruction: str,
    feature: str,
    conversation: list[str] | tuple[str, ...] = (),
    mode: str | None = None,
    count: int = 3,
    intensity: int | None = None,
    relationship: str = "",
    objective: str = "",
    session_id: str = "default",
) -> str:
    result = _engine().coach(
        feature,
        instruction,
        _conversation(conversation),
        mode=mode,
        count=count,
        intensity=intensity,
        relationship=relationship,
        objective=objective,
        session_id=session_id,
    )
    return _json(result.as_dict())
