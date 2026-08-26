from __future__ import annotations

import json

from reyes_agent.routing import capability
from reyes_agent.tools import TOOLS, group_of, run_tool, tool_definitions


CHARM_TOOLS = {
    "charm_reply",
    "charm_analyze",
    "charm_set_mode",
    "charm_status",
    "charm_feedback",
    "charm_coach",
}


def test_charm_tools_are_registered_in_existing_registry() -> None:
    assert CHARM_TOOLS <= set(TOOLS)
    assert {group_of(name) for name in CHARM_TOOLS} == {"charm"}


def test_capability_router_exposes_charm_only_for_relevant_request() -> None:
    capability.clear_context()
    route = capability.tools_for("Give me three smooth replies that don't sound desperate")
    assert route.capabilities[0] == "charm"
    assert {"charm_reply", "charm_analyze"} <= set(route.tools)
    assert route.exposed <= 10

    capability.clear_context()
    ordinary = capability.tools_for("smooth the orb animation")
    assert "charm" not in ordinary.capabilities
    assert not (CHARM_TOOLS & set(ordinary.tools))


def test_charm_draft_wording_does_not_expose_message_transport_to_agent() -> None:
    route = capability.tools_for("Give me a smooth reply I can send her")
    available = {item["name"] for item in tool_definitions(groups={"charm"})}
    exposed_to_agent = set(route.tools) & available
    assert "charm_reply" in exposed_to_agent
    assert "send_message" not in exposed_to_agent


def test_charm_reply_tool_uses_engine_but_never_a_sending_tool(monkeypatch) -> None:
    from reyes_agent.tools import charm_tools

    calls: list[dict] = []

    class FakeResult:
        def as_dict(self):
            return {"generated": True, "best": {"text": "A contextual draft"}}

    class FakeEngine:
        def reply(self, *args, **kwargs):
            calls.append({"args": args, "kwargs": kwargs})
            return FakeResult()

    monkeypatch.setattr(charm_tools, "_engine", lambda: FakeEngine())
    result = json.loads(run_tool("charm_reply", {
        "instruction": "Give me a natural reply",
        "conversation": ["Them: The meeting went well"],
        "count": 1,
        "session_id": "tool-test",
    }))

    assert result["best"]["text"] == "A contextual draft"
    assert len(calls) == 1
    assert calls[0]["kwargs"]["session_id"] == "tool-test"
    assert all("send" not in name for name in CHARM_TOOLS)


def test_agent_fast_path_keeps_charm_tools_for_a_charm_command(monkeypatch) -> None:
    from reyes_agent import agent
    from reyes_agent.provider import AgentTurn

    captured: list[set[str]] = []

    def fake_turn(_history, *, system, tools, on_text, cancel_check, task_kind):
        captured.append({item["name"] for item in tools})
        on_text("Here are the options.")
        return AgentTurn(text="Here are the options.")

    monkeypatch.setattr(agent, "run_turn", fake_turn)
    history = [{"role": "user", "content": "Give me a smooth reply"}]
    agent.run_agent(history)

    assert len(captured) == 1
    assert "charm_reply" in captured[0]
    assert history[-1]["content"] == "Here are the options."


def test_charm_import_has_no_voice_or_frontend_runtime_dependency() -> None:
    default_definitions = {item["name"] for item in tool_definitions()}
    charm_definitions = {item["name"] for item in tool_definitions(groups={"charm"})}
    assert not (CHARM_TOOLS & default_definitions)
    assert CHARM_TOOLS <= charm_definitions
    for tool in CHARM_TOOLS:
        module = TOOLS[tool].func.__module__
        assert module == "reyes_agent.tools.charm_tools"


def test_tool_audit_and_event_envelope_redact_private_charm_content(monkeypatch) -> None:
    from reyes_agent import audit, event_bus, intelligence

    captured: list[object] = []
    monkeypatch.setattr(audit, "log", lambda *args, **kwargs: captured.append((args, kwargs)))
    monkeypatch.setattr(
        event_bus,
        "publish",
        lambda *args, **kwargs: captured.append((args, kwargs)),
    )
    monkeypatch.setattr(
        intelligence,
        "record_tool_execution",
        lambda *args, **kwargs: captured.append((args, kwargs)),
    )
    private_phrase = "unique private conversation phrase 84721"
    output = run_tool("charm_analyze", {
        "conversation": [f"Them: {private_phrase}"],
        "relationship": "private friendship",
    })

    assert "recommendation" in output
    persisted = json.dumps(captured, default=str).casefold()
    assert private_phrase not in persisted
    assert "private friendship" not in persisted
    assert "private_content_redacted" in persisted
