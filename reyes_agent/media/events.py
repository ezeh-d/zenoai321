"""Media panel state + event bus.

`MediaPanelState` is the normalised shape a UI renders: the list of known
sessions, which one is active, and a compact "mini card" for the always-on
corner widget. It is a plain serialisable snapshot -- no live objects -- so it
crosses a WebSocket or a template boundary intact.

`MediaEventBus` is a tiny thread-safe pub/sub. The manager publishes after every
state change; subscribers (a WebSocket broadcaster, the panel, a logger) react.
A bad subscriber can never break publishing or another subscriber. A bounded
ring buffer keeps the most recent events so a client that connects late, or
polls, can catch up.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

# event kinds (documented, not an enum, so payloads stay flexible)
TRACK_CHANGED = "track_changed"
PLAYBACK_CHANGED = "playback_changed"     # play/pause/stop
SESSIONS_CHANGED = "sessions_changed"     # a source appeared/disappeared
VOLUME_CHANGED = "volume_changed"
STATE = "state"                           # a full state push (any change)


@dataclass
class MediaPanelState:
    """Everything a media panel needs, already normalised and JSON-ready."""
    sessions: list[dict[str, Any]] = field(default_factory=list)
    active_app_id: str | None = None
    updated_at: float = 0.0

    @property
    def active(self) -> dict[str, Any] | None:
        for s in self.sessions:
            if s.get("app_id") == self.active_app_id:
                return s
        # fall back to the first playing session, else the first known
        for s in self.sessions:
            if s.get("playing"):
                return s
        return self.sessions[0] if self.sessions else None

    def mini_card(self) -> dict[str, Any] | None:
        """The compact always-on widget: art + title + artist + play state."""
        a = self.active
        if not a:
            return None
        return {
            "source": a.get("source", ""),
            "title": a.get("title", ""),
            "artist": a.get("artist", ""),
            "status": a.get("status", "unknown"),
            "playing": a.get("playing", False),
            "art_path": a.get("art_path", ""),
            "position_s": a.get("position_s", 0.0),
            "duration_s": a.get("duration_s", 0.0),
            "app_id": a.get("app_id", ""),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessions": self.sessions,
            "active_app_id": self.active_app_id,
            "active": self.active,
            "mini_card": self.mini_card(),
            "count": len(self.sessions),
            "any_playing": any(s.get("playing") for s in self.sessions),
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_snapshots(cls, snaps, active_app_id):
        return cls(
            sessions=[s.to_dict() for s in snaps],
            active_app_id=active_app_id,
            updated_at=time.time(),
        )


@dataclass
class MediaEvent:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "payload": self.payload, "ts": self.ts}


class MediaEventBus:
    """Thread-safe fan-out. Subscribers are plain callables `(MediaEvent) -> None`."""

    def __init__(self, *, history: int = 64) -> None:
        self._subs: list[Callable[[MediaEvent], None]] = []
        self._lock = threading.RLock()
        self._history_cap = max(1, history)
        self._history: list[MediaEvent] = []
        self._seq = 0

    def subscribe(self, callback: Callable[[MediaEvent], None]) -> Callable[[], None]:
        """Register a subscriber; returns an unsubscribe function."""
        with self._lock:
            self._subs.append(callback)

        def _off() -> None:
            with self._lock:
                try:
                    self._subs.remove(callback)
                except ValueError:
                    pass
        return _off

    def publish(self, event_type: str, payload: dict[str, Any] | None = None) -> MediaEvent:
        # ts is injected by the caller-free clock; time.time() is fine here
        event = MediaEvent(type=event_type, payload=dict(payload or {}), ts=time.time())
        with self._lock:
            self._seq += 1
            self._history.append(event)
            if len(self._history) > self._history_cap:
                self._history = self._history[-self._history_cap:]
            subs = list(self._subs)
        for cb in subs:
            try:
                cb(event)
            except Exception:  # noqa: BLE001 -- one bad sub never breaks the bus
                continue
        return event

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            return [e.to_dict() for e in self._history[-max(1, limit):]]

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)


_bus: MediaEventBus | None = None
_bus_lock = threading.Lock()


def get_event_bus() -> MediaEventBus:
    global _bus
    if _bus is None:
        with _bus_lock:
            if _bus is None:
                _bus = MediaEventBus()
    return _bus
