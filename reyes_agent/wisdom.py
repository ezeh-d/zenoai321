"""ZENO's own wisdom voice -- when a sharper way of putting it actually helps.

WHAT THIS MODULE IS, AND IS NOT
------------------------------
It is NOT a library of sayings. There is deliberately no list of canned
proverbs here, for two reasons that both matter:

  1. Originality. ZENO's wisdom must be its own. A stored list would be
     someone else's lines repeated verbatim, which is exactly what the
     owner asked this build never to do. Nothing in this file reproduces
     any real person's material, catchphrase, or script.
  2. Repetition. A fixed list would replay the same twelve lines forever,
     and the fastest way to make wisdom feel cheap is to hear it twice.

So this module decides only THREE things -- whether wisdom fits right now,
which tone, and how strongly -- and expresses that as a short style
directive. The actual words are composed fresh by the model each time, in
ZENO's voice, about the specific thing being discussed.

FREQUENCY IS THE WHOLE DESIGN
-----------------------------
Wisdom that appears in every reply is not wisdom, it is a tic. The gate
below is deliberately hard to pass: a cooldown, a decision-weight test, and
an absolute block on sensitive subjects. Silence is the default.
"""

from __future__ import annotations

import os
import threading
import time

from reyes_agent import cognition

# --- tones ---------------------------------------------------------------
LIGHT = "WISDOM_LIGHT"          # clever, relaxed, an analogy that lands
SERIOUS = "WISDOM_SERIOUS"      # direct, calm, no jokes
STRATEGIC = "WISDOM_STRATEGIC"  # consequences, trade-offs, the long game
SHORT = "WISDOM_SHORT"          # one memorable sentence, nothing more
NONE = "NONE"

# --- frequency modes -----------------------------------------------------
AUTO, LOW, NORMAL, HIGH, OFF = "AUTO", "LOW", "NORMAL", "HIGH", "OFF"
_MODES = {AUTO, LOW, NORMAL, HIGH, OFF}

# Minimum gap between wisdom moments, per mode. This is what stops every
# answer turning into a proverb.
_COOLDOWN_S = {HIGH: 60.0, NORMAL: 240.0, AUTO: 240.0, LOW: 900.0, OFF: float("inf")}

# How weighty the moment must be (0..1) before wisdom is offered unasked.
_THRESHOLD = {HIGH: 0.30, NORMAL: 0.55, AUTO: 0.55, LOW: 0.80, OFF: 2.0}

_lock = threading.Lock()
_last_at = 0.0
_mode_override = ""

# Explicit asks always work, regardless of cooldown -- being asked for
# wisdom and getting a shrug is worse than being asked and delivering.
_EXPLICIT = (
    "give me wisdom", "any wisdom", "wise words", "what do you really think",
    "be honest with me", "talk sense", "advise me properly", "your honest take",
    "wisdom on this", "real talk",
)


def mode() -> str:
    """AUTO / LOW / NORMAL / HIGH / OFF. Owner-configurable, default NORMAL."""
    with _lock:
        if _mode_override:
            return _mode_override
    raw = os.environ.get("ZENO_WISDOM_MODE", "").strip().upper()
    return raw if raw in _MODES else NORMAL


def set_mode(value: str) -> str:
    global _mode_override
    value = str(value or "").strip().upper()
    if value not in _MODES:
        raise ValueError(f"Wisdom mode must be one of {', '.join(sorted(_MODES))}.")
    with _lock:
        _mode_override = value
    return value


def _cooled_down(now: float, current_mode: str) -> bool:
    with _lock:
        return (now - _last_at) >= _COOLDOWN_S[current_mode]


def _mark_used(now: float) -> None:
    global _last_at
    with _lock:
        _last_at = now


def explicitly_requested(message: str) -> bool:
    text = cognition.normalize(message)
    return any(phrase in text for phrase in _EXPLICIT)


def choose_tone(message: str, decision: cognition.Route, weight: float) -> str:
    """Pick the register. Humour is the exception, never the default."""
    if cognition.is_sensitive(message):
        # Never clever about grief, illness, emergencies or real loss.
        return SERIOUS
    if weight >= 0.75 or cognition.ADVICE in decision.modes and decision.complexity >= 0.6:
        return STRATEGIC
    if decision.complexity >= 0.5:
        return SERIOUS
    if len(cognition.normalize(message).split()) <= 12:
        return SHORT
    return LIGHT


def evaluate(message: str, decision: cognition.Route, *, weight: float = 0.0,
             now: float | None = None) -> tuple[str, str]:
    """Decide whether wisdom belongs in this turn. Returns (tone, reason).

    `weight` is the Instinct engine's view of how much this moment matters
    (see instinct.py). Wisdom rides on top of that: a heavy moment earns a
    sharper observation, an ordinary one gets none.
    """
    now = time.time() if now is None else now
    current = mode()

    if current == OFF:
        return NONE, "wisdom is switched off"

    if explicitly_requested(message):
        tone = choose_tone(message, decision, max(weight, 0.8))
        _mark_used(now)
        return tone, "wisdom was explicitly asked for"

    if cognition.is_sensitive(message):
        # A serious situation can still receive a steady, plain observation,
        # but it must clear a much higher bar and must never be witty.
        if weight >= 0.85 and _cooled_down(now, current):
            _mark_used(now)
            return SERIOUS, "serious moment; plain and steady, no cleverness"
        return NONE, "sensitive subject -- say the useful thing plainly instead"

    if weight < _THRESHOLD[current]:
        return NONE, f"moment weight {weight:.2f} below the {current} threshold"

    if not _cooled_down(now, current):
        return NONE, "wisdom used recently -- staying quiet keeps it meaningful"

    tone = choose_tone(message, decision, weight)
    _mark_used(now)
    return tone, f"weighty moment ({weight:.2f}) and cooldown clear"


# The style brief. Describes HOW to speak, never WHAT to say -- every line
# ZENO produces is composed for the specific situation in front of it.
_STYLE = {
    LIGHT: (
        "You may close with ONE original observation in your own voice -- a plain-life "
        "comparison that makes the point land. Light and warm is fine. Invent it fresh "
        "for this exact situation; never recite a saved saying or anyone else's line."
    ),
    SERIOUS: (
        "Close with ONE calm, direct observation that names what actually matters here. "
        "No jokes, no analogy for its own sake. Your own words, written for this moment."
    ),
    STRATEGIC: (
        "Close with ONE original observation about the consequence being traded away -- "
        "what this costs later, or what it quietly commits him to. Concrete, not abstract. "
        "Your own words, never a stored aphorism."
    ),
    SHORT: (
        "Close with ONE short line in your own words -- a single sentence worth "
        "remembering, invented fresh for this moment. Say it once and stop; do not "
        "explain it afterwards, and never recite a saved saying."
    ),
}

# Nigerian conversational flavour is available and OPTIONAL. It is the
# owner's own register, so it should sound natural when it appears and be
# absent otherwise -- forced Pidgin is worse than none.
_FLAVOUR = (
    " Nigerian conversational flavour is welcome when it genuinely fits the moment; "
    "skip it entirely if it would feel put on."
)


def directive(tone: str, *, allow_flavour: bool = True) -> str:
    """The short prompt fragment for this turn. Empty when staying quiet."""
    if tone == NONE or tone not in _STYLE:
        return ""
    text = _STYLE[tone]
    if allow_flavour and tone in {LIGHT, SHORT}:
        text += _FLAVOUR
    return f"[{tone}: {text}]"


def status() -> dict:
    with _lock:
        last = _last_at
    current = mode()
    return {
        "mode": current,
        "cooldown_s": _COOLDOWN_S[current] if current != OFF else None,
        "threshold": _THRESHOLD[current] if current != OFF else None,
        "seconds_since_last": round(time.time() - last, 1) if last else None,
        "tones": [LIGHT, SERIOUS, STRATEGIC, SHORT],
        "policy": (
            "No stored sayings. Tone and timing are chosen here; the words are "
            "composed fresh by ZENO for the specific situation. Never used on "
            "sensitive subjects except as a plain, serious observation."
        ),
    }


def reset() -> None:
    """Test hook."""
    global _last_at, _mode_override
    with _lock:
        _last_at = 0.0
        _mode_override = ""
