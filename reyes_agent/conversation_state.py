"""The one authoritative conversation state machine.

WHY THIS EXISTS
---------------
Conversation state was real but scattered: the browser called
`orb.setState(...)` from sixteen different places with five visual names,
and the server tracked free-form `current_task` / `current_step` strings.
Nothing owned the answer to "what is ZENO doing right now", so nothing
could detect the failure the owner actually reported -- SPEAKING while
already SPEAKING, or THINKING fired three times because three listeners
were attached to the same event.

This module is that owner. It is deliberately small:

  * A fixed set of states and the transitions that are legal between them.
  * Re-entering the current state is SUPPRESSED, not applied -- and the
    suppression is counted per (state, source), which is exactly the
    fingerprint of a duplicate listener. `duplicate_report()` turns that
    into something a test can assert on.
  * An illegal transition is REJECTED and counted. The machine never
    silently accepts a move that cannot happen; a rejected transition is a
    bug report, not a state change.
  * Every transition is scoped to a turn. A transition arriving for a turn
    that is already over is rejected, which is what stops cancelled work
    from re-asserting SPEAKING after the user interrupted it.

WHAT IT IS NOT
--------------
Not a scheduler and not a task tracker. `task_engine.py` owns build-task
lifecycle (PLANNING/RUNNING/VERIFYING/...); those are two different
questions and deliberately stay two different modules. This one answers
only "what is the conversation doing".
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any

# --- states --------------------------------------------------------------
IDLE = "IDLE"
LISTENING = "LISTENING"
UNDERSTANDING = "UNDERSTANDING"
THINKING = "THINKING"
DEEP_THINKING = "DEEP_THINKING"
PLANNING = "PLANNING"
EXECUTING = "EXECUTING"
SPEAKING = "SPEAKING"
WAITING = "WAITING"
ADVISORY = "ADVISORY"
ERROR = "ERROR"

STATES = (IDLE, LISTENING, UNDERSTANDING, THINKING, DEEP_THINKING, PLANNING,
          EXECUTING, SPEAKING, WAITING, ADVISORY, ERROR)

# Busy states -- used by the UI and by the barge-in check.
ACTIVE_STATES = frozenset({LISTENING, UNDERSTANDING, THINKING, DEEP_THINKING,
                           PLANNING, EXECUTING, SPEAKING, ADVISORY})

# Legal moves. Kept explicit rather than "anything goes" so an impossible
# move is visible instead of quietly corrupting the display.
_TRANSITIONS: dict[str, frozenset[str]] = {
    IDLE:          frozenset({LISTENING, UNDERSTANDING, THINKING, DEEP_THINKING, EXECUTING, ERROR}),
    # A typed turn skips LISTENING entirely, which is why IDLE -> THINKING is legal.
    LISTENING:     frozenset({UNDERSTANDING, IDLE, ERROR}),
    UNDERSTANDING: frozenset({THINKING, DEEP_THINKING, EXECUTING, WAITING, SPEAKING, IDLE, ERROR}),
    # LISTENING/UNDERSTANDING are reachable from every working state on
    # purpose: the owner can start talking at any moment, and a new message
    # arriving mid-turn is normal conversation, not an error. Observed live
    # 2026-08-07 -- a follow-up sent while the previous turn was still
    # THINKING was rejected, which would have frozen the UI mid-thought.
    THINKING:      frozenset({PLANNING, EXECUTING, SPEAKING, ADVISORY, WAITING, IDLE, ERROR,
                              LISTENING, UNDERSTANDING}),
    DEEP_THINKING: frozenset({PLANNING, EXECUTING, SPEAKING, ADVISORY, WAITING, IDLE, ERROR,
                              LISTENING, UNDERSTANDING}),
    PLANNING:      frozenset({EXECUTING, THINKING, DEEP_THINKING, SPEAKING, WAITING, IDLE, ERROR,
                              LISTENING, UNDERSTANDING}),
    EXECUTING:     frozenset({THINKING, DEEP_THINKING, PLANNING, SPEAKING, WAITING, IDLE, ERROR,
                              LISTENING, UNDERSTANDING}),
    # Barge-in is the whole reason SPEAKING can go straight back to
    # LISTENING or UNDERSTANDING.
    SPEAKING:      frozenset({IDLE, LISTENING, UNDERSTANDING, WAITING, ERROR}),
    WAITING:       frozenset({THINKING, DEEP_THINKING, EXECUTING, LISTENING, SPEAKING, IDLE, ERROR}),
    ADVISORY:      frozenset({SPEAKING, IDLE, ERROR}),
    ERROR:         frozenset({IDLE, LISTENING}),
}

# Two enters of the same state closer together than this, from the same
# source, is what a duplicated listener looks like.
_DUPLICATE_WINDOW_S = 3.0
_MAX_HISTORY = 120
_MAX_TURNS_REMEMBERED = 40


@dataclass
class Transition:
    ok: bool
    state: str
    previous: str
    reason: str = ""
    suppressed: bool = False
    rejected: bool = False
    turn_id: str = ""
    at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "state": self.state, "previous": self.previous,
                "reason": self.reason, "suppressed": self.suppressed,
                "rejected": self.rejected, "turn_id": self.turn_id, "at": self.at}


_lock = threading.RLock()
_state = IDLE
_turn_id = ""
_entered_at = time.time()
_detail = ""
_history: deque[dict[str, Any]] = deque(maxlen=_MAX_HISTORY)
_finished_turns: deque[str] = deque(maxlen=_MAX_TURNS_REMEMBERED)

# Diagnostics -- the reason this module can prove the duplicate-listener bug
# is gone rather than asserting it.
_suppressed = Counter()          # (state, source) -> times a redundant enter was blocked
_rejected = Counter()            # (from->to) -> times an illegal move was refused
_stale = Counter()               # source -> transitions arriving for a finished turn
_last_enter: dict[tuple[str, str], float] = {}
_duplicate_signals: deque[dict[str, Any]] = deque(maxlen=40)


def _emit(transition: Transition) -> None:
    try:
        from reyes_agent import event_bus

        event_bus.publish(
            "conversation.state",
            {**transition.as_dict(), "detail": _detail},
            source="conversation_state",
            correlation_id=transition.turn_id,
        )
    except Exception:  # noqa: BLE001 -- observability never blocks a transition
        pass


def begin_turn(turn_id: str = "") -> str:
    """Open a turn. Everything after this is scoped to it."""
    global _turn_id
    turn_id = str(turn_id or uuid.uuid4().hex[:12])
    with _lock:
        if _turn_id and _turn_id != turn_id:
            _finished_turns.append(_turn_id)
        _turn_id = turn_id
    return turn_id


def end_turn(turn_id: str = "") -> None:
    """Close a turn and return to IDLE.

    Once closed, late transitions for that turn are rejected as stale --
    which is how a cancelled response cannot come back later and claim it
    is SPEAKING.
    """
    global _turn_id
    with _lock:
        target = str(turn_id or _turn_id)
        if target:
            _finished_turns.append(target)
        if target == _turn_id or not turn_id:
            _turn_id = ""
    enter(IDLE, source="end_turn", turn_id="")


def current() -> str:
    with _lock:
        return _state


def current_turn() -> str:
    with _lock:
        return _turn_id


def is_active() -> bool:
    with _lock:
        return _state in ACTIVE_STATES


def enter(state: str, *, source: str = "", turn_id: str = "",
          detail: str = "", force: bool = False) -> Transition:
    """Move to `state`. The single way conversation state ever changes.

    `source` names who asked (e.g. "agent.planning", "browser.mic"). It is
    not decoration: it is what makes a duplicate listener identifiable.
    """
    global _state, _entered_at, _detail
    now = time.time()
    state = str(state or "").upper()
    source = str(source or "unknown")[:64]

    if state not in STATES:
        transition = Transition(False, state, current(), f"'{state}' is not a state", rejected=True)
        with _lock:
            _rejected[f"invalid:{state}"] += 1
        return transition

    with _lock:
        previous = _state
        active_turn = _turn_id

        # Stale-turn guard. A transition for a turn that already finished is
        # refused outright -- this is the barge-in and cancellation
        # protection, not a nicety.
        if turn_id and turn_id in _finished_turns:
            _stale[source] += 1
            transition = Transition(False, state, previous, "transition arrived for a finished turn",
                                    rejected=True, turn_id=turn_id)
            _history.append(transition.as_dict())
            return transition
        if turn_id and active_turn and turn_id != active_turn:
            _stale[source] += 1
            transition = Transition(False, state, previous,
                                    f"transition belongs to turn {turn_id}, current turn is {active_turn}",
                                    rejected=True, turn_id=turn_id)
            _history.append(transition.as_dict())
            return transition

        # Idempotent re-entry. This is the SPEAKING+SPEAKING / THINKING x3
        # case: it is suppressed, and the suppression is recorded with its
        # source so a duplicated listener shows up in duplicate_report().
        if state == previous:
            key = (state, source)
            last = _last_enter.get(key, 0.0)
            _suppressed[key] += 1
            if now - last <= _DUPLICATE_WINDOW_S:
                _duplicate_signals.append({
                    "state": state, "source": source, "gap_s": round(now - last, 3),
                    "at": now, "turn_id": active_turn,
                })
            _last_enter[key] = now
            return Transition(True, state, previous, "already in this state", suppressed=True,
                              turn_id=active_turn or turn_id)

        allowed = _TRANSITIONS.get(previous, frozenset())
        if state not in allowed and not force:
            _rejected[f"{previous}->{state}"] += 1
            transition = Transition(False, state, previous,
                                    f"{previous} -> {state} is not a legal transition",
                                    rejected=True, turn_id=active_turn or turn_id)
            _history.append(transition.as_dict())
            return transition

        _state = state
        _entered_at = now
        _detail = str(detail or "")[:200]
        _last_enter[(state, source)] = now
        transition = Transition(True, state, previous, "", turn_id=active_turn or turn_id)
        _history.append({**transition.as_dict(), "source": source, "detail": _detail})

    _emit(transition)
    return transition


def barge_in(source: str = "user") -> Transition:
    """The user cut in while ZENO was talking.

    Stops audio through the EXISTING central speech queue rather than
    inventing a second one, then moves to LISTENING. Safe to call when not
    speaking -- it simply reports that there was nothing to interrupt.
    """
    with _lock:
        speaking = _state in {SPEAKING, ADVISORY}
        turn = _turn_id
    if not speaking:
        return Transition(False, LISTENING, current(), "not speaking -- nothing to interrupt")
    try:
        from reyes_agent import voice_manager

        voice_manager.cancel_current()
    except Exception:  # noqa: BLE001 -- state must change even if audio teardown fails
        pass
    # The interrupted turn is closed so its remaining events cannot come
    # back and re-assert SPEAKING.
    if turn:
        end_turn(turn)
    return enter(LISTENING, source=f"barge_in:{source}", detail="interrupted by the user")


def snapshot() -> dict[str, Any]:
    with _lock:
        return {
            "state": _state,
            "turn_id": _turn_id,
            "detail": _detail,
            "since_s": round(time.time() - _entered_at, 3),
            "active": _state in ACTIVE_STATES,
            "legal_next": sorted(_TRANSITIONS.get(_state, frozenset())),
            "history": list(_history)[-20:],
        }


def duplicate_report() -> dict[str, Any]:
    """Evidence about duplicate listeners and impossible moves.

    `repeat_sources` is the one to read: a source that keeps re-entering a
    state it is already in is almost always the same handler bound twice.
    """
    with _lock:
        return {
            "suppressed_repeats": sum(_suppressed.values()),
            "repeat_sources": {f"{state}:{src}": count
                               for (state, src), count in _suppressed.most_common(12)},
            "rejected_transitions": dict(_rejected.most_common(12)),
            "rejected_total": sum(_rejected.values()),
            "stale_turn_transitions": dict(_stale.most_common(8)),
            "stale_total": sum(_stale.values()),
            "rapid_duplicates": list(_duplicate_signals)[-10:],
            "note": (
                "suppressed_repeats counts redundant enters that were blocked -- the "
                "machine stayed correct. rapid_duplicates are repeats from the same "
                "source within 3s, which is what a double-bound listener looks like."
            ),
        }


def reset() -> None:
    """Test hook."""
    global _state, _turn_id, _entered_at, _detail
    with _lock:
        _state = IDLE
        _turn_id = ""
        _entered_at = time.time()
        _detail = ""
        _history.clear()
        _finished_turns.clear()
        _suppressed.clear()
        _rejected.clear()
        _stale.clear()
        _last_enter.clear()
        _duplicate_signals.clear()
