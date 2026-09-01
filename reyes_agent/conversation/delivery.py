"""Speech delivery helpers -- streaming sentence-TTS and prosody selection.

Two deterministic, tested components the voice pipeline plugs into:

  SentenceStreamer -- turn a growing LLM token stream into speakable clauses the
                      moment each one is complete, so TTS can start on sentence 1
                      while sentence 2 is still being generated (no wait-for-the-
                      whole-answer).
  delivery_for     -- map a turn's context (urgency / seriousness / complexity)
                      to a SUBTLE prosody choice (style + speaking rate). Never
                      exaggerated, never pretending ZENO has feelings -- it just
                      communicates conversational context.

These produce the CLAUSES and the PARAMS; feeding them to the actual TTS backend
(piper/ElevenLabs) is the on-device wiring step. No model here.
"""

from __future__ import annotations

import re
from typing import Any

# sentence-final and strong-clause boundaries worth speaking on
_BOUNDARY = re.compile(r"[.!?](?=\s|$)|[;:](?=\s)")
_MIN_CLAUSE = 12          # don't emit a tiny fragment as its own utterance
_MAX_BUFFER = 180         # if no punctuation arrives, flush at a word boundary


class SentenceStreamer:
    """Feed it the growing reply; it yields complete clauses to speak."""

    def __init__(self, *, min_clause: int = _MIN_CLAUSE,
                 max_buffer: int = _MAX_BUFFER) -> None:
        self._buf = ""
        self._min = int(min_clause)
        self._max = int(max_buffer)

    def feed(self, delta: str) -> list[str]:
        """Append newly generated text; return any now-complete clauses."""
        self._buf += str(delta or "")
        out: list[str] = []
        while True:
            # earliest boundary that yields a clause of at least min length;
            # boundaries that come too soon ("OK.") are skipped, not re-found.
            start = 0
            emit_end = -1
            while True:
                m = _BOUNDARY.search(self._buf, start)
                if not m:
                    break
                end = m.end()
                if len(self._buf[:end].strip()) >= self._min:
                    emit_end = end
                    break
                start = end
            if emit_end < 0:
                break
            out.append(self._buf[:emit_end].strip())
            self._buf = self._buf[emit_end:].lstrip()
        # runaway guard: a very long buffer with no boundary still starts speech
        if len(self._buf) >= self._max:
            cut = self._buf.rfind(" ", 0, self._max)
            if cut > self._min:
                out.append(self._buf[:cut].strip())
                self._buf = self._buf[cut:].lstrip()
        return [c for c in out if c]

    def flush(self) -> str:
        """Whatever remains (end of the stream)."""
        rest, self._buf = self._buf.strip(), ""
        return rest


# --- prosody ----------------------------------------------------------------
NEUTRAL, CASUAL, FOCUSED, SERIOUS, URGENT, QUIET = (
    "neutral", "casual", "focused", "serious", "urgent", "quiet")

_URGENT_WORDS = ("urgent", "now", "immediately", "asap", "emergency", "critical",
                 "right away", "hurry")


def delivery_for(*, priority: str = "", urgency: str = "", serious: bool = False,
                 complex_answer: bool = False, casual: bool = False,
                 text: str = "") -> dict[str, Any]:
    """A subtle style + speaking-rate for this turn. Rates stay near 1.0 -- the
    brief is explicit that changes must never be extreme."""
    body = f"{urgency} {text}".lower()
    pri = str(priority or "").upper()

    if pri in ("CRITICAL",) or any(w in body for w in _URGENT_WORDS):
        style, rate = URGENT, 1.05          # clear and direct, a touch quicker
    elif serious or pri in ("HIGH",):
        style, rate = SERIOUS, 0.98
    elif complex_answer:
        style, rate = FOCUSED, 0.96         # slightly slower for a real explanation
    elif casual:
        style, rate = CASUAL, 1.0
    else:
        style, rate = NEUTRAL, 1.0
    return {"style": style, "rate": round(rate, 2)}
