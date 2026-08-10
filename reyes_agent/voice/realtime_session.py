"""The real-time conversation session -- backend-agnostic.

WHY LIVEKIT IS A BACKEND AND NOT THE ARCHITECTURE
-------------------------------------------------
The brief is explicit that LiveKit must be the communication layer, not
ZENO's identity or reasoning. So this module owns the SESSION -- is a
conversation open, whose turn is it, may ZENO speak, when does it end --
and delegates the actual audio transport to whichever backend is
configured.

The default backend is LOCAL, and that is a measured decision rather than a
preference: microphone, speakers and brain are all on this machine, so
routing audio out to a LiveKit room and back adds a network round trip to a
path Codex measured at 1.40s end to end. LiveKit earns its place when the
audio genuinely is remote -- the phone companion at app.zenoassitant.com.

WHAT THIS DOES NOT REIMPLEMENT
------------------------------
Barge-in, endpointing, self-echo rejection, VAD calibration and the central
speech queue already exist and work (`voice_manager`, `vad.js`,
`conversation_state`, the browser endpointing rules). This coordinates them;
it does not replace them.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

LOCAL, LIVEKIT = "local", "livekit"

# Conversation stays open until the owner says standby -- not until one
# exchange ends. Anything longer than this without a word is treated as the
# session having quietly ended, so a forgotten session cannot hold the mic.
IDLE_TIMEOUT_S = 900.0

PUSH_TO_TALK, CONVERSATION = "push_to_talk", "conversation"


@dataclass
class Session:
    id: str
    backend: str = LOCAL
    mode: str = CONVERSATION
    started_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    turns: int = 0
    open: bool = True
    ended_reason: str = ""

    @property
    def idle_s(self) -> float:
        return time.time() - self.last_activity

    def as_dict(self) -> dict[str, Any]:
        return {"session_id": self.id, "backend": self.backend, "mode": self.mode,
                "open": self.open, "turns": self.turns,
                "duration_s": round(time.time() - self.started_at, 1),
                "idle_s": round(self.idle_s, 1), "ended_reason": self.ended_reason}


_lock = threading.Lock()
_session: Session | None = None

# Phrases that close a session. Kept here rather than in the browser so
# voice and text agree on what "stop" means.
STANDBY = (
    "standby", "stand by", "go to sleep", "sleep now", "stop listening",
    "goodbye zeno", "that's all", "thats all", "we're done", "were done",
    "dismissed", "zeno off",
)


def backend() -> str:
    """Which transport is actually in use."""
    from reyes_agent import integrations

    if integrations.LIVEKIT_ENABLED and integrations.available("livekit.agents"):
        return LIVEKIT
    return LOCAL


def start(mode: str = CONVERSATION) -> Session:
    """Open a conversation, or return the one already open.

    Idempotent on purpose: a second wake word while a session is live must
    not create a second session competing for the same microphone.
    """
    global _session
    with _lock:
        if _session is not None and _session.open and _session.idle_s < IDLE_TIMEOUT_S:
            _session.last_activity = time.time()
            return _session
        _session = Session(id=uuid.uuid4().hex[:12], backend=backend(),
                           mode=mode if mode in {PUSH_TO_TALK, CONVERSATION} else CONVERSATION)
    _emit("started", _session)
    return _session


def touch(turn: bool = False) -> Session | None:
    """Mark activity. `turn=True` counts a completed exchange."""
    with _lock:
        if _session is None or not _session.open:
            return None
        _session.last_activity = time.time()
        if turn:
            _session.turns += 1
        return _session


def is_standby(text: str) -> bool:
    """Did the owner just end the conversation?"""
    cleaned = " ".join(str(text or "").lower().split()).strip(" .!?,")
    return any(cleaned == phrase or cleaned.endswith(" " + phrase) for phrase in STANDBY)


def end(reason: str = "standby") -> Session | None:
    """Close the session and release the microphone."""
    global _session
    with _lock:
        if _session is None or not _session.open:
            return None
        _session.open = False
        _session.ended_reason = reason
        closing = _session
    # Stop anything still speaking through the EXISTING central queue.
    try:
        from reyes_agent import voice_manager

        voice_manager.cancel_current()
    except Exception:  # noqa: BLE001 -- teardown must not raise
        pass
    _emit("ended", closing)
    return closing


def current() -> Session | None:
    """The LIVE session, or None.

    A closed session is not a current one: callers ask this to find out
    whether a conversation is open, and handing back an ended session made
    "are we still talking?" answer yes forever.
    """
    with _lock:
        if _session is None or not _session.open:
            return None
        stale = _session.idle_s > IDLE_TIMEOUT_S
        if not stale:
            return _session
    # Gone quiet for too long -- close it so the microphone is released.
    end("idle timeout")
    return None


def barge_in(source: str = "user") -> dict[str, Any]:
    """The owner started talking while ZENO was speaking.

    Routed through the existing conversation state machine so the
    interrupted turn is CLOSED -- its late events are then rejected as
    stale and cancelled audio cannot resume.
    """
    touch()
    try:
        from reyes_agent import conversation_state

        transition = conversation_state.barge_in(source=source)
        return {"ok": transition.ok, "state": conversation_state.current(),
                "reason": transition.reason}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "state": "unknown", "reason": f"{type(exc).__name__}: {exc}"}


def _emit(action: str, session: Session) -> None:
    try:
        from reyes_agent import event_bus

        event_bus.publish("voice.session", {"action": action, **session.as_dict()},
                          source="realtime_session", correlation_id=session.id)
    except Exception:  # noqa: BLE001
        pass


def status() -> dict[str, Any]:
    from reyes_agent import integrations

    live = current()
    return {
        "backend": backend(),
        "livekit_enabled": integrations.LIVEKIT_ENABLED,
        "livekit_installed": integrations.available("livekit.agents"),
        "session": live.as_dict() if live else None,
        "modes": [PUSH_TO_TALK, CONVERSATION],
        "idle_timeout_s": IDLE_TIMEOUT_S,
        "note": ("Local transport by default: mic, speakers and brain are on one machine, "
                 "so a LiveKit room would add a network round trip to a 1.40s path. "
                 "LiveKit is for remote audio (the phone companion)."),
    }


def reset() -> None:
    """Test hook."""
    global _session
    with _lock:
        _session = None
