"""A small, local timing policy for ZENO's humour.

This module never generates a reply and never calls a model.  It only gives
the existing authoritative agent turn a compact tonal instruction when a joke,
banter, or a light reaction genuinely fits.  Recent joke *replies* stay in a
bounded in-memory deque so they are not written to Living Memory or replayed
as permanent personal data.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque

from reyes_agent import cognition


HUMOUR_OFF = "HUMOUR_OFF"
HUMOUR_LOW = "HUMOUR_LOW"
HUMOUR_NORMAL = "HUMOUR_NORMAL"
HUMOUR_HIGH = "HUMOUR_HIGH"
_MODES = {HUMOUR_OFF, HUMOUR_LOW, HUMOUR_NORMAL, HUMOUR_HIGH}

_lock = threading.Lock()
_override = ""
_recent: deque[str] = deque(maxlen=8)
_last_light_at = 0.0

_JOKE = ("tell me a joke", "make me laugh", "say something funny", "joke for me")
_ANOTHER = ("another one", "another joke", "give me another", "one more")
_NOT_FUNNY = ("not funny", "no funny", "that one no funny", "wasn't funny", "was not funny")
_ROAST = ("roast me", "tease me", "drag me small", "insult me small")
_PLAYFUL = ("you slow today", "you are slow", "you dey slow", "lol", "lmao", "haha")
_FRUSTRATION = (
    "don spoil", "code don break", "code has break", "code has broken",
    "this thing don", "this thing has", "bug again",
)
_SERIOUS = (
    "serious mode", "take this seriously", "this matters", "something serious",
    "emergency", "urgent", "security incident", "i need help",
)


def mode() -> str:
    """Return the owner preference; NORMAL is the quiet default."""
    with _lock:
        if _override:
            return _override
    raw = os.environ.get("ZENO_HUMOUR_MODE", "").strip().upper()
    aliases = {"OFF": HUMOUR_OFF, "LOW": HUMOUR_LOW, "NORMAL": HUMOUR_NORMAL, "HIGH": HUMOUR_HIGH}
    return raw if raw in _MODES else aliases.get(raw, HUMOUR_NORMAL)


def set_mode(value: str) -> str:
    global _override
    value = str(value or "").strip().upper()
    aliases = {"OFF": HUMOUR_OFF, "LOW": HUMOUR_LOW, "NORMAL": HUMOUR_NORMAL, "HIGH": HUMOUR_HIGH}
    value = aliases.get(value, value)
    if value not in _MODES:
        raise ValueError("Humour mode must be HUMOUR_OFF, HUMOUR_LOW, HUMOUR_NORMAL, or HUMOUR_HIGH.")
    with _lock:
        _override = value
    return value


def reset() -> None:
    """Test/support reset. Does not affect long-term memory because none is used."""
    global _override, _last_light_at
    with _lock:
        _override = ""
        _last_light_at = 0.0
        _recent.clear()


def _contains(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def intent(message: str) -> str:
    """Classify only clear user intent; ambiguity deliberately stays NONE."""
    text = cognition.normalize(message)
    if _contains(text, _JOKE):
        return "JOKE"
    if _contains(text, _ANOTHER):
        return "ANOTHER"
    if _contains(text, _NOT_FUNNY):
        return "RETRY"
    if _contains(text, _ROAST):
        return "ROAST"
    if _contains(text, _PLAYFUL):
        return "BANTER"
    if _contains(text, _FRUSTRATION):
        return "LIGHT_REACTION"
    return "NONE"


def serious(message: str) -> bool:
    text = cognition.normalize(message)
    return cognition.is_sensitive(message) or _contains(text, _SERIOUS)


def _recent_summary() -> str:
    with _lock:
        items = list(_recent)[-3:]
    if not items:
        return ""
    # Prompt context, not durable memory. Keep it short and escape nothing:
    # it is a model instruction, never interpolated into HTML or a shell.
    return " Avoid reusing these recent joke replies: " + " | ".join(repr(item[:110]) for item in items) + "."


def directive(message: str, decision: cognition.Route, *, now: float | None = None) -> str:
    """Return a compact style instruction for the existing agent turn.

    Explicit comedy asks are handled on FAST without tools.  Unsolicited
    humour is intentionally rare and never allowed on serious/sensitive or
    direct action-only turns.
    """
    global _last_light_at

    now = time.time() if now is None else now
    current = mode()
    if current == HUMOUR_OFF or serious(message):
        return ""

    kind = intent(message)
    if kind == "JOKE":
        return "[Humour: user explicitly asked for one short, original conversational joke. Give only the joke; no tools, no lecture.]" + _recent_summary()
    if kind == "ANOTHER":
        return "[Humour: continue the joke exchange. Give one different short joke immediately; do not ask what they mean.]" + _recent_summary()
    if kind == "RETRY":
        return "[Humour: acknowledge the last joke missed, lightly and without defensiveness, then give one clearly different short joke.]" + _recent_summary()
    if kind == "ROAST":
        return "[Humour: give one light, affectionate roast. Never insult, humiliate, target identity, appearance, trauma, money, or a real vulnerability.]"
    if kind == "BANTER":
        return "[Humour: a brief warm comeback is allowed. Match the user's language/register; do not turn it into an insult or delay useful help.]"

    # NORMAL gets one brief, useful reaction only for a clear frustration.
    # LOW stays fully quiet unless the user explicitly asks for comedy.
    if kind == "LIGHT_REACTION" and current in {HUMOUR_NORMAL, HUMOUR_HIGH}:
        with _lock:
            if now - _last_light_at < (300.0 if current == HUMOUR_NORMAL else 90.0):
                return ""
            _last_light_at = now
        return ("[Humour: one short, gentle reaction may open this frustrated technical reply, "
                "then immediately give practical help. Match Pidgin only if the user used it; do not overdo it.]")
    return ""


def record_reply(message: str, reply: str) -> None:
    """Keep only recent explicitly humorous replies, locally and bounded."""
    if intent(message) not in {"JOKE", "ANOTHER", "RETRY", "ROAST"}:
        return
    clean = " ".join(str(reply or "").split())
    if not clean:
        return
    with _lock:
        if clean not in _recent:
            _recent.append(clean[:400])


def status() -> dict:
    with _lock:
        count = len(_recent)
    return {
        "mode": mode(), "recent_jokes": count, "capacity": _recent.maxlen,
        "policy": "Local bounded recent-joke history only; no joke is written to Living Memory.",
    }
