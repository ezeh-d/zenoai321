"""Landscape to vertical, following the subject instead of the centre.

    "Do not simply crop the center if it cuts off the subject."

That instruction describes the entire failure mode. A 16:9 interview cropped
to 9:16 down the middle removes both people and keeps the wall between them.
It is the single most visible sign that a "short" was made by a tool that
was not looking.

HOW THE SUBJECT IS FOUND
------------------------
OpenCV, which is installed here. Faces first via a Haar cascade -- fast,
runs on CPU, and shipped with cv2 so there is nothing to download. When no
face is present, the fallback is frame differencing: the region that MOVES
is almost always the subject in the kind of footage anyone reframes.

WHY THE PATH IS SMOOTHED
------------------------
A crop that snaps to the detection every frame is unwatchable -- it jitters
on every false positive and lurches when someone turns their head. So the
detections are sampled at intervals, outliers are pulled toward the median,
and the result is smoothed before it becomes a crop. The camera should feel
like an operator following someone, not a tracker locking on.

It returns a crop PATH, which `renderer.py` applies. Keeping the analysis
separate from the render means the same measurement can be reused for
another aspect ratio without re-watching the video.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# How often to look. Every frame is wasteful; a subject does not teleport.
SAMPLE_EVERY_S = 0.5

# How much of the way to move toward a new position per sample. Lower is
# calmer; 0.25 tracks a walking person without visible jitter.
SMOOTHING = 0.25

# A detection this far from the running median is treated as a false
# positive rather than a real jump.
OUTLIER_FRACTION = 0.35


@dataclass
class Keyframe:
    at: float
    x: int
    confidence: float = 0.0
    source: str = ""          # face | motion | held

    def as_dict(self) -> dict[str, Any]:
        return {"at": round(self.at, 2), "x": self.x,
                "confidence": round(self.confidence, 2), "source": self.source}


@dataclass
class Plan:
    ok: bool = False
    reason: str = ""
    width: int = 0
    height: int = 0
    crop_width: int = 0
    crop_height: int = 0
    keyframes: list[Keyframe] = field(default_factory=list)
    faces_found: int = 0
    motion_used: int = 0

    @property
    def static(self) -> bool:
        """Did the subject actually move enough to need a moving crop."""
        if len(self.keyframes) < 2:
            return True
        positions = [k.x for k in self.keyframes]
        return (max(positions) - min(positions)) < self.crop_width * 0.1

    def centre_x(self) -> int:
        if not self.keyframes:
            return max(0, (self.width - self.crop_width) // 2)
        positions = sorted(k.x for k in self.keyframes)
        return positions[len(positions) // 2]

    def crop_at(self, seconds: float) -> tuple[int, int, int, int]:
        """The crop rectangle at a moment. (x, y, w, h)."""
        if not self.keyframes:
            return (self.centre_x(), 0, self.crop_width, self.crop_height)
        nearest = min(self.keyframes, key=lambda k: abs(k.at - seconds))
        return (nearest.x, 0, self.crop_width, self.crop_height)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "reason": self.reason,
                "source": [self.width, self.height],
                "crop": [self.crop_width, self.crop_height],
                "static": self.static, "centre_x": self.centre_x(),
                "faces_found": self.faces_found, "motion_used": self.motion_used,
                "keyframes": [k.as_dict() for k in self.keyframes[:40]]}


def _cv2():
    try:
        import cv2

        return cv2
    except Exception:  # noqa: BLE001
        return None


def _cascade(cv2):
    try:
        path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(path)
        return None if cascade.empty() else cascade
    except Exception:  # noqa: BLE001
        return None


def _smooth(raw: list[Keyframe], limit: int) -> list[Keyframe]:
    """Pull outliers toward the median, then ease between positions."""
    if not raw:
        return []
    positions = sorted(k.x for k in raw)
    median = positions[len(positions) // 2]
    allowed = max(1, int(limit * OUTLIER_FRACTION))

    cleaned = []
    for frame in raw:
        x = frame.x
        if abs(x - median) > allowed:
            x = median + (allowed if x > median else -allowed)
        cleaned.append(Keyframe(frame.at, x, frame.confidence, frame.source))

    smoothed = []
    current = float(cleaned[0].x)
    for frame in cleaned:
        current += (frame.x - current) * SMOOTHING
        smoothed.append(Keyframe(frame.at, int(max(0, min(limit, current))),
                                 frame.confidence, frame.source))
    return smoothed


def plan(path: str | Path, *, aspect: str = "9:16",
         sample_every_s: float = SAMPLE_EVERY_S) -> Plan:
    """Watch the video and work out where the crop should be, over time."""
    result = Plan()
    cv2 = _cv2()
    if cv2 is None:
        result.reason = "OpenCV is not available, so I cannot see the subject"
        return result

    target = Path(path)
    if not target.exists():
        result.reason = f"no file at {target}"
        return result

    try:
        capture = cv2.VideoCapture(str(target))
        if not capture.isOpened():
            result.reason = "OpenCV could not open that video"
            return result

        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        result.width, result.height = width, height

        want_w, want_h = (9, 16) if aspect == "9:16" else (1, 1)
        crop_h = height
        crop_w = int(round(height * want_w / want_h))
        if crop_w > width:
            crop_w = width
            crop_h = int(round(width * want_h / want_w))
        result.crop_width, result.crop_height = crop_w, crop_h

        if crop_w >= width:
            result.ok = True
            result.reason = "already at or narrower than the target aspect"
            capture.release()
            return result

        cascade = _cascade(cv2)
        limit = width - crop_w
        step = max(1, int(fps * sample_every_s))
        raw: list[Keyframe] = []
        previous_grey = None
        index = 0

        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if index % step:
                index += 1
                continue
            at = index / fps
            grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            centre = None
            source = ""
            if cascade is not None:
                faces = cascade.detectMultiScale(grey, 1.2, 5, minSize=(60, 60))
                if len(faces):
                    # Widest face wins -- the nearest person is the subject.
                    x, _y, w, _h = max(faces, key=lambda f: f[2])
                    centre = int(x + w / 2)
                    source = "face"
                    result.faces_found += 1

            if centre is None and previous_grey is not None:
                delta = cv2.absdiff(previous_grey, grey)
                columns = delta.sum(axis=0)
                if columns.sum() > 0:
                    import numpy

                    centre = int(numpy.argmax(
                        numpy.convolve(columns, numpy.ones(64) / 64, mode="same")))
                    source = "motion"
                    result.motion_used += 1

            previous_grey = grey
            if centre is not None:
                raw.append(Keyframe(at, int(max(0, min(limit, centre - crop_w // 2))),
                                    1.0 if source == "face" else 0.5, source))
            index += 1

        capture.release()
    except Exception as exc:  # noqa: BLE001
        result.reason = f"{type(exc).__name__}: {exc}"
        return result

    result.keyframes = _smooth(raw, limit)
    result.ok = True
    if not result.keyframes:
        result.reason = ("no face or motion found, so the crop stays centred -- "
                         "which is right for a static shot and wrong for a person "
                         "walking, so check the result")
    elif result.static:
        result.reason = (f"subject stays put ({result.faces_found} face samples); "
                         "a fixed crop on them is better than a moving one")
    else:
        result.reason = (f"subject moves; tracking with {len(result.keyframes)} "
                         f"smoothed keyframes ({result.faces_found} from faces, "
                         f"{result.motion_used} from motion)")
    return result


def to_clip_crop(plan_result: Plan, *, at: float = 0.0) -> tuple[int, int, int, int] | None:
    """A crop rectangle for `timeline.Clip.crop`."""
    if not plan_result.ok or not plan_result.crop_width:
        return None
    return plan_result.crop_at(at)


def status() -> dict[str, Any]:
    cv2 = _cv2()
    return {
        "state": "ONLINE" if cv2 is not None else "DEPENDENCY_MISSING",
        "opencv": cv2 is not None,
        "detects": ["faces (Haar cascade, shipped with OpenCV)",
                    "motion (frame differencing) when no face is present"],
        "smoothing": {"sample_every_s": SAMPLE_EVERY_S, "factor": SMOOTHING,
                      "outlier_fraction": OUTLIER_FRACTION},
        "note": ("A centre crop of a 16:9 interview removes both people and keeps "
                 "the wall between them. The crop follows the subject and is "
                 "smoothed, so it moves like an operator rather than a tracker."),
        "no_model": "Haar cascades and frame differencing -- no ML runtime needed",
    }
