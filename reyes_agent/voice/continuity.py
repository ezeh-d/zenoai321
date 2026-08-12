"""Staying in the conversation once it has started.

THE TWO THINGS THAT MAKE A VOICE ASSISTANT FEEL LIKE A MACHINE
--------------------------------------------------------------
Both are here because both were measured missing, not because they sound
good in a list.

FIRST: having to say the name every single time.

    "ZENO, what time is it?"      -> answers
    "and what about tomorrow?"    -> ignored
    "ZENO, what about tomorrow?"  -> answers

Nobody talks like that. It is the single most robot-like property a voice
system can have, and it is worse in front of a visitor, because the guest
learns within two turns that they are operating a machine rather than
talking to one. The wake word exists to open a conversation, not to
punctuate every sentence of it.

So after ZENO answers, a window opens. Inside it, speech is accepted without
the name. Every exchange extends the window; silence closes it.

SECOND: talking over someone who has started speaking.

`conversation_state.barge_in()` already exists and works -- but nothing on
the phone path ever called it, so a phone user could not interrupt. ZENO
would keep talking through them. That is not a missing feature so much as a
disconnected wire.

WHY THIS DOES NOT BECOME AN OPEN MICROPHONE
-------------------------------------------
The window is not "listen to the room". It only opens once ZENO has actually
answered somebody -- so a conversation demonstrably existed -- and it closes
on silence. Anything the window admits still passes speaker identity and
every permission check unchanged: the window decides whether the NAME was
needed, never whether the ACTION is allowed. And "ZENO, standby" shuts it
immediately.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

# How long after ZENO speaks a follow-up may arrive without the wake word.
# Long enough to think of the next question, short enough that a room
# conversation twenty seconds later is not addressed to ZENO.
FOLLOW_UP_WINDOW_S = 25.0

# During a hosted visit people take longer to formulate questions, and there
# is a known other participant in the room. Still bounded.
VISIT_WINDOW_S = 45.0

# Below this, an utterance is almost certainly not a command -- "mm", "yeah",
# a cough picked up as a word. Inside the window these are ignored rather
# than sent to the brain.
MIN_FOLLOW_UP_CHARS = 3

_lock = threading.RLock()
_state: dict[str, Any] = {"open_until": 0.0, "opened_by": "", "turns": 0,
                          "closed_reason": "never opened"}


@dataclass
class Decision:
    accept: bool
    needed_wake_word: bool
    reason: str
    window_s_left: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"accept": self.accept, "needed_wake_word": self.needed_wake_word,
                "reason": self.reason,
                "window_s_left": round(self.window_s_left, 1)}


def open_window(*, source: str = "reply", visit: bool = False) -> None:
    """ZENO just answered somebody, so a follow-up is plausible."""
    with _lock:
        _state["open_until"] = time.time() + (VISIT_WINDOW_S if visit
                                              else FOLLOW_UP_WINDOW_S)
        _state["opened_by"] = source
        _state["turns"] += 1
        _state["closed_reason"] = ""


def close(reason: str = "owner asked") -> None:
    """Shut it now. 'ZENO, standby' lands here."""
    with _lock:
        _state["open_until"] = 0.0
        _state["closed_reason"] = reason


def is_open() -> bool:
    with _lock:
        return time.time() < _state["open_until"]


def seconds_left() -> float:
    with _lock:
        return max(0.0, _state["open_until"] - time.time())


def consider(transcript: str, *, wake_matched: bool,
             visit: bool = False) -> Decision:
    """Should this utterance be answered.

    The wake word ALWAYS works -- the window only adds a way in, it never
    takes one away.
    """
    text = (transcript or "").strip()

    if wake_matched:
        # A named address re-opens the window regardless of its state.
        open_window(source="wake word", visit=visit)
        return Decision(True, True, "addressed by name", seconds_left())

    if not is_open():
        return Decision(False, True,
                        "no conversation is open -- the wake word is needed")

    if len(text) < MIN_FOLLOW_UP_CHARS:
        return Decision(False, False,
                        f"too short to be a follow-up ({len(text)} chars)",
                        seconds_left())

    # A real follow-up. Extend, so a conversation does not expire mid-flow.
    open_window(source="follow-up", visit=visit)
    return Decision(True, False, "follow-up inside the conversation window",
                    seconds_left())


def interrupted(source: str = "phone") -> dict[str, Any]:
    """Somebody started speaking. Stop talking if ZENO was talking.

    Routed through the EXISTING conversation_state.barge_in() rather than
    stopping audio here -- there must be exactly one thing that can silence
    the speech queue, or two of them will race.
    """
    try:
        from reyes_agent import conversation_state

        transition = conversation_state.barge_in(source=source)
        stopped = bool(getattr(transition, "changed", False) or
                       getattr(transition, "ok", False))
        return {"stopped_speaking": stopped,
                "detail": getattr(transition, "reason", "") or
                          getattr(transition, "detail", ""),
                "state": conversation_state.current()}
    except Exception as exc:  # noqa: BLE001
        return {"stopped_speaking": False,
                "detail": f"{type(exc).__name__}: {exc}"}


def status() -> dict[str, Any]:
    with _lock:
        snapshot = dict(_state)
    return {
        "state": "OPEN" if is_open() else "CLOSED",
        "seconds_left": round(seconds_left(), 1),
        "opened_by": snapshot["opened_by"],
        "exchanges": snapshot["turns"],
        "closed_reason": snapshot["closed_reason"],
        "window_s": {"normal": FOLLOW_UP_WINDOW_S, "visit": VISIT_WINDOW_S},
        "rule": ("The window decides whether the NAME was needed. It never "
                 "decides whether the ACTION is allowed -- identity and "
                 "permissions are unchanged either way."),
    }
