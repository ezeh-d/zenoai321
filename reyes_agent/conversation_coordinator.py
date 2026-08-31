"""Bounded conversation context projected over ZENO's existing authorities.

This module does not execute tools, store provider history, decide wake-word
state, or replace :mod:`conversation_state`.  It correlates the small amount
of operational context those authorities need to share across local, voice and
paired-phone turns.
"""

from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from typing import Any


_CANCEL_PHRASE = re.compile(
    r"^\s*(?:cancel|stop|never\s*mind|nevermind|forget\s+it|leave\s+it)\b",
    re.I,
)


def _bounded(value: object, limit: int) -> str:
    return str(value or "").strip()[: max(1, int(limit))]


def _context_key(value: object) -> str:
    return _bounded(value or "desktop-owner", 160) or "desktop-owner"


def session_key(*, source: str, device_id: str = "", owner: bool = True) -> str:
    """Return a deterministic isolation key; this is not authentication."""

    kind = str(source or "local_text").casefold()
    if kind == "paired_phone":
        return f"phone:{_bounded(device_id or 'unknown', 80)}"
    if kind == "voice" and not owner:
        return f"guest-voice:{_bounded(device_id or 'local', 80)}"
    return "desktop-owner"


@dataclass
class PendingClarification:
    original_utterance: str
    question: str
    missing_field: str
    owner_authenticated: bool
    created_at: float


@dataclass
class TurnContext:
    turn_id: str
    session_key: str
    source: str
    owner_authenticated: bool
    utterance: str
    normalized_utterance: str
    capabilities: tuple[str, ...] = ()
    route_confidence: str = ""
    active_surface: str = ""
    references: dict[str, str] = field(default_factory=dict)
    pending_question: str = ""
    last_verified_outcome: str = ""
    status: str = "ACTIVE"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    manage_lifecycle: bool = True


@dataclass
class SessionContext:
    session_key: str
    active_turn_id: str = ""
    last_capabilities: tuple[str, ...] = ()
    active_surface: str = ""
    references: dict[str, str] = field(default_factory=dict)
    pending_question: str = ""
    pending: PendingClarification | None = None
    last_verified_outcome: str = ""
    updated_at: float = field(default_factory=time.time)


class ConversationCoordinator:
    """Thread-safe bounded projection of current conversation operations."""

    def __init__(
        self,
        *,
        max_sessions: int = 32,
        max_turns: int = 128,
        max_references: int = 12,
        value_limit: int = 240,
        clarification_ttl_s: float = 120.0,
    ) -> None:
        self.max_sessions = max(1, int(max_sessions))
        self.max_turns = max(1, int(max_turns))
        self.max_references = max(1, int(max_references))
        self.value_limit = max(24, int(value_limit))
        self.clarification_ttl_s = max(1.0, float(clarification_ttl_s))
        self._lock = threading.RLock()
        self._sessions: OrderedDict[str, SessionContext] = OrderedDict()
        self._turns: OrderedDict[str, TurnContext] = OrderedDict()

    def _now(self) -> float:
        return time.time()

    def _session(self, key: str, *, create: bool = False) -> SessionContext | None:
        normalized = _context_key(key)
        item = self._sessions.get(normalized)
        if item is None and create:
            item = SessionContext(session_key=normalized)
            self._sessions[normalized] = item
        if item is not None:
            self._sessions.move_to_end(normalized)
        while len(self._sessions) > self.max_sessions:
            self._sessions.popitem(last=False)
        return item

    def _trim_turns(self) -> None:
        while len(self._turns) > self.max_turns:
            self._turns.popitem(last=False)

    def _publish(self, turn: TurnContext, state: str) -> None:
        payload = {
            "turn_id": turn.turn_id,
            "session_key": turn.session_key,
            "state": _bounded(state, 40),
            "source": turn.source,
            "status": turn.status,
            "active_surface": turn.active_surface,
        }
        try:
            from reyes_agent import event_bus

            event_bus.publish(
                "conversation.context.changed",
                payload,
                source="conversation_coordinator",
                correlation_id=turn.turn_id,
            )
        except Exception:  # noqa: BLE001 -- projection never blocks a turn
            pass

    def _project(self, turn: TurnContext, state: str) -> None:
        try:
            from reyes_agent.unified_session import get_session_state

            get_session_state().update(
                source="conversation_coordinator",
                current_task={"turn_id": turn.turn_id, "state": state},
            )
        except Exception:  # noqa: BLE001 -- projection never becomes authority
            pass
        self._publish(turn, state)

    def begin_turn(
        self,
        turn_id: str,
        *,
        session_key: str,
        source: str,
        utterance: str,
        owner_authenticated: bool,
        manage_lifecycle: bool = True,
    ) -> str:
        identifier = _bounded(turn_id, 160)
        if not identifier:
            raise ValueError("turn_id is required")
        key = _context_key(session_key)
        now = self._now()
        with self._lock:
            session = self._session(key, create=True)
            assert session is not None
            previous = self._turns.get(session.active_turn_id)
            if previous is not None and previous.turn_id != identifier:
                previous.status = "SUPERSEDED"
                previous.updated_at = now

            raw_utterance = _bounded(utterance, self.value_limit * 4)
            turn = TurnContext(
                turn_id=identifier,
                session_key=key,
                source=_bounded(source or "unknown", 80),
                owner_authenticated=bool(owner_authenticated),
                utterance=raw_utterance,
                normalized_utterance=" ".join(raw_utterance.casefold().split()),
                created_at=now,
                updated_at=now,
                manage_lifecycle=bool(manage_lifecycle),
            )
            self._turns[identifier] = turn
            self._turns.move_to_end(identifier)
            self._trim_turns()
            session.active_turn_id = identifier
            session.updated_at = now

        if manage_lifecycle:
            try:
                from reyes_agent import conversation_state

                conversation_state.begin_turn(identifier)
            except Exception:  # noqa: BLE001 -- existing authority owns errors
                pass
        self._project(turn, "ACTIVE")
        return identifier

    def turn(self, turn_id: str) -> TurnContext | None:
        with self._lock:
            item = self._turns.get(str(turn_id or ""))
            if item is None:
                return None
            return replace(item, references=dict(item.references))

    def record_route(
        self, turn_id: str, capabilities: tuple[str, ...], confidence: str
    ) -> None:
        now = self._now()
        with self._lock:
            turn = self._turns.get(str(turn_id or ""))
            if turn is None:
                return
            selected = tuple(_bounded(value, 40) for value in capabilities[:3] if value)
            surface = next((value for value in selected if value in {"browser", "desktop"}), "")
            turn.capabilities = selected
            turn.route_confidence = _bounded(confidence, 32)
            if surface:
                turn.active_surface = surface
            turn.updated_at = now
            session = self._session(turn.session_key)
            if session is not None:
                session.last_capabilities = selected
                if surface:
                    session.active_surface = surface
                session.updated_at = now
        self._project(turn, "ROUTED")

    def record_reference(self, turn_id: str, name: str, value: str) -> None:
        key = _bounded(name, 80)
        bounded_value = _bounded(value, self.value_limit)
        if not key or not bounded_value:
            return
        now = self._now()
        with self._lock:
            turn = self._turns.get(str(turn_id or ""))
            if turn is None:
                return
            turn.references[key] = bounded_value
            while len(turn.references) > self.max_references:
                turn.references.pop(next(iter(turn.references)))
            turn.updated_at = now
            session = self._session(turn.session_key)
            if session is not None:
                session.references[key] = bounded_value
                while len(session.references) > self.max_references:
                    session.references.pop(next(iter(session.references)))
                session.updated_at = now
        self._publish(turn, "REFERENCE")

    def record_tool_result(
        self, turn_id: str, *, tool: str, outcome: str, evidence: str = ""
    ) -> None:
        del tool  # Correlated tool details are owned by the transaction ledger.
        normalized = str(outcome or "").upper()
        if normalized != "VERIFIED":
            return
        bounded_evidence = _bounded(evidence, self.value_limit)
        now = self._now()
        with self._lock:
            turn = self._turns.get(str(turn_id or ""))
            if turn is None:
                return
            turn.last_verified_outcome = bounded_evidence
            turn.updated_at = now
            session = self._session(turn.session_key)
            if session is not None:
                session.last_verified_outcome = bounded_evidence
                session.updated_at = now
        self._publish(turn, "TOOL_RESULT")

    def set_pending_clarification(
        self, turn_id: str, question: str, missing_field: str
    ) -> None:
        now = self._now()
        with self._lock:
            turn = self._turns.get(str(turn_id or ""))
            if turn is None:
                return
            bounded_question = _bounded(question, self.value_limit)
            turn.pending_question = bounded_question
            turn.status = "WAITING"
            turn.updated_at = now
            session = self._session(turn.session_key)
            if session is not None:
                session.pending_question = bounded_question
                session.pending = PendingClarification(
                    original_utterance=turn.utterance,
                    question=bounded_question,
                    missing_field=_bounded(missing_field, 80),
                    owner_authenticated=turn.owner_authenticated,
                    created_at=now,
                )
                session.updated_at = now
        self._project(turn, "WAITING")

    def authorization_utterance(
        self, session_key: str, text: str, *, owner_authenticated: bool
    ) -> str:
        answer = _bounded(text, self.value_limit * 4)
        key = _context_key(session_key)
        with self._lock:
            session = self._session(key)
            if session is None or session.pending is None:
                return answer
            if _CANCEL_PHRASE.match(answer):
                session.pending = None
                session.pending_question = ""
                return answer
            pending = session.pending
            if self._now() - pending.created_at > self.clarification_ttl_s:
                session.pending = None
                session.pending_question = ""
                return answer
            if pending.owner_authenticated != bool(owner_authenticated):
                return answer
            session.pending = None
            session.pending_question = ""
            return (
                f"{pending.original_utterance}\n"
                f"Clarification answer: {answer}"
            )

    def finish_turn(self, turn_id: str) -> None:
        self._terminal(turn_id, "COMPLETED", "COMPLETED")

    def cancel_turn(self, turn_id: str, *, reason: str = "") -> None:
        self._terminal(turn_id, "CANCELLED", _bounded(reason or "CANCELLED", 80))

    def _terminal(self, turn_id: str, status: str, projection: str) -> None:
        with self._lock:
            turn = self._turns.get(str(turn_id or ""))
            if turn is None:
                return
            turn.status = status
            turn.updated_at = self._now()
            session = self._session(turn.session_key)
            if session is not None and session.active_turn_id == turn.turn_id:
                session.active_turn_id = ""
                session.updated_at = turn.updated_at
            manage_lifecycle = turn.manage_lifecycle
        if manage_lifecycle:
            try:
                from reyes_agent import conversation_state

                if conversation_state.current_turn() == turn.turn_id:
                    conversation_state.end_turn(turn.turn_id)
            except Exception:  # noqa: BLE001 -- projection never blocks cleanup
                pass
        self._project(turn, projection)

    def active_surface(self, session_key: str) -> str:
        with self._lock:
            session = self._session(_context_key(session_key))
            return session.active_surface if session is not None else ""

    def snapshot(self, session_key: str) -> dict[str, Any]:
        with self._lock:
            session = self._session(_context_key(session_key))
            if session is None:
                return {}
            return {
                "session_key": session.session_key,
                "active_turn_id": session.active_turn_id,
                "last_capabilities": list(session.last_capabilities),
                "active_surface": session.active_surface,
                "references": dict(session.references),
                "pending_question": session.pending_question,
                "last_verified_outcome": session.last_verified_outcome,
                "updated_at": session.updated_at,
            }

    def reset(self) -> None:
        with self._lock:
            self._sessions.clear()
            self._turns.clear()


_coordinator: ConversationCoordinator | None = None
_coordinator_lock = threading.Lock()


def get_coordinator() -> ConversationCoordinator:
    global _coordinator
    with _coordinator_lock:
        if _coordinator is None:
            _coordinator = ConversationCoordinator()
        return _coordinator
