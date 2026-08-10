"""The camera: off by default, and gated so footage never streams anywhere.

THE PRIVACY POSITION
--------------------
A camera in a room is different from a screenshot of a window. The brief is
unambiguous: OFF unless explicitly enabled, and a clear indicator whenever
it is active. Both are enforced here rather than left to the caller --
`open()` refuses without the flag, and `active()` is the truth the UI reads.

THE PIPELINE, AND WHY IT EXISTS
-------------------------------
    CAMERA -> OpenCV preprocessing -> interesting? -> NO: discard
                                                   -> YES: vision model

Nearly every frame is boring. Asking a model to look at all of them costs
money, latency and privacy for no information, so classical image processing
answers "did anything change?" first. That is what OpenCV is genuinely good
at, and it needs no model at all: a downscaled greyscale absolute difference
is a few hundred microseconds.

Frames are discarded by default. `capture()` returns a decision and a
measurement, not a picture, unless the caller explicitly asks to keep one --
so the accidental path is the private one.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any

ENABLED_FLAG = "ZENO_CAMERA_ENABLED"

# Proportion of pixels that must change before a frame is "interesting".
# 1.2% is comfortably above sensor noise and below a hand entering frame.
MOTION_THRESHOLD = 0.012

# Per-pixel greyscale delta that counts as changed at all.
PIXEL_DELTA = 22

# Frames are compared at this width; full resolution buys nothing for motion.
WORK_WIDTH = 160

_lock = threading.Lock()
_capture = None
_previous = None
_opened_at = 0.0
_frames = 0
_interesting = 0


def enabled() -> bool:
    return os.environ.get(ENABLED_FLAG, "").strip().lower() in {"1", "true", "yes", "on"}


def _cv2():
    try:
        import cv2

        return cv2
    except Exception:  # noqa: BLE001
        return None


def available() -> bool:
    return _cv2() is not None


def active() -> bool:
    """Is the camera open RIGHT NOW. What an on-air indicator must read."""
    with _lock:
        return _capture is not None


@dataclass
class Frame:
    """A decision and a measurement. The image itself is opt-in."""

    ok: bool
    interesting: bool = False
    motion: float = 0.0
    at: float = 0.0
    reason: str = ""
    image: Any = None            # only when the caller asked to keep it

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "interesting": self.interesting,
                "motion": round(self.motion, 4), "at": self.at,
                "reason": self.reason, "image_kept": self.image is not None}


def open(index: int = 0) -> tuple[bool, str]:
    """Turn the camera on. Refused unless the owner enabled it."""
    global _capture, _opened_at, _previous, _frames, _interesting
    if not enabled():
        return False, (f"The camera is off. Set {ENABLED_FLAG}=1 if you want me to "
                       "use it -- I will not turn it on by myself.")
    cv2 = _cv2()
    if cv2 is None:
        return False, "OpenCV is not available, so there is no camera path"

    with _lock:
        if _capture is not None:
            return True, "already open"
        try:
            device = cv2.VideoCapture(int(index), getattr(cv2, "CAP_DSHOW", 0))
            if not device.isOpened():
                device.release()
                return False, f"no camera at index {index}"
            _capture, _opened_at = device, time.time()
            _previous, _frames, _interesting = None, 0, 0
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"

    _announce(True)
    return True, "camera on"


def close() -> None:
    global _capture, _previous
    with _lock:
        if _capture is not None:
            try:
                _capture.release()
            except Exception:  # noqa: BLE001
                pass
        _capture, _previous = None, None
    _announce(False)


def _announce(on: bool) -> None:
    """The indicator is an event, so the UI cannot forget to show it."""
    try:
        from reyes_agent import event_bus

        event_bus.publish("zeno.camera." + ("on" if on else "off"),
                          {"at": time.time()}, source="camera")
    except Exception:  # noqa: BLE001
        pass


def capture(*, keep_image: bool = False) -> Frame:
    """One frame, judged. The image is dropped unless explicitly kept."""
    global _previous, _frames, _interesting
    if not enabled():
        return Frame(False, reason="the camera is disabled")
    cv2 = _cv2()
    if cv2 is None:
        return Frame(False, reason="OpenCV is not available")

    with _lock:
        device = _capture
    if device is None:
        return Frame(False, reason="the camera is not open")

    try:
        ok, raw = device.read()
    except Exception as exc:  # noqa: BLE001
        return Frame(False, reason=f"{type(exc).__name__}: {exc}")
    if not ok or raw is None:
        return Frame(False, reason="the camera returned no frame")

    import numpy

    height, width = raw.shape[:2]
    scale = WORK_WIDTH / float(width or 1)
    small = cv2.resize(raw, (WORK_WIDTH, max(1, int(height * scale))))
    grey = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    grey = cv2.GaussianBlur(grey, (5, 5), 0)

    frame = Frame(True, at=time.time())
    with _lock:
        previous = _previous
        _previous = grey
        _frames += 1

    if previous is None:
        frame.reason = "first frame; nothing to compare against yet"
        return frame

    delta = cv2.absdiff(previous, grey)
    changed = int(numpy.count_nonzero(delta > PIXEL_DELTA))
    frame.motion = changed / float(delta.size or 1)
    frame.interesting = frame.motion >= MOTION_THRESHOLD
    frame.reason = ("something moved" if frame.interesting
                    else "nothing changed; discarded without leaving the machine")

    if frame.interesting:
        with _lock:
            _interesting += 1
        if keep_image:
            frame.image = raw
    return frame


def health() -> dict[str, Any]:
    cv2 = _cv2()
    if cv2 is None:
        return {"available": False}
    if not enabled():
        return {"available": True, "enabled": False,
                "detail": "not probed -- probing would turn the camera on"}
    try:
        device = cv2.VideoCapture(0, getattr(cv2, "CAP_DSHOW", 0))
        present = device.isOpened()
        device.release()
        return {"available": True, "enabled": True, "camera_present": present}
    except Exception as exc:  # noqa: BLE001
        return {"available": True, "enabled": True, "error": f"{type(exc).__name__}: {exc}"}


def status() -> dict[str, Any]:
    with _lock:
        on, frames, interesting, since = _capture is not None, _frames, _interesting, _opened_at
    return {
        "state": "ACTIVE" if on else ("STANDBY" if enabled() else "DISABLED"),
        "opencv": available(),
        "enabled": enabled(),
        "active": on,
        "indicator": ("THE CAMERA IS ON" if on else "the camera is off"),
        "open_for_s": round(time.time() - since, 1) if on else None,
        "frames_seen": frames,
        "frames_interesting": interesting,
        "discarded": frames - interesting,
        "flag": ENABLED_FLAG,
        "policy": ("Off unless you turn it on. Frames are compared locally with "
                   "OpenCV and discarded unless something actually changed -- "
                   "footage is never streamed to a model, and the image is only "
                   "kept when a caller explicitly asks for it."),
    }
