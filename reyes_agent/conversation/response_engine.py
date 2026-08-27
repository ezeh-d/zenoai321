"""NaturalResponseEngine -- one place that decides whether ZENO speaks and, if
so, generates the words from FACTS + CONTEXT + PERSONALITY. Subsystems send a
structured Event; they never hand ZENO a finished sentence.

WHAT THIS EXTENDS (never replaces)
----------------------------------
    personality.VOICE_CUE   -- the anti-robotic style layer (#12)
    provider.run_turn       -- dynamic generation, fast + deep (#17)
    conversation_state      -- is ZENO already speaking? (#15)
    privacy.detector        -- don't read OTPs/secrets aloud (#8)
    voice.narration         -- tool-action narration already exists (#10/#11)

THE ONE IDEA
------------
Events provide facts. Tools provide facts. Memory provides context. Personality
provides style. This engine produces the actual communication -- and often
decides the best communication is a visual, a quiet queue, or silence, not
speech (#2, #13). It teaches ZENO HOW to decide what to say, not thousands of
sentences.

FAST BY DEFAULT
---------------
Trivial events (an app opened, volume changed, a timer) are phrased locally from
their own facts with light variation -- no model call. Only messages, questions,
alerts and data that need reasoning reach the model. Model generation is
injectable so this stays testable and never blocks on the network.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

# --- priority levels (#15) ---------------------------------------------------
CRITICAL = "CRITICAL"
HIGH = "HIGH"
NORMAL = "NORMAL"
LOW = "LOW"
SILENT = "SILENT"
_ORDER = {SILENT: 0, LOW: 1, NORMAL: 2, HIGH: 3, CRITICAL: 4}

# --- actions ZENO can choose (#2) -------------------------------------------
SPEAK = "SPEAK"          # say it out loud
SHOW = "SHOW"            # visual panel only, no speech
WAIT = "WAIT"            # queue until a natural break in conversation
QUIET = "QUIET"          # record it silently (notice), no speech, no panel
ASK = "ASK"              # speak AND expect an answer
ACT = "ACT"              # a pre-authorized action handles it; no speech needed
NOTHING = "NOTHING"      # not worth surfacing at all

# Event kinds that are trivial enough to phrase locally (no model, #17).
_SIMPLE_KINDS = frozenset({
    "app_opened", "app_closed", "volume_changed", "brightness_changed",
    "music_changed", "music_paused", "track_changed", "timer_finished",
    "tool_ack", "file_op", "screenshot",
})
# Kinds where a visual panel carries the weight; speech is optional/short (#14).
_VISUAL_KINDS = frozenset({
    "track_changed", "music_changed", "incoming_call", "system_alert",
    "now_playing",
})


@dataclass
class Event:
    """The structured context a subsystem sends. Facts only -- never a sentence."""
    kind: str
    app: str = ""
    sender: str = ""
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    context: str = ""          # what was happening just before (#6)
    relationship: str = ""     # close/coworker/business/unknown/system (#7)
    user_activity: str = ""    # idle / typing / in_call / speaking ...
    urgency: str = ""          # explicit urgency if the source knows it
    priority: str = ""         # explicit override; else classified
    timestamp: float = field(default_factory=time.time)


@dataclass
class Decision:
    action: str
    speech: str = ""
    visual: dict[str, Any] = field(default_factory=dict)
    priority: str = NORMAL
    reason: str = ""
    kind: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"action": self.action, "speech": self.speech, "visual": self.visual,
                "priority": self.priority, "reason": self.reason, "kind": self.kind}


# --- signals about the world (best-effort; never raise) ---------------------
def _zeno_busy() -> bool:
    """Is ZENO mid-utterance or in an active exchange? Then NORMAL/LOW should
    queue rather than barge in (#15)."""
    try:
        from reyes_agent import conversation_state as cs
        return cs.is_active()
    except Exception:  # noqa: BLE001
        return False


def _is_sensitive(text: str) -> bool:
    """OTP / card / secret in the text -> never read it aloud (#8). Checks the
    privacy detector AND an OTP heuristic, so a code slips through neither."""
    import re

    text = str(text or "")
    if not text:
        return False
    try:
        from reyes_agent.security.privacy import detector
        if detector.detect(text):
            return True
    except Exception:  # noqa: BLE001
        pass
    low = text.lower()
    return bool(re.search(r"\b\d{4,8}\b", text) and
                any(w in low for w in ("otp", "code", "verification", "password",
                                       "pin", "one-time", "2fa", "passcode")))


_URGENT_WORDS = ("urgent", "asap", "now", "emergency", "before", "deadline",
                 "today", "right away", "immediately", "call me")


def _looks_urgent(ev: Event) -> bool:
    body = f"{ev.message} {ev.urgency} {ev.data.get('text', '')}".lower()
    return any(w in body for w in _URGENT_WORDS)


# --- model generation (injectable; #17 deep path) ---------------------------
def _model_generate(ev: Event, priority: str, recent: list[str]) -> str:
    """Generate ONE natural line via the fast conversational model, in ZENO's
    voice, avoiding recent phrasings. Returns '' on any failure so the caller
    falls back locally (#18)."""
    try:
        from reyes_agent import personality, provider

        avoid = ""
        if recent:
            avoid = (" Do not reuse the shape or opening of these recent lines: "
                     + " / ".join(f'"{r}"' for r in recent[-4:]) + ".")
        length = {"CRITICAL": "Be immediate and clear.",
                  "HIGH": "One brief sentence.",
                  }.get(priority, "One short, natural sentence.")
        system = (
            personality.VOICE_CUE
            + " You are ZENO relaying a real-world event to the owner out loud. "
            "Say only what actually matters, generated from the facts below. "
            + length +
            " Never say 'Sir', 'you have a new message', 'what is your reply', "
            "'command completed', or 'processing your request'. Do not end with a "
            "question unless an answer is genuinely needed." + avoid)
        history = [{"role": "user", "content": _facts_block(ev)}]
        turn = provider.run_turn(history, system=system, tools=[], task_kind="notify")
        text = (getattr(turn, "text", "") or getattr(turn, "reply", "") or "").strip()
        # Guard: never let a stock phrase through even if the model slips.
        return "" if _is_stock(text) else text
    except Exception:  # noqa: BLE001
        return ""


def _facts_block(ev: Event) -> str:
    bits = [f"event: {ev.kind}"]
    for label, value in (("app", ev.app), ("from", ev.sender),
                         ("relationship", ev.relationship),
                         ("message", ev.message), ("urgency", ev.urgency),
                         ("just before", ev.context),
                         ("owner is", ev.user_activity)):
        if value:
            bits.append(f"{label}: {value}")
    for key, value in (ev.data or {}).items():
        bits.append(f"{key}: {value}")
    return "\n".join(bits)


_STOCK = ("what's your reply", "what is your reply", "you have a new message",
          "how may i assist", "command completed", "processing your request",
          "according to your request", "you have received a notification")


def _is_stock(text: str) -> bool:
    low = str(text or "").lower()
    return any(s in low for s in _STOCK)


class NaturalResponseEngine:
    def __init__(self, *, generate: Callable[..., str] | None = None,
                 now: Callable[[], float] | None = None) -> None:
        self._recent: deque[str] = deque(maxlen=12)     # anti-repetition (#16)
        self._recent_events: deque[tuple[str, str, float]] = deque(maxlen=32)
        self._pending: list[Event] = []                 # batch queue (#2/#15)
        self._generate = generate or _model_generate
        self._now = now or time.time

    # -- priority (#15) ----------------------------------------------------
    def classify(self, ev: Event) -> str:
        if ev.priority in _ORDER:
            return ev.priority
        kind = ev.kind
        if kind in ("system_critical", "emergency", "safety_warning", "security_alert"):
            return CRITICAL
        if kind in ("incoming_call",):
            return HIGH
        if kind in ("message_received", "email_received", "dm_received"):
            return HIGH if _looks_urgent(ev) else NORMAL
        if kind in ("system_alert", "error", "agent_needs_input"):
            return HIGH if _looks_urgent(ev) else NORMAL
        if kind in _SIMPLE_KINDS:
            return SILENT if kind in ("track_changed", "music_changed") else LOW
        return NORMAL

    # -- duplicate suppression (#2) ---------------------------------------
    def _is_duplicate(self, ev: Event) -> bool:
        sig = f"{ev.kind}|{ev.app}|{ev.sender}|{ev.message}".strip("|")
        now = self._now()
        for k, s, t in self._recent_events:
            if s == sig and now - t < 20.0:
                return True
        self._recent_events.append((ev.kind, sig, now))
        return False

    # -- action choice (think before speaking, #13) ----------------------
    def _choose_action(self, ev: Event, priority: str) -> tuple[str, str]:
        if priority == SILENT:
            return (SHOW if ev.kind in _VISUAL_KINDS else QUIET,
                    "not worth speech")
        if priority == CRITICAL:
            return SPEAK, "critical -- interrupt immediately"
        if _zeno_busy() and _ORDER[priority] <= _ORDER[NORMAL]:
            return WAIT, "ZENO is mid-conversation; queue until a break"
        return SPEAK, "surface now"

    # -- phrasing ----------------------------------------------------------
    def _phrase(self, ev: Event, priority: str) -> str:
        # Privacy first: sensitive content is never read aloud (#8).
        if _is_sensitive(ev.message) or _is_sensitive(ev.data.get("text", "")):
            return self._local(ev, priority, privacy=True)
        if ev.kind in _SIMPLE_KINDS:            # fast local path, no model (#17)
            return self._local(ev, priority)
        try:
            line = self._generate(ev, priority, list(self._recent))   # model (#17 deep)
        except Exception:  # noqa: BLE001 -- a model failure falls back, not crashes
            line = ""
        if line and not _is_stock(line):        # a stock phrase never gets through (#3)
            return line
        return self._local(ev, priority)                          # fallback (#18)

    def _local(self, ev: Event, priority: str, *, privacy: bool = False) -> str:
        """Short, factual lines built from THIS event's own facts, with light
        structural variation and anti-repetition. Not a personality store -- a
        fast/fallback constructor for trivial or degraded cases (#17/#18)."""
        who = ev.sender or ev.app
        if privacy:
            return self._vary(ev, [
                "A code just came through -- it's on screen, not out loud.",
                f"Something private landed{f' from {ev.app}' if ev.app else ''} -- I'll keep it on screen.",
                "There's a verification code waiting; I won't read it aloud."])
        if ev.kind in ("app_opened",):
            name = ev.app or ev.data.get("name", "it")
            return self._vary(ev, [f"Opening {name}.", f"{name}, coming up.", f"Got it -- {name}."])
        if ev.kind in ("music_paused",):
            return self._vary(ev, ["Paused.", "Music's paused."])
        if ev.kind in ("timer_finished",):
            label = ev.data.get("label", "")
            return self._vary(ev, [f"Timer's up{f' -- {label}' if label else ''}.",
                                   f"That's time{f' on {label}' if label else ''}."])
        if ev.kind in ("volume_changed", "brightness_changed"):
            return ""  # a slider moved -- visual is enough, usually silent
        if ev.kind in ("tool_ack",):
            return self._vary(ev, ["Got it.", "On it.", "Done."])
        if ev.kind in ("message_received", "email_received", "dm_received"):
            src = ev.app or "a message"
            return self._vary(ev, [
                f"{who} messaged you." if who else f"Something came in on {src}.",
                f"There's a message from {who}." if who else f"New message on {src}."])
        # generic factual fallback
        return self._vary(ev, [f"Heads up -- {ev.kind.replace('_', ' ')}.",
                               f"Something just happened: {ev.kind.replace('_', ' ')}."])

    def _vary(self, ev: Event, choices: list[str]) -> str:
        """Pick a variant not used recently -- deterministic per event content so
        it's stable within a turn but rotates across events (like the existing
        latency_governor.reply_for)."""
        fresh = [c for c in choices if c and c not in self._recent]
        pool = fresh or [c for c in choices if c]
        if not pool:
            return ""
        seed = f"{ev.kind}{ev.sender}{ev.message}{len(self._recent)}"
        return pool[sum(map(ord, seed)) % len(pool)]

    def _remember(self, line: str) -> None:
        if line:
            self._recent.append(line)

    # -- public API --------------------------------------------------------
    def respond(self, ev: Event) -> Decision:
        """Decide + phrase a single event. Never raises."""
        try:
            priority = self.classify(ev)
            if self._is_duplicate(ev):
                return Decision(NOTHING, "", {}, priority, "duplicate within 20s", ev.kind)
            action, reason = self._choose_action(ev, priority)
            speech = ""
            if action in (SPEAK, ASK):
                speech = self._phrase(ev, priority)
                self._remember(speech)
                if not speech:                 # phrasing decided silence
                    action = SHOW if ev.kind in _VISUAL_KINDS else QUIET
            visual = _visual_for(ev)
            return Decision(action, speech, visual, priority, reason, ev.kind)
        except Exception as exc:  # noqa: BLE001 -- the engine must never break a caller
            return Decision(QUIET, "", {}, NORMAL, f"engine error: {type(exc).__name__}",
                            getattr(ev, "kind", ""))

    def ingest(self, ev: Event) -> Decision:
        """Batch path: a WAIT decision is held; the caller flushes at a break."""
        decision = self.respond(ev)
        if decision.action == WAIT:
            self._pending.append(ev)
        return decision

    def flush(self) -> Decision | None:
        """Coalesce everything queued into ONE line (#2: five unimportant
        notifications become 'a few notifications, nothing urgent')."""
        if not self._pending:
            return None
        pending, self._pending = self._pending, []
        if len(pending) == 1:
            return self.respond(pending[0])
        top = max(_ORDER[self.classify(e)] for e in pending)
        urgent = top >= _ORDER[HIGH]
        senders = [e.sender for e in pending if e.sender]
        n = len(pending)
        if urgent:
            line = self._vary(pending[-1], [
                f"A few things came in -- one looks like it needs you.",
                f"{n} notifications; at least one's worth a look."])
        else:
            line = self._vary(pending[-1], [
                "You've got a few notifications -- nothing urgent.",
                f"{n} things came in, none pressing.",
                "A handful of notifications piled up; nothing that can't wait."])
        self._remember(line)
        return Decision(SPEAK, line, {}, HIGH if urgent else LOW,
                        f"coalesced {n} queued events", "batch")


def _visual_for(ev: Event) -> dict[str, Any]:
    """Panel payload when a visual is the right channel (#14)."""
    if ev.kind in ("track_changed", "now_playing", "music_changed"):
        return {"panel": "now_playing", "title": ev.data.get("title", ""),
                "artist": ev.data.get("artist", "")}
    if ev.kind == "incoming_call":
        return {"panel": "caller", "name": ev.sender or "Unknown"}
    if ev.kind == "app_opened":
        return {"panel": "status", "text": f"Opening {ev.app or ev.data.get('name', '')}".strip()}
    return {}


# Module-level singleton + convenience -- subsystems just call respond(Event(...)).
_engine = NaturalResponseEngine()


def respond(event: Event) -> Decision:
    return _engine.respond(event)


def ingest(event: Event) -> Decision:
    return _engine.ingest(event)


def flush() -> Decision | None:
    return _engine.flush()


def engine() -> NaturalResponseEngine:
    return _engine
