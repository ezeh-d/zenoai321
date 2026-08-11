"""An edit as structure, not as a command that has already been run.

    "Do not manually bake every edit without retaining timeline information."

WHY THE STRUCTURE IS THE POINT
------------------------------
The moment an edit exists only as an ffmpeg invocation, the second version
is a rewrite. "Make the hook two seconds shorter" means re-deriving every
downstream timestamp by hand, and "give me the 9:16 version" means building
the whole thing again.

Holding the edit as data makes those operations what they should be:
`shift`, `retime`, `reframe`. The ffmpeg command becomes an output format,
generated at render time from the current state.

TIME IS INTEGER MILLISECONDS
----------------------------
Not floats. A timeline built from float seconds accumulates error across
cuts until clips overlap by a frame and audio drifts -- the classic symptom
being a video that is fine for thirty seconds and subtly wrong by the end.
Milliseconds as integers make `end == next.start` exact.

WHAT THIS DOES NOT DO
---------------------
It does not generate footage. It arranges clips, colour, text and audio
that already exist, and `renderer.py` turns that into a real file. There is
no AI video model behind it and it does not pretend otherwise.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

VIDEO = "video"
AUDIO = "audio"
TEXT = "text"
CAPTION = "caption"
IMAGE = "image"
COLOR = "color"

KINDS = (VIDEO, AUDIO, TEXT, CAPTION, IMAGE, COLOR)

# Platform profiles. Not hardcoded limits -- the frame geometry, which is
# the part that genuinely does not change month to month.
ASPECTS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}


@dataclass
class Clip:
    kind: str
    start_ms: int
    duration_ms: int
    source: str = ""              # file path, or the text for TEXT/CAPTION
    in_ms: int = 0                # seek within the source
    track: int = 0
    # presentation
    text: str = ""
    color: str = "#000000"
    font_size: int = 64
    position: str = "center"      # center | top | bottom
    volume: float = 1.0
    crop: tuple[int, int, int, int] | None = None   # x, y, w, h

    @property
    def end_ms(self) -> int:
        return self.start_ms + self.duration_ms

    def overlaps(self, other: "Clip") -> bool:
        return (self.track == other.track and self.kind == other.kind
                and self.start_ms < other.end_ms and other.start_ms < self.end_ms)

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "start_ms": self.start_ms,
                "duration_ms": self.duration_ms, "end_ms": self.end_ms,
                "source": self.source, "in_ms": self.in_ms, "track": self.track,
                "text": self.text, "color": self.color, "font_size": self.font_size,
                "position": self.position, "volume": self.volume,
                "crop": list(self.crop) if self.crop else None}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Clip":
        crop = raw.get("crop")
        return cls(**{**{k: v for k, v in raw.items()
                         if k in cls.__dataclass_fields__ and k != "crop"},
                      "crop": tuple(crop) if crop else None})


@dataclass
class Timeline:
    name: str = "untitled"
    aspect: str = "9:16"
    fps: int = 30
    clips: list[Clip] = field(default_factory=list)
    background: str = "#000000"

    @property
    def size(self) -> tuple[int, int]:
        return ASPECTS.get(self.aspect, ASPECTS["9:16"])

    @property
    def duration_ms(self) -> int:
        return max((c.end_ms for c in self.clips), default=0)

    @property
    def duration_s(self) -> float:
        return self.duration_ms / 1000.0

    def add(self, clip: Clip) -> "Timeline":
        self.clips.append(clip)
        self.clips.sort(key=lambda c: (c.kind, c.track, c.start_ms))
        return self

    def append(self, kind: str, duration_ms: int, **kw) -> Clip:
        """Add a clip immediately after the last one of its kind and track."""
        track = int(kw.get("track", 0))
        tail = max((c.end_ms for c in self.clips
                    if c.kind == kind and c.track == track), default=0)
        clip = Clip(kind=kind, start_ms=tail, duration_ms=int(duration_ms), **kw)
        self.add(clip)
        return clip

    def of_kind(self, kind: str) -> list[Clip]:
        return [c for c in self.clips if c.kind == kind]

    def at(self, ms: int) -> list[Clip]:
        return [c for c in self.clips if c.start_ms <= ms < c.end_ms]

    # --- the operations that structure makes cheap -----------------------

    def retime(self, clip: Clip, new_duration_ms: int, *, ripple: bool = True
               ) -> "Timeline":
        """Change a clip's length; move everything after it to match.

        This is the operation that a baked ffmpeg command cannot do without
        re-deriving every downstream timestamp by hand.
        """
        delta = int(new_duration_ms) - clip.duration_ms
        clip.duration_ms = max(1, int(new_duration_ms))
        if ripple and delta:
            for other in self.clips:
                if other is clip:
                    continue
                if other.track == clip.track and other.kind == clip.kind \
                        and other.start_ms >= clip.start_ms:
                    other.start_ms = max(0, other.start_ms + delta)
        self.clips.sort(key=lambda c: (c.kind, c.track, c.start_ms))
        return self

    def shift(self, clip: Clip, delta_ms: int) -> "Timeline":
        clip.start_ms = max(0, clip.start_ms + int(delta_ms))
        self.clips.sort(key=lambda c: (c.kind, c.track, c.start_ms))
        return self

    def reframe(self, aspect: str) -> "Timeline":
        """The same edit for another platform -- one field, not a rebuild."""
        if aspect not in ASPECTS:
            raise ValueError(f"unknown aspect '{aspect}'")
        self.aspect = aspect
        return self

    # --- correctness -----------------------------------------------------

    def problems(self) -> list[str]:
        """Everything structurally wrong, before anyone waits for a render."""
        found: list[str] = []
        if not self.clips:
            found.append("the timeline is empty")
        if self.aspect not in ASPECTS:
            found.append(f"unknown aspect '{self.aspect}'")
        if not 1 <= self.fps <= 120:
            found.append(f"{self.fps}fps is not a sane frame rate")

        for index, clip in enumerate(self.clips):
            if clip.kind not in KINDS:
                found.append(f"clip {index}: '{clip.kind}' is not a clip kind")
            if clip.duration_ms <= 0:
                found.append(f"clip {index} ({clip.kind}) has no duration")
            if clip.start_ms < 0:
                found.append(f"clip {index} ({clip.kind}) starts before zero")
            if clip.kind in (VIDEO, AUDIO, IMAGE) and not clip.source:
                found.append(f"clip {index} ({clip.kind}) has no source file")
            if clip.kind in (TEXT, CAPTION) and not clip.text:
                found.append(f"clip {index} ({clip.kind}) has no text")

        for i, left in enumerate(self.clips):
            for right in self.clips[i + 1:]:
                if left.overlaps(right):
                    found.append(
                        f"{left.kind} clips overlap on track {left.track}: "
                        f"{left.start_ms}-{left.end_ms}ms and "
                        f"{right.start_ms}-{right.end_ms}ms")
        return found

    @property
    def valid(self) -> bool:
        return not self.problems()

    # --- persistence -----------------------------------------------------

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "aspect": self.aspect, "fps": self.fps,
                "background": self.background,
                "duration_ms": self.duration_ms,
                "size": list(self.size),
                "clips": [c.as_dict() for c in self.clips]}

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Timeline":
        timeline = cls(name=raw.get("name", "untitled"),
                       aspect=raw.get("aspect", "9:16"),
                       fps=int(raw.get("fps", 30)),
                       background=raw.get("background", "#000000"))
        for clip in raw.get("clips") or []:
            timeline.clips.append(Clip.from_dict(clip))
        timeline.clips.sort(key=lambda c: (c.kind, c.track, c.start_ms))
        return timeline

    def summary(self) -> str:
        lines = [f"{self.name} — {self.aspect} {self.size[0]}x{self.size[1]} "
                 f"@{self.fps}fps, {self.duration_s:.1f}s"]
        for clip in sorted(self.clips, key=lambda c: c.start_ms):
            span = f"{clip.start_ms / 1000:5.1f}–{clip.end_ms / 1000:5.1f}s"
            what = clip.text[:34] if clip.text else (clip.source or clip.color)
            lines.append(f"  {span}  {clip.kind:8} {what}")
        return "\n".join(lines)


def status() -> dict[str, Any]:
    return {
        "state": "ONLINE",
        "kinds": list(KINDS),
        "aspects": {k: list(v) for k, v in ASPECTS.items()},
        "time_unit": "integer milliseconds",
        "note": ("The edit is data. Retiming a clip ripples the rest, and another "
                 "aspect ratio is one field rather than a rebuild -- neither is "
                 "possible once an edit exists only as a baked command."),
        "does_not": "generate footage; it arranges material that already exists",
    }
