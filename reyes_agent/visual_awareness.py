"""Privacy-controlled, bounded visual/audio awareness state.

The manager owns settings and small in-memory rolling buffers.  It does not
start cameras, microphones, or screen capture at import time.  Screen samples
are taken only while both Visual Awareness and Rolling Buffer are explicitly
enabled, or during a direct user-requested analysis.  Nothing in the rolling
buffer is written to disk.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reyes_agent import config

_SETTINGS_PATH: Path = (
    Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT / ".runtime"))).expanduser()
    / "ZENO" / "Awareness" / "settings.json"
)
_LOCK = threading.RLock()
_DEFAULTS = {
    "visual_awareness": False,
    "microphone_recognition": False,
    "system_audio_recognition": False,
    "rolling_buffer": False,
    "screen_interval_s": 5,
    "rolling_seconds": 60,
}
_MAX_FRAMES = 12
_frames: deque["FrameSample"] = deque(maxlen=_MAX_FRAMES)
_audio_history: deque[dict[str, Any]] = deque(maxlen=40)
_last_frame_digest = ""
_last_sample_error = ""


@dataclass
class FrameSample:
    captured_at: float
    jpeg: bytes
    motion: float
    digest: str

    def metadata(self) -> dict[str, Any]:
        return {"captured_at": self.captured_at, "motion": round(self.motion, 3), "digest": self.digest[:12],
                "bytes": len(self.jpeg)}


def _load() -> dict[str, Any]:
    try:
        stored = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        stored = {}
    values = dict(_DEFAULTS)
    values.update({key: stored[key] for key in _DEFAULTS if key in stored})
    values["screen_interval_s"] = max(3, min(30, int(values["screen_interval_s"])))
    values["rolling_seconds"] = max(20, min(300, int(values["rolling_seconds"])))
    return values


def _save(values: dict[str, Any]) -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(values, indent=2), encoding="utf-8")
    tmp.replace(_SETTINGS_PATH)


def settings() -> dict[str, Any]:
    with _LOCK:
        values = _load()
        return {**values, **_buffer_status(values)}


def update_settings(**changes: Any) -> dict[str, Any]:
    allowed = set(_DEFAULTS)
    with _LOCK:
        values = _load()
        for key, value in changes.items():
            if key not in allowed or value is None:
                continue
            if key in {"screen_interval_s", "rolling_seconds"}:
                values[key] = int(value)
            else:
                values[key] = bool(value)
        values["screen_interval_s"] = max(3, min(30, int(values["screen_interval_s"])))
        values["rolling_seconds"] = max(20, min(300, int(values["rolling_seconds"])))
        _save(values)
        enabled = values["visual_awareness"] and values["rolling_buffer"]
    _configure_sampler(enabled, values["screen_interval_s"])
    _emit("awareness.settings_changed", {key: values[key] for key in _DEFAULTS})
    return settings()


def _configure_sampler(enabled: bool, interval: int) -> None:
    from reyes_agent.scheduler import get_scheduler

    scheduler = get_scheduler()
    if enabled:
        scheduler.schedule("awareness:screen-buffer", sample_if_enabled, interval=interval,
                           timeout=4, replace=True)
    else:
        scheduler.cancel("awareness:screen-buffer")


def sample_if_enabled() -> None:
    values = settings()
    if not (values["visual_awareness"] and values["rolling_buffer"]):
        return
    try:
        capture_screen_sample(reason="rolling")
    except Exception as exc:  # noqa: BLE001 -- sampling is never allowed to harm runtime
        global _last_sample_error
        with _LOCK:
            _last_sample_error = f"{type(exc).__name__}: {exc}"[:180]


def capture_screen_sample(*, reason: str = "direct") -> FrameSample:
    """Capture one compressed screen frame in memory only; no camera use."""
    import pyautogui

    image = pyautogui.screenshot()
    image.thumbnail((640, 360))
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=62, optimize=True)
    jpeg = buf.getvalue()
    digest = hashlib.sha256(jpeg).hexdigest()
    with _LOCK:
        global _last_frame_digest
        motion = 0.0 if not _last_frame_digest else (0.0 if digest == _last_frame_digest else 1.0)
        _last_frame_digest = digest
        sample = FrameSample(time.time(), jpeg, motion, digest)
        if reason == "rolling":
            _frames.append(sample)
            cutoff = sample.captured_at - int(_load()["rolling_seconds"])
            while _frames and _frames[0].captured_at < cutoff:
                _frames.popleft()
    if reason != "rolling":
        _emit("awareness.direct_screen_capture", {"reason": reason, "stored": False, "bytes": len(jpeg)})
    return sample


def recent_frames(lookback_seconds: int = 30) -> list[FrameSample]:
    try:
        lookback_seconds = max(1, min(300, int(lookback_seconds)))
    except (TypeError, ValueError):
        lookback_seconds = 30
    cutoff = time.time() - lookback_seconds
    with _LOCK:
        return [sample for sample in _frames if sample.captured_at >= cutoff]


def clear_visual_history() -> dict[str, Any]:
    with _LOCK:
        count = len(_frames)
        _frames.clear()
    _emit("awareness.visual_history_cleared", {"frames": count})
    return {"ok": True, "cleared_frames": count}


def record_audio_observation(result: dict[str, Any]) -> None:
    """Keep metadata only.  Audio waveform/voice data is never retained."""
    values = settings()
    if not (values["microphone_recognition"] or values["system_audio_recognition"]):
        return
    item = {key: result.get(key) for key in ("matched", "title", "artist", "album", "provider", "source", "reason")}
    item["at"] = time.time()
    with _LOCK:
        _audio_history.append(item)


def recent_audio(lookback_seconds: int = 30) -> list[dict[str, Any]]:
    cutoff = time.time() - max(1, min(300, int(lookback_seconds)))
    with _LOCK:
        return [dict(item) for item in _audio_history if item["at"] >= cutoff]


def clear_audio_history() -> dict[str, Any]:
    with _LOCK:
        count = len(_audio_history)
        _audio_history.clear()
    _emit("awareness.audio_history_cleared", {"items": count})
    return {"ok": True, "cleared_audio_observations": count}


def _buffer_status(values: dict[str, Any]) -> dict[str, Any]:
    return {
        "rolling_frames": len(_frames),
        "rolling_audio_observations": len(_audio_history),
        "screen_capture_active": bool(values["visual_awareness"] and values["rolling_buffer"]),
        "camera_active": False,
        "last_sample_error": _last_sample_error,
        "privacy": "Frames and audio history are memory-only, bounded, and clearable; no camera is started by this service.",
    }


def _emit(event_type: str, payload: dict[str, Any]) -> None:
    try:
        from reyes_agent import event_bus

        event_bus.publish(event_type, payload, source="visual_awareness")
    except Exception:  # noqa: BLE001
        pass
