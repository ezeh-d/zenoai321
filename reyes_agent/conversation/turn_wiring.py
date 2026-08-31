"""Defensive bridge from the turn loop to the conversation coordinator and the
tool-transaction ledger.

agent.py calls these at four points -- turn start, before a tool runs, after it
returns, and turn end -- so ZENO gains correlated tool-transaction tracking,
honest verification and bounded per-session turn context WITHOUT agent.py taking
on that logic or a hard dependency. Every function swallows its own errors:
wiring conversation telemetry must never be the reason a reply fails.

This does not replace conversation_state (it drives the coordinator with
manage_lifecycle=False so the existing state machine stays the single owner of
SPEAKING/LISTENING). It projects context alongside it.
"""

from __future__ import annotations

from typing import Any


def begin(turn_id: str, *, source: str = "local_text", utterance: str = "",
          owner: bool = True) -> None:
    """Open a coordinator turn. No-op without a turn_id, or on any error."""
    if not turn_id:
        return
    try:
        from reyes_agent.conversation_coordinator import get_coordinator, session_key
        get_coordinator().begin_turn(
            turn_id,
            session_key=session_key(source=source, owner=owner),
            source=source, utterance=str(utterance or "")[:400],
            owner_authenticated=bool(owner), manage_lifecycle=False)
    except Exception:  # noqa: BLE001
        pass


def tool_planned(turn_id: str, call_id: str, tool: str,
                 arguments: dict[str, Any] | None) -> None:
    """Record that a tool is about to run (privacy-safe input in the ledger)."""
    if not turn_id or not call_id:
        return
    try:
        from reyes_agent.tool_transactions import get_ledger
        get_ledger().planned(turn_id, call_id, str(tool or ""),
                             arguments if isinstance(arguments, dict) else {})
    except Exception:  # noqa: BLE001
        pass


def tool_finished(turn_id: str, call_id: str, result: Any) -> None:
    """Record a tool's outcome (verified/failed/timed_out/cancelled) and mirror
    a VERIFIED result into the coordinator's context."""
    if not turn_id or not call_id:
        return
    try:
        from reyes_agent.tool_transactions import get_ledger
        tx = get_ledger().finished(turn_id, call_id, result)
    except Exception:  # noqa: BLE001
        return
    try:
        from reyes_agent.conversation_coordinator import get_coordinator
        get_coordinator().record_tool_result(
            turn_id, tool=getattr(tx, "tool", ""),
            outcome=getattr(tx, "status", ""), evidence=getattr(tx, "evidence", ""))
    except Exception:  # noqa: BLE001
        pass


def guard_reply(turn_id: str, text: str) -> str:
    """Refuse an unverified 'done' claim. Returns text unchanged on any error,
    so it can wrap the final reply without risk (#18 honest confidence)."""
    if not turn_id or not text:
        return text
    try:
        from reyes_agent.tool_transactions import get_ledger
        return get_ledger().guard_reply(turn_id, text)
    except Exception:  # noqa: BLE001
        return text


def finish(turn_id: str) -> None:
    """Close the coordinator turn."""
    if not turn_id:
        return
    try:
        from reyes_agent.conversation_coordinator import get_coordinator
        get_coordinator().finish_turn(turn_id)
    except Exception:  # noqa: BLE001
        pass


def cancel(turn_id: str, *, reason: str = "") -> None:
    """Mark the turn cancelled in both the coordinator and the ledger (#19)."""
    if not turn_id:
        return
    try:
        from reyes_agent.conversation_coordinator import get_coordinator
        get_coordinator().cancel_turn(turn_id, reason=reason)
    except Exception:  # noqa: BLE001
        pass
    try:
        from reyes_agent.tool_transactions import get_ledger
        get_ledger().cancel_turn(turn_id, reason=reason)
    except Exception:  # noqa: BLE001
        pass
