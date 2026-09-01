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

So the wake word OPENS a conversation and then gets out of the way. Inside an
open conversation, speech is accepted without the name; every exchange
extends it. It ends when the owner ends it -- "standby", "that's all",
"thanks ZENO" -- or after a long enough silence that whatever is said next is
a new conversation rather than a continuation of this one.

Saying "ZENO" is still meaningful inside a conversation: it re-addresses him,
which is exactly what you do when you hand him to somebody else in the room.
It is simply no longer REQUIRED on every sentence.

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

def _seconds_env(name: str, default: float) -> float:
    """A tunable idle time, bounded so neither extreme is reachable.

    Floor of 30s because anything less recreates the problem this exists to
    fix. Ceiling of an hour because an open microphone with no end is a
    different product, and not one the owner asked for.
    """
    import os

    try:
        return max(30.0, min(3600.0, float(os.environ.get(name, default))))
    except (TypeError, ValueError):
        return default


# HOW LONG THE CONVERSATION STAYS OPEN.
#
# The first version of this used 25 seconds, and that was wrong -- it is
# still "say the name every time" with extra steps, because 25 seconds is
# shorter than a pause to think, shorter than reading something off the
# screen, and far shorter than a conversation with a third person in the
# room. The owner said so plainly, and he was right.
#
# The wake word's job is to OPEN a conversation, or to hand ZENO to somebody
# else. It is not punctuation. So once a conversation is open it stays open
# through ordinary silences, and closes when the conversation is actually
# over -- either because the owner said so, or because nothing has been said
# for long enough that the next thing said is a new conversation.
FOLLOW_UP_WINDOW_S = _seconds_env("ZENO_CONVERSATION_IDLE_S", 180.0)

# A hosted visit runs longer still: people think before asking, the host and
# the visitor talk to each other, and being dropped mid-visit is exactly the
# failure that makes it feel like a machine.
VISIT_WINDOW_S = _seconds_env("ZENO_VISIT_IDLE_S", 300.0)

# Said out loud, these end it. The owner should be able to close a
# conversation the way a person does, rather than by waiting for a timer.
CLOSING_PHRASES = (
    "standby", "stand by", "that's all", "thats all", "that will be all",
    "goodbye zeno", "bye zeno", "thanks zeno", "thank you zeno",
    "that's it for now", "we're done", "were done", "stop listening",
    "go to sleep", "sleep now", "nevermind", "never mind",
)

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
    # The transcript looks syntactically unfinished ("open spotify and"): the
    # caller MAY keep listening rather than answer a half-sentence (#semantic
    # turn detection). Additive -- old callers simply ignore it.
    incomplete: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"accept": self.accept, "needed_wake_word": self.needed_wake_word,
                "reason": self.reason, "incomplete": self.incomplete,
                "window_s_left": round(self.window_s_left, 1)}


def _looks_incomplete(text: str) -> bool:
    try:
        from reyes_agent.conversation.realtime import is_turn_complete
        return not is_turn_complete(text)["complete"]
    except Exception:  # noqa: BLE001
        return False


def _is_backchannel(text: str) -> bool:
    try:
        from reyes_agent.conversation.realtime import classify_utterance, BACKCHANNEL
        return classify_utterance(text, zeno_speaking=False)["type"] == BACKCHANNEL
    except Exception:  # noqa: BLE001
        return False


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
    low = text.lower().strip(" .,!?")

    # Ending a conversation should feel like ending one. "Standby" or
    # "that's all" closes it immediately, rather than the owner waiting out
    # a timer he cannot see.
    if any(phrase in low for phrase in CLOSING_PHRASES):
        close("the owner ended the conversation")
        return Decision(True, False, "closing phrase -- conversation ended", 0.0)

    if wake_matched:
        # A named address re-opens the window regardless of its state.
        open_window(source="wake word", visit=visit)
        return Decision(True, True, "addressed by name", seconds_left(),
                        incomplete=_looks_incomplete(text))

    if not is_open():
        return Decision(False, True,
                        "no conversation is open -- the wake word is needed")

    if len(text) < MIN_FOLLOW_UP_CHARS:
        return Decision(False, False,
                        f"too short to be a follow-up ({len(text)} chars)",
                        seconds_left())

    # A bare acknowledgement inside an open window ("mhm", "okay", "right") is
    # the owner listening, not a new command -- don't answer it.
    if _is_backchannel(text):
        return Decision(False, False, "backchannel, not a command",
                        seconds_left())

    # A real follow-up. Extend, so a conversation does not expire mid-flow.
    open_window(source="follow-up", visit=visit)
    return Decision(True, False, "follow-up inside the conversation window",
                    seconds_left(), incomplete=_looks_incomplete(text))


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
