"""Behaviour tests for ZENO's small, local humour policy.

Run: `.venv/Scripts/python.exe tests/test_humour.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_default_and_fast_joke_route() -> None:
    from reyes_agent import cognition, humour

    humour.reset()
    decision = cognition.route("ZENO, tell me a joke.")
    assert humour.mode() == humour.HUMOUR_NORMAL
    assert decision.path == cognition.FAST
    assert decision.max_tool_rounds == cognition.FAST_ROUNDS
    assert "short, original conversational joke" in humour.directive("ZENO, tell me a joke.", decision)


def test_another_and_missed_joke_keep_context_without_long_term_memory() -> None:
    from reyes_agent import cognition, humour

    humour.reset()
    humour.record_reply("Tell me a joke", "A byte walked into a bar.")
    another = humour.directive("Another one.", cognition.route("Another one."))
    retry = humour.directive("That one no funny.", cognition.route("That one no funny."))
    assert "different short joke immediately" in another
    assert "Avoid reusing" in another
    assert "acknowledge" in retry and "different short joke" in retry
    assert humour.status()["recent_jokes"] == 1


def test_roast_stays_light_and_serious_mood_disables_humour() -> None:
    from reyes_agent import cognition, humour

    humour.reset()
    roast = humour.directive("ZENO, roast me small.", cognition.route("ZENO, roast me small."))
    assert "light, affectionate roast" in roast
    assert "Never insult" in roast
    for message in ("I'm dealing with something serious.", "I am having a medical emergency."):
        assert humour.directive(message, cognition.route(message)) == ""


def test_pidgin_reaction_is_optional_and_cooldown_limited() -> None:
    from reyes_agent import cognition, humour

    humour.reset()
    message = "This code don break again."
    decision = cognition.route(message)
    first = humour.directive(message, decision, now=1000.0)
    assert "Match Pidgin only if the user used it" in first
    assert humour.directive(message, decision, now=1001.0) == ""
    humour.set_mode(humour.HUMOUR_LOW)
    assert humour.directive(message, decision, now=2000.0) == ""


def test_recent_history_is_bounded_and_not_permanent() -> None:
    from reyes_agent import humour

    humour.reset()
    for index in range(12):
        humour.record_reply("Tell me a joke", f"joke {index}")
    details = humour.status()
    assert details["recent_jokes"] == 8
    assert details["capacity"] == 8
    assert "Living Memory" in details["policy"]


def test_agent_uses_the_existing_fast_turn_with_the_humour_nudge() -> None:
    """A joke must not add a second model call, worker, or tool round."""
    from reyes_agent import agent, humour
    from reyes_agent.provider import AgentTurn

    humour.reset()
    captured: list[str] = []
    original_run_turn = agent.run_turn
    original_tools = agent.tool_definitions

    def fake_turn(_history, *, system, tools, on_text, cancel_check, task_kind):
        captured.append(system)
        assert task_kind == "general"
        assert tools == []
        on_text("A clean joke.")
        return AgentTurn(text="A clean joke.")

    try:
        agent.run_turn = fake_turn
        agent.tool_definitions = lambda **_kwargs: []
        history = [{"role": "user", "content": "ZENO, tell me a joke."}]
        agent.run_agent(history)
    finally:
        agent.run_turn = original_run_turn
        agent.tool_definitions = original_tools

    assert len(captured) == 1
    assert "short, original conversational joke" in captured[0]
    assert history[-1]["content"] == "A clean joke."
    assert humour.status()["recent_jokes"] == 1


def test_agent_uses_the_existing_single_turn_for_ragebait() -> None:
    """Ragebait is a directive inside the current turn, never a second call."""
    from reyes_agent import agent, ragebait
    from reyes_agent.provider import AgentTurn

    ragebait.reset()
    ragebait.handle("ZENO, ragebait me.")
    captured: list[str] = []
    original_run_turn = agent.run_turn
    original_tools = agent.tool_definitions

    def fake_turn(_history, *, system, tools, on_text, cancel_check, task_kind):
        captured.append(system)
        assert tools == []
        on_text("That confidence needs a seatbelt.")
        return AgentTurn(text="That confidence needs a seatbelt.")

    try:
        agent.run_turn = fake_turn
        agent.tool_definitions = lambda **_kwargs: []
        history = [{"role": "user", "content": "You cannot ragebait me."}]
        agent.run_agent(history)
    finally:
        agent.run_turn = original_run_turn
        agent.tool_definitions = original_tools

    assert len(captured) == 1
    assert "Ragebait" in captured[0]


def test_ragebait_reply_history_records_non_joke_banter() -> None:
    from reyes_agent import humour, ragebait

    ragebait.reset()
    ragebait.handle("ragebait me")
    humour.record_reply("You cannot ragebait me", "That confidence needs a seatbelt.")
    assert ragebait.status()["recent_lines"] == 1


def _run_all() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"PASS: {len(tests)}/{len(tests)} humour behaviour tests")


if __name__ == "__main__":
    _run_all()
