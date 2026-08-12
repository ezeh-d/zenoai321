"""Fast English/Nigerian-English/Pidgin boundary heuristic.

TEN Turn Detection currently requires a Qwen2.5-7B stack.  That is rejected
from this machine's realtime path, so this bounded lexical decision runs only
after STT produces a stable final near a VAD boundary.
"""

from __future__ import annotations

import re

FINISHED = "FINISHED"
UNFINISHED = "UNFINISHED"
WAIT = "WAIT"

_WAIT = re.compile(
    r"^(?:wait|hold on|hang on|one (?:second|sec|minute)|give me a (?:second|sec|minute)|"
    r"make i think|abeg wait(?: first)?|no wait|wait first)[.!…\s-]*$", re.I,
)
_TRAILING_CONTINUATIONS = {
    "and", "but", "or", "because", "so", "then", "with", "without", "for", "from", "to",
    "about", "if", "when", "where", "which", "that", "like", "maybe", "plus", "wey", "say",
    "make", "abi", "sha", "except", "while", "after", "before",
}
_OPEN_PHRASES = (
    "i was thinking", "i dey think", "what if", "the thing is", "first of all",
    "can you help me to", "i need you to", "i want you to", "make we",
)


def detect(text: str) -> dict:
    raw = " ".join(str(text or "").strip().split())
    lowered = raw.casefold()
    if not raw:
        return {"state": UNFINISHED, "confidence": 1.0, "reason": "empty transcript", "backend": "heuristic-v1"}
    if _WAIT.fullmatch(raw):
        return {"state": WAIT, "confidence": 0.96, "reason": "explicit hold phrase", "backend": "heuristic-v1"}
    if raw.endswith(("...", "…", ",", ";", ":", "—", "-")):
        return {"state": UNFINISHED, "confidence": 0.91, "reason": "open trailing punctuation", "backend": "heuristic-v1"}
    words = re.findall(r"[\w']+", lowered)
    if words and words[-1] in _TRAILING_CONTINUATIONS:
        return {"state": UNFINISHED, "confidence": 0.88, "reason": f"trailing continuation '{words[-1]}'", "backend": "heuristic-v1"}
    if any(lowered.endswith(phrase) for phrase in _OPEN_PHRASES):
        return {"state": UNFINISHED, "confidence": 0.82, "reason": "unfinished framing phrase", "backend": "heuristic-v1"}
    if raw.endswith((".", "?", "!")):
        return {"state": FINISHED, "confidence": 0.95, "reason": "terminal punctuation", "backend": "heuristic-v1"}
    # A final transcription without an open lexical tail is normally a
    # complete natural utterance even when the provider omitted punctuation.
    confidence = 0.80 if len(words) >= 2 else 0.68
    return {"state": FINISHED, "confidence": confidence, "reason": "closed stable transcript", "backend": "heuristic-v1"}
