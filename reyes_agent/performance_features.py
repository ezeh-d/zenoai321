"""Persisted controls and load guard for optional performance features.

This is deliberately small: Dream Mode, dashboard refresh and cursor eyes
already exist in their own subsystems.  This module merely gives them one
durable preference contract and an evidence-based load signal; it does not
create another scheduler or polling thread.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any

import psutil

from reyes_agent import config

_SETTINGS_PATH = config.VAULT_PATH / "07-System" / "performance_features.json"
_lock = threading.Lock()
_dream_state = "DREAM_MODE_IDLE"
_dream_updated_at = 0.0
_dream_detail = ""


@dataclass
class FeatureSettings:
    dream_mode: bool = True
    dashboard_updates: bool = True
    cursor_eye_tracking: bool = True
    eye_tracking_fps: str = "auto"       # auto | 15 | 30
    dream_idle_only: bool = True          # deliberately never false in runtime
    performance_mode: str = "auto"       # auto | low_power | normal

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_settings() -> FeatureSettings:
    try:
        raw = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        known = FeatureSettings().as_dict()
        values = {key: raw[key] for key in known if key in raw}
        if str(values.get("eye_tracking_fps", "auto")) not in {"auto", "15", "30"}:
            values["eye_tracking_fps"] = "auto"
        if str(values.get("performance_mode", "auto")) not in {"auto", "low_power", "normal"}:
            values["performance_mode"] = "auto"
        values["dream_idle_only"] = True
        return FeatureSettings(**values)
    except Exception:  # noqa: BLE001 - a corrupt preference never disables the core app
        return FeatureSettings()


def save_settings(**changes: Any) -> FeatureSettings:
    settings = load_settings()
    for key, value in changes.items():
        if not hasattr(settings, key):
            continue
        if key == "dream_idle_only":
            value = True
        elif key in {"dream_mode", "dashboard_updates", "cursor_eye_tracking"}:
            value = bool(value)
        elif key == "eye_tracking_fps" and str(value) not in {"auto", "15", "30"}:
            continue
        elif key == "performance_mode" and str(value) not in {"auto", "low_power", "normal"}:
            continue
        setattr(settings, key, value)
    try:
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _SETTINGS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings.as_dict(), indent=2), encoding="utf-8")
        tmp.replace(_SETTINGS_PATH)
    except OSError:
        pass
    return settings


def set_dream_state(state: str, detail: str = "") -> dict[str, Any]:
    global _dream_state, _dream_updated_at, _dream_detail
    with _lock:
        _dream_state, _dream_updated_at, _dream_detail = state, time.time(), str(detail)[:300]
        result = {"state": _dream_state, "updated_at": _dream_updated_at, "detail": _dream_detail}
    try:
        from reyes_agent import event_bus

        event_bus.publish("dream.state_changed", result, source="dream_mode")
    except Exception:  # noqa: BLE001 - diagnostics must not make Dream Mode fail
        pass
    return result


def dream_status() -> dict[str, Any]:
    with _lock:
        return {"state": _dream_state, "updated_at": _dream_updated_at, "detail": _dream_detail}


def load_snapshot() -> dict[str, Any]:
    """A non-blocking, bounded sample used only by optional work."""
    vm = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=None)
    active = queue_depth = 0
    try:
        from reyes_agent.worker_pool import get_worker_pool

        metrics = get_worker_pool().metrics()
        active, queue_depth = int(metrics.get("active", 0)), int(metrics.get("queue_depth", 0))
    except Exception:  # noqa: BLE001
        pass
    return {"cpu": float(cpu), "ram": float(vm.percent), "active_workers": active, "queue_depth": queue_depth}


def under_load(snapshot: dict[str, Any] | None = None) -> bool:
    sample = snapshot or load_snapshot()
    # The Dream/proactive check itself occupies one managed worker. Treating
    # that worker as contention would make Dream Mode permanently pause before
    # its first pass; a second active worker is real concurrent work.
    return (sample["cpu"] >= 75 or sample["ram"] >= 85 or sample["active_workers"] > 1
            or sample["queue_depth"] > 0)
