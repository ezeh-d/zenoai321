from __future__ import annotations


def test_every_agent_turn_exposes_a_normalized_context_source(monkeypatch) -> None:
    from reyes_agent import agent
    from reyes_agent.turn_context import current_turn_context

    observed = []
    monkeypatch.setattr(agent, "_run_agent_impl", lambda *_args, **_kwargs: observed.append(current_turn_context()))

    agent.run_agent([{"role": "user", "content": "show the panel"}], action_source="panel")

    assert observed[0].source == "panel"
    assert observed[0].is_proactive is False
    assert observed[0].owner_authenticated is False


def test_tool_registry_exposes_proactive_eligibility_without_making_it_default() -> None:
    from reyes_agent.tools import Tool

    safe = Tool("status", "status", {"type": "object"}, lambda: "ok", proactive_allowed=True)
    protected = Tool("send", "send", {"type": "object"}, lambda: "ok", requires_confirmation=True)

    assert safe.metadata()["proactiveAllowed"] is True
    assert protected.metadata()["proactiveAllowed"] is False
    assert protected.metadata()["requiresConfirmation"] is True
