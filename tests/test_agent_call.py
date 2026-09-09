"""Regression tests for direct one-on-one agent conversation ("Zeno call Kate").

Covers agent_presence's turn-ownership tracking and per-agent history, and
subagents.specialist_conversation_turn's history continuity across calls --
the two pieces that let a summoned specialist own the conversational turn
in its own voice rather than ZENO re-processing and re-speaking it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _clean_presence():
    from reyes_agent import agent_presence

    agent_presence.reset_for_tests()
    yield
    agent_presence.reset_for_tests()


class TestActiveConversationalAgent:
    def test_no_one_owns_the_turn_by_default(self):
        from reyes_agent import agent_presence

        assert agent_presence.get_agent_presence().active_conversational_agent() == ""

    def test_summoning_kate_makes_her_the_active_conversational_agent(self):
        from reyes_agent import agent_presence

        reply, voice = agent_presence.handle_command("Zeno call Kate.")
        assert "KATE" in reply and voice == "kate"
        assert agent_presence.get_agent_presence().active_conversational_agent() == "kate"

    def test_dismissing_kate_returns_ownership_to_zeno(self):
        from reyes_agent import agent_presence

        agent_presence.handle_command("Call Kate.")
        assert agent_presence.get_agent_presence().active_conversational_agent() == "kate"
        agent_presence.handle_command("Kate, you can go.")
        assert agent_presence.get_agent_presence().active_conversational_agent() == ""

    def test_summoning_a_second_agent_hands_ownership_to_the_new_one(self):
        """Matches the master prompt's multi-agent example: Hunter X joining
        while Kate is present makes Hunter X the most recently addressed --
        ZENO (not this module) decides whose specific question to route
        where within a multi-agent session; this module only tracks who was
        addressed last."""
        from reyes_agent import agent_presence

        agent_presence.handle_command("Call Kate.")
        agent_presence.handle_command("Bring in Hunter X.")
        manager = agent_presence.get_agent_presence()
        assert manager.active_conversational_agent() == "hunter_x"
        assert set(manager.active_ids()) == {"kate", "hunter_x"}

    def test_a_stale_pointer_to_a_dismissed_agent_never_silently_routes_turns(self):
        """Defensive: active_conversational_agent must re-check presence,
        not just trust the last-addressed pointer, in case something
        dismisses an agent through a path other than handle_command."""
        from reyes_agent import agent_presence

        manager = agent_presence.get_agent_presence()
        agent_presence.handle_command("Call Kate.")
        manager.dismiss(["kate"])
        assert manager.active_conversational_agent() == ""


class TestPerAgentHistory:
    def test_history_for_returns_the_same_mutable_list_across_calls(self):
        from reyes_agent import agent_presence

        manager = agent_presence.get_agent_presence()
        history = manager.history_for("kate")
        history.append({"role": "user", "content": "hi"})
        assert manager.history_for("kate") == [{"role": "user", "content": "hi"}]

    def test_dismissing_an_agent_discards_its_call_history(self):
        from reyes_agent import agent_presence

        manager = agent_presence.get_agent_presence()
        agent_presence.handle_command("Call Kate.")
        manager.history_for("kate").append({"role": "user", "content": "remember this"})
        agent_presence.handle_command("Kate, standby.")
        assert manager.history_for("kate") == []  # fresh session next time, not a leaked transcript


class TestSpecialistConversationTurn:
    def test_unknown_specialist_reports_the_error_without_raising(self):
        from reyes_agent.tools.subagents import specialist_conversation_turn

        result = specialist_conversation_turn("not_a_real_agent", "hello", history=[])
        assert "No specialist named" in result

    def test_a_second_turn_sees_the_first_turns_conversation(self, monkeypatch):
        """The whole point of passing a persistent history: Kate should not
        have amnesia between consecutive turns of the same call session
        (master prompt s36)."""
        from reyes_agent import provider
        from reyes_agent.provider import AgentTurn
        from reyes_agent.tools.subagents import specialist_conversation_turn

        seen_histories: list[list[dict]] = []

        def fake_run_turn(history, *, system, tools, cancel_check=None):
            seen_histories.append([dict(item) for item in history])
            return AgentTurn(text=f"reply #{len(seen_histories)}")

        monkeypatch.setattr(provider, "run_turn", fake_run_turn)

        history: list[dict] = []
        first = specialist_conversation_turn("kate", "What is a variable?", history=history)
        assert first == "reply #1"
        second = specialist_conversation_turn("kate", "Give me an example.", history=history)
        assert second == "reply #2"

        # The SECOND call's history must include the FIRST turn's user
        # message and Kate's own first reply -- real continuity, not just
        # the new message alone.
        assert seen_histories[1][0] == {"role": "user", "content": "What is a variable?"}
        assert seen_histories[1][1] == {"role": "assistant", "content": "reply #1"}
        assert seen_histories[1][2] == {"role": "user", "content": "Give me an example."}

    def test_delegates_one_shot_call_is_unaffected_by_the_history_parameter(self, monkeypatch):
        """delegate() never passes history= -- confirm its existing one-shot
        behaviour (fresh context every call) is untouched by this change."""
        from reyes_agent import provider
        from reyes_agent.provider import AgentTurn
        from reyes_agent.tools.subagents import delegate

        seen_histories: list[list[dict]] = []

        def fake_run_turn(history, *, system, tools, cancel_check=None):
            seen_histories.append([dict(item) for item in history])
            return AgentTurn(text="done")

        monkeypatch.setattr(provider, "run_turn", fake_run_turn)
        monkeypatch.setattr("reyes_agent.agent_runtime.is_running", lambda: False, raising=False)

        delegate("kate", "first task")
        delegate("kate", "second unrelated task")
        # Each call started from scratch -- no memory of the first task.
        assert len(seen_histories[0]) == 1
        assert len(seen_histories[1]) == 1
        assert seen_histories[1][0]["content"] == "second unrelated task"


def _run_all() -> int:
    import inspect

    failures = 0
    total = 0
    for name, cls in sorted(globals().items()):
        if not (isinstance(cls, type) and name.startswith("Test")):
            continue
        instance = cls()
        for method_name, method in inspect.getmembers(instance, predicate=inspect.ismethod):
            if not method_name.startswith("test_"):
                continue
            total += 1
            try:
                if "monkeypatch" in inspect.signature(method).parameters:
                    print(f"SKIP {name}.{method_name} (needs pytest monkeypatch fixture)")
                    continue
                from reyes_agent import agent_presence
                agent_presence.reset_for_tests()
                method()
                print(f"PASS {name}.{method_name}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"FAIL {name}.{method_name}: {type(exc).__name__}: {exc}")
    print(f"{total - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
