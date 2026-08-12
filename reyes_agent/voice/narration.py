"""Saying what you're doing while you do it.

THE SILENCE PROBLEM
-------------------
Ask a person to check something and they say "let me look" before they look.
Ask ZENO and, until now, nothing happened -- the room went quiet for four
seconds and then an answer arrived. The listener cannot tell a system that is
working from one that has crashed, so they ask again, or they apologise for
the machine, or they fill the silence themselves. In front of a visitor, that
silence reads as a fault even when the answer is perfect.

WHY THIS IS NOT "PROCESSING..."
-------------------------------
    "Do not speak 'Processing...' 'Analyzing...' 'Thinking...' every time."

Quite right, and the reason is that those say nothing. They are the same
noise whatever is happening, so after twice they carry no information and
start to grate. What a person says is specific -- "let me check your
calendar", "opening Slack now" -- because the specificity IS the reassurance:
it proves the right thing was understood before the answer exists.

So narration here is derived from the TOOL ACTUALLY BEING CALLED, and it only
speaks when something genuinely slow is happening. A fast answer is not
improved by being announced.

THREE RULES THAT KEEP IT PLEASANT
---------------------------------
Speak once per turn, not once per tool -- a turn that calls six tools must
not narrate six times.
Stay under a breath: four or five words, because this is filler while the
real answer is coming, and long filler delays the thing it apologises for.
Vary the wording, so hearing it twice in a minute does not sound like a
recording.
"""

from __future__ import annotations

import random
import threading
import time
from typing import Any

# Only narrate when the work is genuinely slow enough that silence would be
# uncomfortable. Anything under this answers before a person would have
# finished saying "let me check".
NARRATE_AFTER_S = 0.9

# One narration per turn. A turn calling six tools narrating six times is
# worse than saying nothing at all.
_lock = threading.RLock()
_state: dict[str, Any] = {"turn_id": "", "spoken": False, "started": 0.0}

# What each kind of work sounds like out loud. Several phrasings each, so the
# same action twice in a minute does not sound like a recording.
_PHRASES: dict[str, tuple[str, ...]] = {
    "search": ("Let me look that up.", "Checking now.", "Looking that up."),
    "web": ("Let me search for that.", "Checking online now.",
            "Looking that up online."),
    "file": ("Let me check the files.", "Looking through them now.",
             "Checking that file."),
    "memory": ("Let me check what I have.", "Checking my notes.",
               "Looking that up."),
    "calendar": ("Let me check your calendar.", "Checking your schedule."),
    "mail": ("Let me check your mail.", "Checking your inbox."),
    "app": ("Opening that now.", "Getting that open.", "One moment, opening it."),
    "message": ("Let me send that.", "Sending that now."),
    "system": ("Let me check the machine.", "Checking that now."),
    "agent": ("Let me ask the team.", "Checking with the specialists.",
              "Passing that to the right agent."),
    "build": ("Let me put that together.", "Working on that now.",
              "Building that."),
    "vision": ("Let me look at the screen.", "Taking a look now."),
    "generic": ("One moment.", "Let me check.", "Checking now.",
                "Give me a second."),
}

# Tool name fragments -> the kind of work they represent. Matched on the
# fragment so a new tool named `search_invoices` narrates sensibly without
# anyone having to add it here.
_KINDS: tuple[tuple[str, str], ...] = (
    ("calendar", "calendar"),
    ("email", "mail"), ("mail", "mail"), ("inbox", "mail"),
    ("send_message", "message"), ("message", "message"), ("slack", "message"),
    ("whatsapp", "message"), ("telegram", "message"), ("discord", "message"),
    ("open_app", "app"), ("launch", "app"), ("open_", "app"),
    ("web_search", "web"), ("browse", "web"), ("news", "web"), ("fetch", "web"),
    ("screenshot", "vision"), ("vision", "vision"), ("camera", "vision"),
    ("memory", "memory"), ("remember", "memory"), ("recall", "memory"),
    ("note", "memory"), ("vault", "memory"),
    ("agent", "agent"), ("council", "agent"), ("delegate", "agent"),
    ("specialist", "agent"), ("worker", "agent"),
    ("build", "build"), ("project", "build"), ("write_", "build"),
    ("create", "build"), ("generate", "build"),
    ("health", "system"), ("process", "system"), ("system", "system"),
    ("file", "file"), ("read_", "file"), ("list_", "file"),
    ("search", "search"), ("find", "search"), ("look", "search"),
)


def kind_of(tool_name: str) -> str:
    """Which sort of work a tool represents, for phrasing purposes."""
    name = (tool_name or "").lower()
    for fragment, kind in _KINDS:
        if fragment in name:
            return kind
    return "generic"


def line_for(tool_name: str) -> str:
    """One short spoken line for the work about to happen."""
    return random.choice(_PHRASES.get(kind_of(tool_name), _PHRASES["generic"]))


def begin_turn(turn_id: str = "") -> None:
    """A new turn started; narration is allowed again."""
    with _lock:
        _state.update({"turn_id": turn_id, "spoken": False,
                       "started": time.monotonic()})


def should_narrate(tool_name: str, *, spoken_turn: bool = True) -> tuple[bool, str]:
    """Should ZENO say something now, and what.

    False for a fast turn: an answer that arrives before a person would have
    finished saying "let me check" is not improved by being announced first.
    """
    if not spoken_turn:
        return False, ""
    with _lock:
        if _state["spoken"]:
            return False, ""
        elapsed = time.monotonic() - (_state["started"] or time.monotonic())
        if elapsed < NARRATE_AFTER_S:
            return False, ""
        _state["spoken"] = True
    return True, line_for(tool_name)


def narrate(tool_name: str, *, spoken_turn: bool = True) -> str:
    """Speak the line if one is due. Returns what was said, or ''.

    Goes through the ordinary speech queue, so it is interruptible and is
    cancelled by barge-in exactly like any other speech. Never raises -- a
    failure to say "one moment" must not fail the turn it was narrating.
    """
    due, line = should_narrate(tool_name, spoken_turn=spoken_turn)
    if not due:
        return ""
    try:
        from reyes_agent.voice_manager import cached_audio, speak_cached_queued, speak_queued

        cached = cached_audio(line)
        speak_cached_queued(cached) if cached else speak_queued(line)
        return line
    except Exception:  # noqa: BLE001
        return ""


def status() -> dict[str, Any]:
    with _lock:
        snapshot = dict(_state)
    return {
        "state": "ONLINE",
        "narrate_after_s": NARRATE_AFTER_S,
        "spoken_this_turn": snapshot["spoken"],
        "kinds": sorted(_PHRASES),
        "rule": ("Derived from the tool actually being called, once per turn, "
                 "only when the work is slow enough that silence would be "
                 "uncomfortable."),
    }
