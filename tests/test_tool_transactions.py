from __future__ import annotations

from reyes_agent.tool_transactions import ToolTransactionLedger


def test_evidence_is_required_for_verified() -> None:
    ledger = ToolTransactionLedger(max_records=8)
    ledger.planned("t", "1", "click_element", {"target": "Save"})
    assert ledger.finished("t", "1", "clicked").status == "RETURNED_UNVERIFIED"

    ledger.planned("t", "2", "click_element", {"target": "Save"})
    result = '{"ok": true, "verified": true, "evidence": "window changed"}'
    assert ledger.finished("t", "2", result).status == "VERIFIED"


def test_waiting_failure_cancel_and_timeout_are_distinct() -> None:
    ledger = ToolTransactionLedger(max_records=8)
    ledger.planned("t", "w", "delete_file", {"path": "report.txt"})
    waiting = "Queued as request #7 for high-impact confirmation"
    assert ledger.finished("t", "w", waiting).status == "WAITING"

    ledger.planned("t", "f", "click_element", {"target": "Missing"})
    assert ledger.finished("t", "f", "Error: target missing").status == "FAILED"

    ledger.planned("t", "c", "browser_open", {"url": "https://example.com"})
    ledger.cancel_turn("t", reason="owner interrupted")
    assert ledger.get("t", "c").status == "CANCELLED"

    ledger.planned("other", "timeout", "web_search", {"query": "weather"})
    assert ledger.finished("other", "timeout", "Timed out waiting for provider").status == "TIMED_OUT"

    ledger.planned("t", "q", "send_message", {"message": "hello"})
    clarification = "Clarification needed: the intended recipient is missing. Nothing ran."
    assert ledger.finished("t", "q", clarification).status == "WAITING"


def test_ledger_redacts_and_bounds_records() -> None:
    ledger = ToolTransactionLedger(max_records=3)
    for index in range(8):
        ledger.planned(
            "t",
            str(index),
            "type_text",
            {"password": "secret", "text": "hello"},
        )

    snapshot = ledger.snapshot()
    assert len(snapshot) == 3
    assert "secret" not in str(snapshot)
    assert "hello" not in str(snapshot)


def test_unverified_success_claim_is_replaced() -> None:
    ledger = ToolTransactionLedger(max_records=8)
    ledger.planned("t", "1", "click_element", {"target": "Save"})
    ledger.finished("t", "1", "clicked")

    reply = ledger.guard_reply("t", "Done, I saved it.")

    assert reply.startswith("I could not verify that action completed.")
    assert not reply.casefold().startswith("done")


def test_uncertain_hand_action_cannot_repeat_automatically() -> None:
    ledger = ToolTransactionLedger(max_records=8)
    arguments = {"target": "Send"}
    ledger.planned("t", "1", "click_element", arguments)
    ledger.finished("t", "1", "clicked but verification unavailable")

    allowed, reason = ledger.allow_attempt("t", "click_element", arguments)

    assert allowed is False
    assert "uncertain" in reason.casefold()


def test_safe_retryable_failure_has_one_bounded_retry() -> None:
    ledger = ToolTransactionLedger(max_records=8, max_retries=1)
    arguments = {"query": "weather"}
    ledger.planned("t", "1", "web_search", arguments)
    ledger.finished("t", "1", "Error: temporary network timeout")
    assert ledger.allow_attempt("t", "web_search", arguments)[0] is True

    ledger.planned("t", "2", "web_search", arguments)
    ledger.finished("t", "2", "Error: temporary network timeout")
    assert ledger.allow_attempt("t", "web_search", arguments)[0] is False


def test_started_and_reset_are_observable_without_executing_a_tool() -> None:
    ledger = ToolTransactionLedger(max_records=8)
    ledger.planned("t", "1", "web_search", {"query": "weather"})
    assert ledger.started("t", "1").status == "RUNNING"
    assert ledger.snapshot(turn_id="t")[0]["status"] == "RUNNING"
    ledger.reset()
    assert ledger.snapshot() == []
