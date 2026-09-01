"""Realtime turn-taking intelligence -- the pieces that make ZENO feel instant
and interruptible without an LLM in the reaction path.

Four deterministic components, all local and fast:

  is_turn_complete   -- semantic turn detection: a pause is not the same as
                        "finished" (a trailing "and"/"to" means keep listening).
  PartialIntentEngine-- guess intent from a partial transcript to warm the right
                        handler, with a HARD safety gate: it NEVER prepares or
                        executes a dangerous/irreversible action on speculation.
  BackchannelDetector-- tell a "mhm" apart from an interruption, a correction, a
                        stop, or a real new command while ZENO is speaking.
  micro_ack          -- a short contextual acknowledgement ("got it", "on it"),
                        chosen with anti-repetition, or silence. Not a canned
                        script -- a small situational set, never repeated back-
                        to-back, and empty when a visual already says enough.

These extend (don't replace) the intent router, the coordinator and the
NaturalResponseEngine. Nothing here calls a model.
"""

from __future__ import annotations

import re
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any

# --- semantic turn detection ------------------------------------------------
# A turn that ends on one of these is almost certainly unfinished, whatever the
# silence timer says.
_DANGLING = {
    "and", "or", "but", "so", "to", "the", "a", "an", "with", "for", "of",
    "then", "because", "if", "when", "that", "my", "your", "their", "into",
    "at", "on", "in", "from", "about", "like", "plus", "also", "which", "while",
}
_HESITATION = {"um", "uh", "er", "erm", "hmm", "uhh", "ehm"}


def is_turn_complete(transcript: str) -> dict[str, Any]:
    """Whether the user has (probably) finished, from syntax + wording. Meant to
    combine with VAD silence, not replace it."""
    t = str(transcript or "").strip()
    if not t:
        return {"complete": False, "reason": "empty"}
    if t[-1] in ".?!":
        return {"complete": True, "reason": "terminal punctuation"}
    if t[-1] == ",":
        return {"complete": False, "reason": "trailing comma"}
    words = re.findall(r"[a-z0-9']+", t.lower())
    last = words[-1] if words else ""
    if last in _HESITATION:
        return {"complete": False, "reason": f"hesitation '{last}'"}
    if last in _DANGLING:
        return {"complete": False, "reason": f"dangling '{last}'"}
    return {"complete": True, "reason": "syntactically complete"}


# --- partial intent, with a hard safety gate --------------------------------
# Words that indicate a consequential / irreversible action. On a PARTIAL
# transcript we must never execute these and must not "prepare" them either.
_DANGEROUS = {
    "send", "delete", "remove", "publish", "post", "buy", "purchase", "pay",
    "transfer", "wire", "overwrite", "replace", "format", "wipe", "erase",
    "uninstall", "shutdown", "reboot", "kill", "drop", "revoke", "reset",
    "unsubscribe", "deploy", "email", "message", "text", "call", "share",
}


@dataclass
class PartialIntent:
    partial: str
    candidate: str | None
    capability: str
    confidence: float
    safe_to_prepare: bool
    prepare: list[str] = field(default_factory=list)
    execute: bool = False           # ALWAYS False on a partial -- never commit

    def as_dict(self) -> dict[str, Any]:
        return {"partial": self.partial, "candidate": self.candidate,
                "capability": self.capability, "confidence": round(self.confidence, 3),
                "safe_to_prepare": self.safe_to_prepare, "prepare": self.prepare,
                "execute": self.execute}


class PartialIntentEngine:
    """Anticipate intent from partial speech to warm the right handler. Reuses
    the semantic intent router. Preparation is reversible + read-only only."""

    def consider(self, partial: str, *, context: str = "") -> PartialIntent:
        text = str(partial or "").strip()
        low = text.lower()
        dangerous = any(re.search(rf"\b{re.escape(w)}\b", low) for w in _DANGEROUS)
        candidate, capability, conf = None, "", 0.0
        if len(text) >= 3:
            try:
                from reyes_agent.routing.intent_router import get_intent_router
                match = get_intent_router().classify(text)
                if match:
                    candidate, capability, conf = match.intent, match.capability, match.confidence
            except Exception:  # noqa: BLE001
                pass
        # Safe preparation only when the partial carries no dangerous verb.
        safe = not dangerous
        prepare: list[str] = []
        if safe and capability and conf >= 0.4:
            # read-only / reversible warms only: schema + handler, never an action
            prepare = [f"warm_capability:{capability}"]
            if candidate == "open_app":
                prepare.append("warm:app_registry")
            elif candidate == "open_content":
                prepare.append("warm:file_index")
        return PartialIntent(partial=text, candidate=candidate, capability=capability,
                             confidence=conf, safe_to_prepare=safe, prepare=prepare,
                             execute=False)


# --- backchannel / interruption classification ------------------------------
BACKCHANNEL = "BACKCHANNEL"
INTERRUPT = "INTERRUPT"
CORRECTION = "CORRECTION"
STOP = "STOP"
NEW_COMMAND = "NEW_COMMAND"

_BACKCHANNELS = {
    "yeah", "yep", "yup", "mhm", "mm", "mmhm", "uh huh", "uhhuh", "okay", "ok",
    "right", "sure", "exactly", "cool", "nice", "true", "i see", "gotcha",
    "makes sense", "go on", "and", "aha", "oh", "hmm okay",
}
_STOPS = {"stop", "wait", "hold on", "hold up", "cancel", "never mind",
          "nevermind", "quiet", "shush", "enough", "pause", "shut up"}
_CORRECTIONS = ("no ", "not that", "not the", "i meant", "i mean", "actually",
                "wrong", "the other one", "the other", "no i", "no,", "nope")


def _norm(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", str(s).lower()))


class BackchannelDetector:
    """Classify a short utterance heard WHILE ZENO is speaking (or right after),
    so a listening 'mhm' doesn't get treated as a new command."""

    def classify(self, utterance: str, *, zeno_speaking: bool = False) -> dict[str, Any]:
        raw = str(utterance or "").strip()
        norm = _norm(raw)
        words = norm.split()
        if not norm:
            return {"type": BACKCHANNEL, "reason": "empty", "act": False}

        # stop / cancel -- highest priority, always acted on
        if norm in _STOPS or any(norm.startswith(s) for s in _STOPS):
            return {"type": STOP, "reason": "stop word", "act": True}
        # correction -- modifies the active action
        if any(norm.startswith(c) or c.strip() == norm for c in _CORRECTIONS):
            return {"type": CORRECTION, "reason": "correction phrase", "act": True}
        # backchannel -- only when short AND ZENO is talking; else it's a command
        if zeno_speaking and (norm in _BACKCHANNELS or
                              (len(words) <= 2 and norm in _BACKCHANNELS)):
            return {"type": BACKCHANNEL, "reason": "acknowledgement", "act": False}
        # while ZENO speaks, a substantive utterance is a barge-in
        if zeno_speaking and len(words) >= 2:
            return {"type": INTERRUPT, "reason": "user spoke over ZENO", "act": True}
        if not zeno_speaking and norm in _BACKCHANNELS and len(words) <= 2:
            return {"type": BACKCHANNEL, "reason": "bare acknowledgement", "act": False}
        return {"type": NEW_COMMAND, "reason": "substantive utterance", "act": True}


# --- contextual micro-acknowledgements (anti-repetition) --------------------
_ACKS = {
    "ack": ("got it", "on it", "alright", "sure", "okay", "yep"),
    "done": ("there", "done", "that's done", "all set"),
    "searching": ("one sec", "looking", "checking"),
    "found": ("found it", "here", "got it"),
    "thinking": ("hmm", "let me see", "one moment"),
}


class MicroAck:
    """A short acknowledgement for a situation, never repeated back-to-back, and
    empty (silence) when a visual already communicates the action."""

    def __init__(self, maxlen: int = 8) -> None:
        self._recent: deque[str] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def pick(self, situation: str = "ack", *, visual_shown: bool = False) -> str:
        if visual_shown:
            return ""                        # the panel/orb already said it
        pool = _ACKS.get(situation, _ACKS["ack"])
        with self._lock:
            fresh = [a for a in pool if a not in self._recent]
            choice = fresh[0] if fresh else pool[0]
            self._recent.append(choice)
        return choice


_micro = MicroAck()
_partial = PartialIntentEngine()
_backchannel = BackchannelDetector()


def micro_ack(situation: str = "ack", *, visual_shown: bool = False) -> str:
    return _micro.pick(situation, visual_shown=visual_shown)


def partial_intent(partial: str, *, context: str = "") -> dict[str, Any]:
    return _partial.consider(partial, context=context).as_dict()


def classify_utterance(utterance: str, *, zeno_speaking: bool = False) -> dict[str, Any]:
    return _backchannel.classify(utterance, zeno_speaking=zeno_speaking)
