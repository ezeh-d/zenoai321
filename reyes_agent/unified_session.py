"""Authoritative, bounded live state shared by every ZENO surface.

This manager owns *coordination state*, not conversation content.  Durable
fields survive a UI/worker restart; rapidly changing presentation fields are
kept in memory and rebuilt from real lifecycle events.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from reyes_agent import config

_PATH = config.VAULT_PATH / "07-System" / "session" / (
    "unified-test.json" if config.ZENO_ENV == "test" else "unified.json"
)
_DURABLE = {
    "session_id", "user", "source_device", "active_device",
    "conversation_mode", "current_topic", "current_task", "unfinished_tasks",
    "privacy_state",
}


@dataclass
class UnifiedSessionState:
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    user: str = "owner"
    source_device: str = "laptop"
    active_device: str = "laptop"
    connected_devices: dict[str, float] = field(default_factory=dict)
    active_agents: list[str] = field(default_factory=list)
    conversation_mode: str = "NORMAL"
    current_topic: str = ""
    current_task: dict[str, Any] = field(default_factory=dict)
    current_app: str = ""
    current_window: str = ""
    pending_questions: list[str] = field(default_factory=list)
    unfinished_tasks: list[dict[str, Any]] = field(default_factory=list)
    privacy_state: dict[str, Any] = field(default_factory=dict)
    voice_state: str = "STANDBY"
    screen_state: str = "NOT_SHARED"
    revision: int = 0
    updated_at: float = field(default_factory=time.time)


class SessionStateManager:
    """Thread-safe last-writer authority with atomic persistence."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _PATH
        self._lock = threading.RLock()
        self._state = UnifiedSessionState()
        self._restore()

    def _restore(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(raw, dict):
            return
        with self._lock:
            for key in _DURABLE:
                if key in raw:
                    setattr(self._state, key, raw[key])
            # A restored device is not assumed online until it checks in.
            self._state.connected_devices = {}
            self._state.active_agents = []
            self._state.voice_state = "STANDBY"
            self._state.screen_state = "NOT_SHARED"

    def _persist(self) -> None:
        payload = {key: getattr(self._state, key) for key in _DURABLE}
        payload.update(revision=self._state.revision, updated_at=self._state.updated_at)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, default=str), encoding="utf-8")
            temporary.replace(self._path)
        except OSError:
            pass

    def update(self, *, source: str = "runtime", notify: bool = True,
               **changes: Any) -> dict[str, Any]:
        allowed = set(UnifiedSessionState.__dataclass_fields__) - {"revision", "updated_at"}
        changed: dict[str, Any] = {}
        with self._lock:
            for key, value in changes.items():
                if key not in allowed or getattr(self._state, key) == value:
                    continue
                setattr(self._state, key, value)
                changed[key] = value
            if not changed:
                return self.snapshot()
            self._state.revision += 1
            self._state.updated_at = time.time()
            if any(key in _DURABLE for key in changed):
                self._persist()
            snapshot = asdict(self._state)
        if notify:
            self._publish(changed, source)
        return snapshot

    def connect_device(self, device_id: str, *, make_active: bool = False,
                       source: str = "device") -> dict[str, Any]:
        key = str(device_id or "").strip()
        if not key:
            return self.snapshot()
        with self._lock:
            devices = dict(self._state.connected_devices)
            devices[key] = time.time()
        changes: dict[str, Any] = {"connected_devices": devices}
        if make_active:
            changes["active_device"] = key
            changes["source_device"] = key
        return self.update(source=source, **changes)

    def disconnect_device(self, device_id: str, *, source: str = "device") -> dict[str, Any]:
        key = str(device_id or "").strip()
        with self._lock:
            devices = dict(self._state.connected_devices)
            devices.pop(key, None)
            active = self._state.active_device
        changes: dict[str, Any] = {"connected_devices": devices}
        if active == key:
            changes["active_device"] = "laptop" if "laptop" in devices else ""
        return self.update(source=source, **changes)

    def set_agent(self, agent: str, active: bool, *, source: str = "agent_runtime") -> dict[str, Any]:
        key = str(agent or "").strip().upper()
        with self._lock:
            agents = list(self._state.active_agents)
        if active and key and key not in agents:
            agents.append(key)
        elif not active and key in agents:
            agents.remove(key)
        return self.update(source=source, active_agents=agents)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return asdict(self._state)

    def _publish(self, changed: dict[str, Any], source: str) -> None:
        try:
            from reyes_agent import event_bus
            event_bus.publish("session.state.changed", {
                "session_id": self._state.session_id,
                "revision": self._state.revision,
                "changed": changed,
            }, source=source, correlation_id=self._state.session_id)
        except Exception:  # observability must never break state
            pass


_manager: SessionStateManager | None = None
_manager_lock = threading.Lock()


def get_session_state() -> SessionStateManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = SessionStateManager()
        return _manager
