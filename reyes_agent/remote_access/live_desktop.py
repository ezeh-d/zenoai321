"""Bounded signalling authority for ZENO Anywhere live desktop sessions.

Video/audio never pass through this module.  It stores only short-lived
WebRTC signalling messages and a privacy-safe session projection.  The
browser and Windows node exchange encrypted media directly through WebRTC
(or a configured TURN relay), while the existing authenticated gateway is
used only to authenticate, authorize and rendezvous the two peers.

The v1 gateway is deliberately single-process.  These ephemeral sessions do
not survive a gateway restart; the phone creates a fresh peer connection,
which is safer than resurrecting an unattended control session.
"""
from __future__ import annotations

import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any


MAX_SESSIONS = 4
MAX_SIGNALS = 64
SESSION_TTL_S = 10 * 60
MAX_SESSION_TTL_S = 30 * 60
CAPABILITY_TTL_S = 75.0
PRESENCE_TTL_S = 75.0
MAX_SDP_CHARS = 256_000

REQUESTED = "REQUESTED"
OFFERED = "OFFERED"
CONNECTING = "CONNECTING"
CONNECTED = "CONNECTED"
DEGRADED = "DEGRADED"
FAILED = "FAILED"
ENDED = "ENDED"
EXPIRED = "EXPIRED"
TERMINAL = {FAILED, ENDED, EXPIRED}
MODES = {"VIEW_ONLY", "REMOTE_CONTROL", "ZENO_CONTROL"}
QUALITIES = {"LOW", "BALANCED", "HIGH"}
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")
_SAFE_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class LiveDesktopError(RuntimeError):
    pass


class SessionNotFound(LiveDesktopError):
    pass


class SessionAccessDenied(LiveDesktopError):
    pass


class SessionCapacityExceeded(LiveDesktopError):
    pass


def _safe_id(value: Any, label: str) -> str:
    clean = str(value or "").strip()
    if not _SAFE_ID.fullmatch(clean):
        raise ValueError(f"Invalid {label}.")
    return clean


def _clean_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _signal(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("A signalling object is required.")
    kind = str(raw.get("type", "")).casefold()
    if kind in {"offer", "answer"}:
        sdp = str(raw.get("sdp", ""))
        if not sdp or len(sdp) > MAX_SDP_CHARS or "v=0" not in sdp[:200]:
            raise ValueError("Invalid or oversized WebRTC session description.")
        return {"type": kind, "sdp": sdp}
    if kind == "candidate":
        candidate = str(raw.get("candidate", ""))[:4096]
        if not candidate:
            raise ValueError("ICE candidate is empty.")
        return {
            "type": "candidate", "candidate": candidate,
            "sdpMid": str(raw.get("sdpMid", ""))[:64],
            "sdpMLineIndex": max(0, min(int(raw.get("sdpMLineIndex", 0) or 0), 32)),
        }
    if kind == "end_of_candidates":
        return {"type": kind}
    raise ValueError("Unsupported WebRTC signalling message.")


@dataclass
class Signal:
    sequence: int
    message: dict[str, Any]
    at: float = field(default_factory=time.time)

    def public(self) -> dict[str, Any]:
        return {"sequence": self.sequence, "at": self.at, **self.message}


@dataclass
class Session:
    id: str
    browser_device: str
    target_device: str
    mode: str
    monitor: str
    quality: str
    show_cursor: bool
    stream_audio: bool
    created: float
    expires: float
    state: str = REQUESTED
    claimed: bool = False
    ended_reason: str = ""
    updated: float = 0.0
    fps: float = 0.0
    measured_quality: str = ""
    error: str = ""
    browser_signals: list[Signal] = field(default_factory=list)
    device_signals: list[Signal] = field(default_factory=list)
    browser_sequence: int = 0
    device_sequence: int = 0

    def owner_view(self) -> dict[str, Any]:
        return {
            "id": self.id, "device_id": self.target_device,
            "mode": self.mode, "monitor": self.monitor,
            "quality": self.quality, "show_cursor": self.show_cursor,
            "stream_audio": self.stream_audio, "state": self.state,
            "created": self.created, "expires": self.expires,
            "updated": self.updated or self.created, "fps": round(self.fps, 1),
            "measured_quality": self.measured_quality or self.quality,
            "error": self.error[:180], "active": self.state not in TERMINAL,
        }


class LiveDesktopManager:
    """Short-lived owner/device rendezvous with strict ownership checks."""

    def __init__(self, *, maximum: int = MAX_SESSIONS) -> None:
        self._maximum = max(1, min(int(maximum), 8))
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._sessions: dict[str, Session] = {}
        self._capabilities: dict[str, dict[str, Any]] = {}
        self._presence: dict[str, dict[str, Any]] = {}

    def register_capabilities(self, device_id: str, raw: dict[str, Any]) -> dict[str, Any]:
        device = _safe_id(device_id, "device id")
        monitors: list[dict[str, Any]] = []
        for index, item in enumerate(raw.get("monitors") if isinstance(raw.get("monitors"), list) else []):
            if not isinstance(item, dict) or len(monitors) >= 12:
                continue
            width = max(1, min(int(item.get("width", 0) or 0), 16_384))
            height = max(1, min(int(item.get("height", 0) or 0), 16_384))
            monitors.append({
                "id": _clean_text(item.get("id") or f"display-{index + 1}", 32),
                "label": _clean_text(item.get("label") or f"Display {index + 1}", 64),
                "width": width, "height": height,
                "primary": bool(item.get("primary")),
            })
        cap = {
            "available": bool(raw.get("available")),
            "detail": _clean_text(raw.get("detail"), 180),
            "monitors": monitors,
            "streaming_enabled": bool(raw.get("streaming_enabled")),
            "control_enabled": bool(raw.get("control_enabled")),
            "audio_available": bool(raw.get("audio_available")),
            "active_display": _clean_text(raw.get("active_display"), 32),
            "at": time.time(),
        }
        with self._changed:
            self._capabilities[device] = cap
            self._changed.notify_all()
        return dict(cap)

    def capabilities(self, device_id: str) -> dict[str, Any]:
        device = _safe_id(device_id, "device id")
        with self._lock:
            cap = dict(self._capabilities.get(device) or {})
        if not cap:
            return {"available": False, "state": "NOT_REPORTED", "monitors": [],
                    "detail": "The Windows live-desktop node has not reported capabilities."}
        stale = time.time() - float(cap.get("at") or 0) > CAPABILITY_TTL_S
        cap["state"] = "STALE" if stale else ("READY" if cap.get("available") else "UNAVAILABLE")
        cap["available"] = bool(cap.get("available")) and not stale
        return cap

    def create(self, *, browser_device: str, target_device: str,
               mode: str = "VIEW_ONLY", monitor: str = "display-1",
               quality: str = "BALANCED", show_cursor: bool = True,
               stream_audio: bool = False, ttl_s: float = SESSION_TTL_S) -> Session:
        browser = _safe_id(browser_device, "browser device")
        target = _safe_id(target_device, "target device")
        selected_mode = str(mode or "VIEW_ONLY").upper()
        selected_quality = str(quality or "BALANCED").upper()
        if selected_mode not in MODES:
            raise ValueError("Invalid live desktop mode.")
        if selected_quality not in QUALITIES:
            raise ValueError("Invalid stream quality.")
        selected_monitor = _clean_text(monitor, 32) or "display-1"
        now = time.time()
        expires = now + max(60.0, min(float(ttl_s), MAX_SESSION_TTL_S))
        with self._changed:
            self._purge_locked(now)
            active = [row for row in self._sessions.values() if row.state not in TERMINAL]
            # One owner browser and one Windows node each have at most one
            # active peer. Replacing an earlier peer is deterministic and
            # prevents hidden duplicate capture/control sessions.
            for row in active:
                if row.browser_device == browser or row.target_device == target:
                    row.state = ENDED
                    row.ended_reason = "replaced by a newer owner session"
                    row.updated = now
            remaining = [row for row in active if row.state not in TERMINAL]
            if len(remaining) >= self._maximum:
                raise SessionCapacityExceeded("Too many live desktop sessions are already active.")
            session = Session(
                id=f"lds_{secrets.token_urlsafe(18)}", browser_device=browser,
                target_device=target, mode=selected_mode, monitor=selected_monitor,
                quality=selected_quality, show_cursor=bool(show_cursor),
                stream_audio=bool(stream_audio), created=now, expires=expires,
                updated=now,
            )
            self._sessions[session.id] = session
            self._changed.notify_all()
            return session

    def session_for_owner(self, session_id: str, browser_device: str) -> Session:
        browser = _safe_id(browser_device, "browser device")
        with self._lock:
            self._purge_locked()
            session = self._sessions.get(str(session_id or ""))
            if session is None:
                raise SessionNotFound("Live desktop session does not exist.")
            if session.browser_device != browser:
                raise SessionAccessDenied("This browser does not own the live desktop session.")
            return session

    def owner_signal(self, session_id: str, browser_device: str,
                     raw: dict[str, Any]) -> dict[str, Any]:
        message = _signal(raw)
        with self._changed:
            session = self.session_for_owner(session_id, browser_device)
            if session.state in TERMINAL:
                raise SessionNotFound("Live desktop session is no longer active.")
            if message["type"] == "offer" and any(
                    signal.message.get("type") == "offer" for signal in session.browser_signals):
                raise ValueError("This session already has a WebRTC offer.")
            session.browser_sequence += 1
            session.browser_signals.append(Signal(session.browser_sequence, message))
            session.browser_signals[:] = session.browser_signals[-MAX_SIGNALS:]
            session.updated = time.time()
            if message["type"] == "offer":
                session.state = OFFERED
            self._changed.notify_all()
            return {"ok": True, "sequence": session.browser_sequence, "state": session.state}

    def claim(self, device_id: str, *, wait_s: float = 20.0) -> dict[str, Any] | None:
        device = _safe_id(device_id, "device id")
        deadline = time.monotonic() + max(0.0, min(float(wait_s), 25.0))
        with self._changed:
            while True:
                now = time.time()
                self._purge_locked(now)
                for session in self._sessions.values():
                    if (session.target_device == device and session.state == OFFERED
                            and not session.claimed and session.expires > now):
                        offer = next((signal.message for signal in session.browser_signals
                                      if signal.message.get("type") == "offer"), None)
                        if not offer:
                            continue
                        session.claimed = True
                        session.state = CONNECTING
                        session.updated = now
                        return {
                            **session.owner_view(), "offer": dict(offer),
                            "control_allowed": session.mode == "REMOTE_CONTROL",
                        }
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._changed.wait(min(remaining, 2.0))

    def device_signal(self, session_id: str, device_id: str,
                      raw: dict[str, Any]) -> dict[str, Any]:
        device = _safe_id(device_id, "device id")
        message = _signal(raw)
        with self._changed:
            self._purge_locked()
            session = self._sessions.get(str(session_id or ""))
            if session is None or session.target_device != device:
                raise SessionAccessDenied("Device is not assigned to this live desktop session.")
            if session.state in TERMINAL:
                raise SessionNotFound("Live desktop session is no longer active.")
            session.device_sequence += 1
            session.device_signals.append(Signal(session.device_sequence, message))
            session.device_signals[:] = session.device_signals[-MAX_SIGNALS:]
            session.updated = time.time()
            self._changed.notify_all()
            return {"ok": True, "sequence": session.device_sequence, "state": session.state}

    def owner_signals(self, session_id: str, browser_device: str, *,
                      after: int = 0, wait_s: float = 20.0) -> dict[str, Any]:
        deadline = time.monotonic() + max(0.0, min(float(wait_s), 25.0))
        with self._changed:
            while True:
                session = self.session_for_owner(session_id, browser_device)
                rows = [signal.public() for signal in session.device_signals
                        if signal.sequence > int(after)]
                if rows or session.state in TERMINAL:
                    return {"signals": rows, "state": session.state,
                            "active": session.state not in TERMINAL}
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return {"signals": [], "state": session.state, "active": True}
                self._changed.wait(min(remaining, 2.0))

    def device_status(self, session_id: str, device_id: str, *, state: str,
                      fps: float = 0.0, quality: str = "", error: str = "") -> dict[str, Any]:
        device = _safe_id(device_id, "device id")
        selected = str(state or "").upper()
        if selected not in {CONNECTING, CONNECTED, DEGRADED, FAILED, ENDED}:
            selected = DEGRADED
        with self._changed:
            self._purge_locked()
            session = self._sessions.get(str(session_id or ""))
            if session is None or session.target_device != device:
                raise SessionAccessDenied("Device is not assigned to this live desktop session.")
            if session.state in {ENDED, EXPIRED}:
                return {"ok": False, "terminate": True, "state": session.state}
            session.state = selected
            session.fps = max(0.0, min(float(fps or 0.0), 120.0))
            session.measured_quality = str(quality or "").upper() if str(quality or "").upper() in QUALITIES else ""
            session.error = _clean_text(error, 180)
            session.updated = time.time()
            if selected in TERMINAL:
                session.ended_reason = session.error or selected.casefold()
            self._changed.notify_all()
            return {"ok": True, "terminate": selected in TERMINAL,
                    "state": session.state, "expires": session.expires}

    def end_owner(self, session_id: str, browser_device: str,
                  reason: str = "owner ended session") -> bool:
        with self._changed:
            session = self.session_for_owner(session_id, browser_device)
            if session.state in TERMINAL:
                return False
            session.state = ENDED
            session.ended_reason = _clean_text(reason, 180)
            session.updated = time.time()
            self._changed.notify_all()
            return True

    def end_device(self, session_id: str, device_id: str,
                   reason: str = "device ended session") -> bool:
        device = _safe_id(device_id, "device id")
        with self._changed:
            self._purge_locked()
            session = self._sessions.get(str(session_id or ""))
            if session is None or session.target_device != device:
                raise SessionAccessDenied("Device is not assigned to this live desktop session.")
            if session.state in TERMINAL:
                return False
            session.state = ENDED
            session.ended_reason = _clean_text(reason, 180)
            session.updated = time.time()
            self._changed.notify_all()
            return True

    def end_all(self, reason: str, *, modes: set[str] | None = None,
                target_device: str = "") -> int:
        """Terminate matching peers for kill-switch and revocation paths."""
        selected_modes = ({str(mode).upper() for mode in modes} if modes else None)
        target = _safe_id(target_device, "device id") if target_device else ""
        ended = 0
        now = time.time()
        with self._changed:
            for session in self._sessions.values():
                if session.state in TERMINAL:
                    continue
                if selected_modes is not None and session.mode not in selected_modes:
                    continue
                if target and session.target_device != target:
                    continue
                session.state = ENDED
                session.ended_reason = _clean_text(reason, 180)
                session.updated = now
                ended += 1
            if ended:
                self._changed.notify_all()
        return ended

    def update_presence(self, device_id: str, raw: dict[str, Any]) -> dict[str, Any]:
        device = _safe_id(device_id, "device id")
        active: list[dict[str, Any]] = []
        for item in raw.get("active_agents") if isinstance(raw.get("active_agents"), list) else []:
            if not isinstance(item, dict) or len(active) >= 12:
                continue
            agent = str(item.get("id") or item.get("agent") or "").casefold()
            if not re.fullmatch(r"[a-z0-9_-]{1,64}", agent):
                continue
            color = str(item.get("color") or "#719bff")
            active.append({
                "id": agent, "name": _clean_text(item.get("name") or agent.upper(), 40),
                "role": _clean_text(item.get("role"), 90),
                "color": color if _SAFE_COLOR.fullmatch(color) else "#719bff",
                "state": _clean_text(item.get("state") or "LISTENING", 32).upper(),
                "expression": _clean_text(item.get("expression") or "neutral", 32).lower(),
                "speaking": bool(item.get("speaking")),
                "current_task": _clean_text(item.get("current_task"), 180),
            })
        projection = {"schema": 1, "device_id": device, "active_agents": active,
                      "current_speaker": _clean_text(raw.get("current_speaker"), 64),
                      "at": time.time()}
        with self._changed:
            self._presence[device] = projection
            self._changed.notify_all()
        return dict(projection)

    def presence(self, device_id: str) -> dict[str, Any]:
        device = _safe_id(device_id, "device id")
        with self._lock:
            projection = dict(self._presence.get(device) or {})
        if not projection:
            return {"schema": 1, "device_id": device, "active_agents": [],
                    "current_speaker": "", "state": "NOT_REPORTED", "at": 0.0}
        projection["state"] = ("STALE" if time.time() - float(projection.get("at") or 0) > PRESENCE_TTL_S
                               else "CURRENT")
        if projection["state"] == "STALE":
            projection["active_agents"] = []
            projection["current_speaker"] = ""
        return projection

    def stats(self) -> dict[str, Any]:
        with self._lock:
            self._purge_locked()
            active = [row for row in self._sessions.values() if row.state not in TERMINAL]
            return {"active_sessions": len(active), "maximum": self._maximum,
                    "states": {state: sum(row.state == state for row in self._sessions.values())
                               for state in {row.state for row in self._sessions.values()}}}

    def _purge_locked(self, now: float | None = None) -> None:
        observed = time.time() if now is None else float(now)
        for session in self._sessions.values():
            if session.state not in TERMINAL and session.expires <= observed:
                session.state = EXPIRED
                session.ended_reason = "session expired"
                session.updated = observed
        old = [key for key, session in self._sessions.items()
               if session.state in TERMINAL and observed - session.updated > 600]
        for key in old:
            self._sessions.pop(key, None)


_manager: LiveDesktopManager | None = None
_manager_lock = threading.Lock()


def get_live_desktop() -> LiveDesktopManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = LiveDesktopManager()
    return _manager


def reset_for_tests() -> LiveDesktopManager:
    global _manager
    with _manager_lock:
        _manager = LiveDesktopManager()
        return _manager
