"""Humor as a modular capability, not a system-prompt essay.

The main system prompt never grows for this: classify_intent() recognizes a
handful of explicit phrasings ("tell me a joke", "roast me", "dark humor
battle", "another one", ...) with the same exact-match discipline as
voice/local_command_router.py, and build_context() returns a SMALL addendum
appended to THIS turn's system prompt only (mirrors agent.py's existing
matched_skill_context pattern) -- gone again on the next turn unless a battle
is still active. The actual jokes are never hard-coded: only the model
generates them, so "avoid repeating jokes" is enforced by tracking what was
already said (note_used()/is_repeat()) and telling the model what to avoid,
not by drawing from a canned list that would run out and start repeating on
its own.

Battle state is a small, single-owner, in-process store -- ZENO has one
conversation at a time, so this does not need per-session keys, matching
Confirmation/RuntimeControl elsewhere in this codebase.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field

_PREVIOUS_JOKES_MAX = 12
_BATTLE_IDLE_TIMEOUT_S = 10 * 60  # an abandoned battle stops counting as active

# --- content safety, non-negotiable regardless of "intensity" --------------
_DARK_HUMOR_BOUNDARY = (
    "Dark humor stays general and fictional: absurd, morbid-silly, gallows "
    "humor about death/taxes/existence in the abstract. Never write hateful "
    "content, never target a real, named, identifiable person, never joke "
    "about self-harm/suicide as something to do (gallows humor ABOUT mortality "
    "in the abstract is fine; content that could read as encouragement is "
    "not), and never make light of a real tragedy, real victims, or a "
    "protected group. If a request pushes past this, decline the specific "
    "joke and stay in character doing it -- do not lecture at length."
)


@dataclass
class BattleState:
    active: bool = False
    mode: str = ""  # "dark_battle" | "comeback_battle"
    round: int = 0
    score_user: int = 0
    score_zeno: int = 0
    max_rounds: int = 5
    intensity: str = "mild"  # "mild" | "medium" | "spicy" -- never a safety override
    previous_jokes: list[str] = field(default_factory=list)
    last_activity_at: float = 0.0

    def note_used(self, joke_text: str) -> None:
        sig = _signature(joke_text)
        if sig and sig not in self.previous_jokes:
            self.previous_jokes.append(sig)
            del self.previous_jokes[:-_PREVIOUS_JOKES_MAX]

    def is_repeat(self, joke_text: str) -> bool:
        return _signature(joke_text) in self.previous_jokes


def _signature(text: str) -> str:
    """A short, order-insensitive fingerprint so near-identical punchlines
    ('why did the chicken cross the road' vs '...cross the road?') still
    count as the same joke, without storing/echoing the full text anywhere."""
    words = sorted(set(re.sub(r"[^a-z0-9 ]", " ", str(text).casefold()).split()))
    return " ".join(words)[:200]


_lock = threading.RLock()
_battle = BattleState()
_last_joke_signatures: list[str] = []  # tracked even OUTSIDE a battle


def _idle_reset_locked() -> None:
    if _battle.active and time.time() - _battle.last_activity_at > _BATTLE_IDLE_TIMEOUT_S:
        _battle.__init__()  # noqa: PLC2801 -- deliberate reset to defaults


def get_battle_state() -> BattleState:
    with _lock:
        _idle_reset_locked()
        return BattleState(**vars(_battle))  # a copy; callers must not mutate the store


# --- intent classification --------------------------------------------------
_JOKE_TRIGGERS: dict[str, tuple[str, ...]] = {
    "joke": (
        "tell me a joke", "got a joke", "say a joke", "make me laugh",
        "know any jokes", "hit me with a joke",
    ),
    "dad_joke": ("tell me a dad joke", "give me a dad joke", "dad joke"),
    "programming_joke": (
        "tell me a programming joke", "give me a programming joke",
        "coding joke", "programmer joke", "nerd joke", "tech joke",
    ),
    "dark_joke": ("tell me a dark joke", "give me a dark joke", "dark joke"),
    "roast": ("roast me", "give me a roast", "roast me please"),
    "dark_battle": (
        "dark humor battle", "let's do a dark humor battle",
        "start a dark humor battle", "dark joke battle",
    ),
    "comeback_battle": (
        "comeback battle", "let's do a comeback battle", "roast battle",
        "start a comeback battle", "let's roast each other",
    ),
    "another": ("another one", "another joke", "one more", "hit me again", "again"),
    "feedback_bad": (
        "that joke was terrible", "that was terrible", "that joke sucked",
        "not funny", "that was bad", "worse joke ever", "that joke was bad",
    ),
    "stop_battle": ("stop the battle", "end the battle", "that's enough", "i give up", "you win"),
}


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]+", " ", str(text).casefold())).strip()


def classify_intent(message: str) -> str | None:
    """Exact-phrase match only -- same discipline as the local command
    router: false positives here would inject humor framing into an
    unrelated serious turn, which is worse than missing an occasional
    casually-phrased joke request (the model still handles those normally,
    just without the dedicated addendum)."""
    normalised = _normalise(message)
    if not normalised:
        return None
    for intent, phrases in _JOKE_TRIGGERS.items():
        if normalised in phrases:
            return intent
    return None


# --- state transitions -------------------------------------------------------
def start_battle(mode: str, *, intensity: str = "mild", max_rounds: int = 5) -> BattleState:
    with _lock:
        _battle.__init__(  # noqa: PLC2801 -- deliberate reset into a fresh battle
            active=True, mode=mode, round=1, intensity=intensity,
            max_rounds=max(1, min(20, max_rounds)), last_activity_at=time.time(),
        )
        return BattleState(**vars(_battle))


def stop_battle() -> None:
    with _lock:
        _battle.__init__()  # noqa: PLC2801


def record_round_result(who_won: str) -> BattleState:
    """who_won: 'user' | 'zeno' | 'tie'. Called after the model judges one
    exchange (see the battle_score tool) -- state bookkeeping is
    deterministic and testable even though the JUDGING is the model's call."""
    with _lock:
        _idle_reset_locked()
        if not _battle.active:
            return BattleState(**vars(_battle))
        who_won = who_won if who_won in {"user", "zeno", "tie"} else "tie"
        if who_won == "user":
            _battle.score_user += 1
        elif who_won == "zeno":
            _battle.score_zeno += 1
        _battle.round += 1
        _battle.last_activity_at = time.time()
        if _battle.round > _battle.max_rounds:
            _battle.active = False
        return BattleState(**vars(_battle))


def note_joke_used(joke_text: str) -> None:
    with _lock:
        _battle.note_used(joke_text)
        sig = _signature(joke_text)
        if sig and sig not in _last_joke_signatures:
            _last_joke_signatures.append(sig)
            del _last_joke_signatures[:-_PREVIOUS_JOKES_MAX]


def is_repeat(joke_text: str) -> bool:
    with _lock:
        sig = _signature(joke_text)
        return sig in _battle.previous_jokes or sig in _last_joke_signatures


# --- prompt addendum ---------------------------------------------------------
_TONE_GUIDANCE = {
    "joke": "Tell ONE original joke. Keep it short -- a real joke, not a lecture about jokes.",
    "dad_joke": "Tell ONE dad joke -- groan-worthy pun energy, delivered completely straight.",
    "programming_joke": "Tell ONE joke a programmer would actually laugh at -- real technical "
                        "premise, not a generic joke with 'code' swapped in.",
    "dark_joke": "Tell ONE dark/gallows-humor joke. " + _DARK_HUMOR_BOUNDARY,
    "roast": "Deliver ONE short, clearly-affectionate roast of the owner -- sharp, funny, "
             "never cruel or targeting anything actually sensitive about a real person.",
    "another": "Tell another one, different angle/category from your last one -- never the same joke reworded.",
    "feedback_bad": "The owner didn't like the last one. Own it briefly and try a genuinely "
                    "different, better joke -- don't apologize at length.",
}


def build_context(intent: str, battle: BattleState) -> str:
    """A small, per-turn addendum -- never the whole personality baked into
    the main prompt. Empty string if there's nothing to add."""
    parts: list[str] = []
    if intent in ("dark_battle", "comeback_battle"):
        label = "dark humor battle" if intent == "dark_battle" else "comeback battle"
        parts.append(
            f"\n\nHUMOR MODE: the owner just started a {label}. You are the opponent AND "
            "the scorekeeper. Deliver one line, then call battle_score with who you judge "
            "won THIS exchange ('user'/'zeno'/'tie') and a one-phrase reason. Keep it playful, "
            "never actually mean."
        )
        if intent == "dark_battle":
            parts.append(_DARK_HUMOR_BOUNDARY)
    elif battle.active:
        parts.append(
            f"\n\nHUMOR MODE: a {battle.mode.replace('_', ' ')} is in progress -- round "
            f"{battle.round} of {battle.max_rounds}, score you {battle.score_zeno}-"
            f"{battle.score_user} owner. Stay in the battle unless the owner clearly wants "
            "to stop; deliver one line and call battle_score to judge this exchange."
        )
        if battle.mode == "dark_battle":
            parts.append(_DARK_HUMOR_BOUNDARY)
    elif intent in _TONE_GUIDANCE:
        parts.append(f"\n\nHUMOR MODE: {_TONE_GUIDANCE[intent]}")
    elif intent == "stop_battle":
        return ""  # handled by the caller ending the battle; no addendum needed

    if not parts:
        return ""

    if battle.previous_jokes or _last_joke_signatures:
        parts.append(
            " Do not repeat a joke/roast you already used this conversation -- "
            "a genuinely new one, not a reworded version of the last one."
        )
    return "".join(parts)
