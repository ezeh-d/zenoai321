"""Bounded, honest response-latency policy for voice conversation.

Only trivial social utterances can be answered locally.  Anything that may
need facts, memory, tools, advice or judgement continues through ZENO's real
brain.  This deliberately tiny allow-list prevents a speed optimisation from
turning into a second fake assistant.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from reyes_agent import config


@dataclass(frozen=True)
class FastReply:
    text: str
    intent: str


_RESPONSES: dict[str, tuple[str, ...]] = {
    "greeting": ("Hey, bro. What's up?",),
    "wellbeing": ("I'm good, bro. How you dey?",),
    "thanks": ("Anytime, bro.",),
    "acknowledgement": ("Got you.",),
}

_EXACT: dict[str, str] = {}
for _intent, _phrases in {
    "greeting": (
        "hi", "hello", "hey", "yo", "hi zeno", "hello zeno", "hey zeno",
        "yo zeno", "good morning", "good afternoon", "good evening", "what's up",
        "whats up",
    ),
    "wellbeing": (
        "how are you", "how are you doing", "how you dey", "how far", "you good",
        "are you okay", "are you ok",
    ),
    "thanks": (
        "thanks", "thank you", "thanks zeno", "thank you zeno", "nice one",
    ),
    "acknowledgement": (
        "ok", "okay", "alright", "cool", "got it", "i understand",
    ),
}.items():
    for _phrase in _phrases:
        _EXACT[_phrase] = _intent


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]+", " ", str(text).casefold())).strip()


def reply_for(text: str) -> FastReply | None:
    """Return a local reply only for an exact, consequence-free utterance."""
    if not config.VOICE_FAST_LOCAL_REPLIES:
        return None
    normalised = _normalise(text)
    intent = _EXACT.get(normalised)
    if intent is None:
        return None
    choices = _RESPONSES[intent]
    digest = hashlib.blake2b(normalised.encode("utf-8"), digest_size=2).digest()
    return FastReply(choices[int.from_bytes(digest, "big") % len(choices)], intent)


def cacheable_fast_replies() -> tuple[str, ...]:
    """All bounded phrases that can occur, for off-path ElevenLabs warming."""
    return tuple(dict.fromkeys(text for values in _RESPONSES.values() for text in values))


def diagnostics() -> dict[str, object]:
    return {
        "target_ms": config.VOICE_RESPONSE_BUDGET_MS,
        "ack_delay_ms": config.VOICE_THINKING_ACK_DELAY_MS,
        "fast_local_replies": config.VOICE_FAST_LOCAL_REPLIES,
        "thinking_ack": config.VOICE_THINKING_ACK_ENABLED,
        "local_intents": sorted(_RESPONSES),
    }
