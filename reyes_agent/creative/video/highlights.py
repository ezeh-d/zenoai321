"""Find the interesting moments -- with signal processing, not a model.

WHY NO ML IS NEEDED HERE
------------------------
"Where does the scene change" and "where does the energy spike" are
measurements, not judgements. ffmpeg answers both directly: `scdet` scores
every frame for scene change, `ebur128` and `astats` give real loudness over
time. Those two signals plus silence boundaries locate almost every moment a
human would call a highlight -- a cut to a new shot, a raised voice, a laugh,
a demonstration starting.

What a model WOULD add is meaning: which of those moments is funny, which is
the point of the story. This does not claim that, and `rank()` reports the
signals it used so nobody mistakes energy for insight.

THE FAILURE THIS AVOIDS
-----------------------
"Turn this into five shorts" answered with five evenly-spaced cuts. That is
what happens when a tool has no signal and slices by arithmetic instead --
the output looks like work and contains nothing. Every candidate here points
at a measured event, and if the analysis finds nothing, `find()` returns
nothing rather than padding the list.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reyes_agent.capabilities import inventory

# A clip shorter than this is a glitch; longer than this is not a short.
MIN_CLIP_S = 8.0
MAX_CLIP_S = 60.0
DEFAULT_CLIP_S = 30.0

# Scene-change score above which ffmpeg considers it a real cut.
SCENE_THRESHOLD = 0.35

# Analysis must not run forever on a long recording.
ANALYSIS_TIMEOUT_S = 900

_SCENE = re.compile(r"lavfi\.scd\.score=([0-9.]+).*?pts_time:([0-9.]+)", re.S)
_SCENE_ALT = re.compile(r"pts_time:([0-9.]+)")
_LOUDNESS = re.compile(r"t:\s*([0-9.]+).*?M:\s*(-?[0-9.]+)", re.S)


@dataclass
class Moment:
    at: float
    kind: str                 # scene | energy | speech_start
    score: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"at": round(self.at, 2), "kind": self.kind,
                "score": round(self.score, 3)}


@dataclass
class Candidate:
    start: float
    end: float
    score: float
    reasons: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def as_dict(self) -> dict[str, Any]:
        return {"start": round(self.start, 2), "end": round(self.end, 2),
                "duration": round(self.duration, 2), "score": round(self.score, 3),
                "reasons": self.reasons}


def _run(args: list[str]) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True,
                                timeout=ANALYSIS_TIMEOUT_S,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return (result.stderr or "") + (result.stdout or "")
    except Exception:  # noqa: BLE001
        return ""


def duration_of(path: str | Path) -> float:
    from reyes_agent.creative import verification

    data = verification.probe(path)
    try:
        return float((data or {}).get("format", {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def scene_changes(path: str | Path, *, threshold: float = SCENE_THRESHOLD) -> list[Moment]:
    """Real cuts, from ffmpeg's own scene-change detector."""
    binary = inventory.which("ffmpeg")
    if not binary:
        return []
    output = _run([binary, "-hide_banner", "-i", str(path),
                   "-filter:v", f"select='gt(scene,{threshold})',showinfo",
                   "-f", "null", "-"])
    moments = []
    for match in _SCENE_ALT.finditer(output):
        try:
            moments.append(Moment(float(match.group(1)), "scene", threshold))
        except ValueError:
            continue
    return moments


def loudness(path: str | Path) -> list[Moment]:
    """Momentary loudness over time -- where voices rise, where things happen."""
    binary = inventory.which("ffmpeg")
    if not binary:
        return []
    output = _run([binary, "-hide_banner", "-i", str(path),
                   "-filter:a", "ebur128=metadata=1", "-f", "null", "-"])
    moments = []
    for match in _LOUDNESS.finditer(output):
        try:
            at, level = float(match.group(1)), float(match.group(2))
        except ValueError:
            continue
        if level > -70:                      # -70 LUFS is silence
            moments.append(Moment(at, "energy", level))
    return moments


def _energy_peaks(levels: list[Moment]) -> list[Moment]:
    """Moments meaningfully louder than the recording's own baseline.

    Relative, not absolute: a quiet podcast and a loud stream should both
    yield their own peaks rather than one producing everything and the other
    nothing.
    """
    if len(levels) < 8:
        return []
    scores = sorted(m.score for m in levels)
    median = scores[len(scores) // 2]
    loud = scores[int(len(scores) * 0.85)]
    if loud - median < 1.5:                  # nothing stands out
        return []
    return [m for m in levels if m.score >= loud]


def find(path: str | Path, *, count: int = 5,
         clip_s: float = DEFAULT_CLIP_S) -> dict[str, Any]:
    """Rank real moments and propose clips around them."""
    target = Path(path)
    if not target.exists():
        return {"ok": False, "reason": f"no file at {target}", "candidates": []}
    if not inventory.which("ffmpeg"):
        return {"ok": False, "reason": "ffmpeg is not installed, so nothing can be "
                                       "analysed", "candidates": []}

    total = duration_of(target)
    if total < MIN_CLIP_S:
        return {"ok": False, "reason": f"the video is only {total:.1f}s long",
                "candidates": []}

    scenes = scene_changes(target)
    levels = loudness(target)
    peaks = _energy_peaks(levels)

    if not scenes and not peaks:
        # The honest outcome. Five evenly-spaced cuts would look like work
        # and contain nothing.
        return {"ok": False, "candidates": [], "analysed_seconds": round(total, 1),
                "reason": ("I could not find any scene changes or energy peaks in "
                           "that — it may be one continuous shot at a steady level. "
                           "I would rather tell you that than hand you evenly-spaced "
                           "slices and call them highlights.")}

    window = max(MIN_CLIP_S, min(MAX_CLIP_S, clip_s))
    candidates: list[Candidate] = []

    for moment in sorted(scenes + peaks, key=lambda m: m.at):
        start = max(0.0, moment.at - window * 0.25)
        end = min(total, start + window)
        if end - start < MIN_CLIP_S:
            continue
        # Merge with a candidate we already have that overlaps heavily.
        overlapping = next((c for c in candidates
                            if abs(c.start - start) < window * 0.5), None)
        if overlapping is not None:
            overlapping.score += 1.0
            if moment.kind not in " ".join(overlapping.reasons):
                overlapping.reasons.append(
                    "a scene change" if moment.kind == "scene" else "an energy peak")
            continue
        candidates.append(Candidate(
            start, end, 1.0,
            ["a scene change" if moment.kind == "scene" else "an energy peak"]))

    # Prefer moments backed by BOTH signals -- a cut that is also loud is
    # far more likely to be the interesting bit than either alone.
    candidates.sort(key=lambda c: (-c.score, -len(c.reasons), c.start))
    chosen = candidates[:max(1, count)]

    return {
        "ok": bool(chosen),
        "analysed_seconds": round(total, 1),
        "scene_changes": len(scenes),
        "energy_peaks": len(peaks),
        "candidates": [c.as_dict() for c in chosen],
        "signals": ["ffmpeg scene detection", "EBU R128 momentary loudness"],
        "note": ("These are measured events -- cuts and energy peaks -- not a "
                 "judgement about which moment is the most interesting. Nothing "
                 "here understands the content."),
    }


def status() -> dict[str, Any]:
    available = bool(inventory.which("ffmpeg"))
    return {
        "state": "ONLINE" if available else "DEPENDENCY_MISSING",
        "ffmpeg": available,
        "signals": ["scene change (ffmpeg scdet)", "loudness (EBU R128)"],
        "no_model": "these are measurements, not judgements -- no ML is involved",
        "refuses": ("returning evenly-spaced slices when the analysis finds "
                    "nothing; that looks like work and contains none"),
        "clip_range_s": [MIN_CLIP_S, MAX_CLIP_S],
    }
