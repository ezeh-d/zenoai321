"""The defensive bridge from the turn loop to the coordinator + ledger.

These assert the wiring records what it should AND that it never raises -- the
whole point is that conversation telemetry can't break a reply.
"""

from __future__ import annotations

import pytest

from reyes_agent.conversation import turn_wiring
from reyes_agent.tool_transactions import get_ledger
from reyes_agent.conversation_coordinator import get_coordinator


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    # Isolated singletons so tests don't bleed into each other or real state.
    from reyes_agent import tool_transactions, conversation_coordinator
    monkeypatch.setattr(tool_transactions, "_ledger",
                        tool_transactions.ToolTransactionLedger())
    monkeypatch.setattr(conversation_coordinator, "_coordinator",
                        conversation_coordinator.ConversationCoordinator())
    yield


def test_begin_opens_a_coordinator_turn():
    turn_wiring.begin("t1", utterance="open notepad", source="local_text")
    assert get_coordinator().turn("t1") is not None


def test_tool_planned_then_finished_records_the_outcome():
    turn_wiring.begin("t2", utterance="delete the file")
    turn_wiring.tool_planned("t2", "c1", "delete_file", {"path": "x.txt"})
    turn_wiring.tool_finished("t2", "c1", "Error: file is missing")
    tx = get_ledger().get("t2", "c1")
    assert tx is not None and tx.status == "FAILED"


def test_finished_classifies_timeout_and_waiting():
    turn_wiring.tool_planned("t3", "a", "web_search", {"q": "weather"})
    turn_wiring.tool_finished("t3", "a", "Timed out waiting for provider")
    assert get_ledger().get("t3", "a").status == "TIMED_OUT"


def test_ledger_never_records_a_secret_argument():
    turn_wiring.tool_planned("t4", "k", "type_text", {"text": "hunter2password"})
    turn_wiring.tool_finished("t4", "k", "typed")
    assert "hunter2password" not in str(get_ledger().snapshot(turn_id="t4"))


def test_guard_reply_blocks_an_unverified_done_claim():
    turn_wiring.tool_planned("t5", "1", "click_element", {"target": "Save"})
    turn_wiring.tool_finished("t5", "1", "clicked")  # no verification evidence
    guarded = turn_wiring.guard_reply("t5", "Done, I saved it.")
    assert guarded != "Done, I saved it."  # rewritten to an honest claim


def test_cancel_marks_the_turn_cancelled():
    turn_wiring.begin("t6", utterance="open chrome")
    turn_wiring.tool_planned("t6", "1", "browser_open", {"url": "https://x.com"})
    turn_wiring.cancel("t6", reason="owner interrupted")
    assert get_ledger().get("t6", "1").status == "CANCELLED"


# --- the contract that matters most: it never raises --------------------
def test_empty_turn_id_is_a_noop():
    turn_wiring.begin("")               # must not raise
    turn_wiring.tool_planned("", "", "x", {})
    turn_wiring.tool_finished("", "", "y")
    turn_wiring.finish("")
    assert turn_wiring.guard_reply("", "text") == "text"


def test_a_broken_ledger_never_breaks_the_turn(monkeypatch):
    from reyes_agent import tool_transactions

    def boom(*a, **k):
        raise RuntimeError("ledger exploded")
    monkeypatch.setattr(tool_transactions, "get_ledger", boom)
    # None of these may raise even though the ledger is broken.
    turn_wiring.tool_planned("t7", "1", "open_app", {"name": "notepad"})
    turn_wiring.tool_finished("t7", "1", "ok")
    assert turn_wiring.guard_reply("t7", "hello") == "hello"


def test_agent_imports_the_wiring():
    # Structural: agent.py must import and reference the wiring at its hooks.
    import reyes_agent.agent as agent
    assert hasattr(agent, "turn_wiring")
