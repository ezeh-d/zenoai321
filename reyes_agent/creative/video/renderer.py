"""Compile a timeline into a real, playable file.

    "Do not use an AI model for simple deterministic media operations."

Everything here is ffmpeg. Trimming, concatenating, overlaying text,
mixing audio and letterboxing to an aspect ratio are solved problems with
exact, repeatable answers -- reaching for a model to do them would be
slower, more expensive and less correct.

WHY THE FILTER GRAPH IS BUILT RATHER THAN TEMPLATED
---------------------------------------------------
A timeline has a variable number of clips on a variable number of tracks,
so the command has to be constructed from the structure. Building it means
the same timeline always produces the same command, which is what makes a
render reproducible and a diff meaningful.

THE RENDER IS NOT DONE WHEN FFMPEG EXITS
----------------------------------------
It is done when `creative.verification` says the file plays at the right
size and length. ffmpeg exits 0 on plenty of files nobody can watch, so
`render()` always verifies and reports the verification, not the exit code.
"""

from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reyes_agent.capabilities import inventory
from reyes_agent.creative import verification
from reyes_agent.creative.video.timeline import (AUDIO, CAPTION, COLOR, IMAGE,
                                                 TEXT, VIDEO, Clip, Timeline)

# A render must not hold a worker forever.
DEFAULT_TIMEOUT_S = 900

# Escaping for drawtext: ffmpeg's filter parser treats these structurally.
_DRAWTEXT_ESCAPE = str.maketrans({
    "\\": r"\\", ":": r"\:", "'": r"\'", "%": r"\%",
    "[": r"\[", "]": r"\]", ",": r"\,", ";": r"\;",
})


@dataclass
class Render:
    ok: bool = False
    path: str = ""
    command: str = ""
    duration_s: float = 0.0
    stderr: str = ""
    media: verification.Media | None = None
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "path": self.path, "reason": self.reason,
                "render_seconds": round(self.duration_s, 2),
                "command": self.command[:1200],
                "media": self.media.as_dict() if self.media else None}

    def summary(self) -> str:
        if not self.ok:
            return f"render did NOT produce a usable file: {self.reason}"
        return f"{self.media.summary()} in {self.duration_s:.1f}s"


def _escape_text(value: str) -> str:
    return str(value or "").translate(_DRAWTEXT_ESCAPE)


# Fonts to try, best first. Windows ships all of these.
_FONT_CANDIDATES = ("segoeui.ttf", "arial.ttf", "calibri.ttf", "tahoma.ttf",
                    "DejaVuSans.ttf", "verdana.ttf")

_font_cache: str | None = None


def _font_file() -> str:
    """An explicit font path for drawtext, escaped for the filter parser.

    Windows ffmpeg builds generally ship WITHOUT fontconfig, so `drawtext`
    with no `fontfile=` dies with "Cannot load default config file" and
    produces nothing -- which the verifier correctly reported as "no file
    was produced". Naming a real font removes the dependency entirely.

    The escaping is its own trap: inside a filter string a Windows path has
    to become `C\\:/Windows/Fonts/arial.ttf`. Backslashes become forward
    slashes and the drive colon is escaped, or ffmpeg reads `C` as a filter
    option name.
    """
    global _font_cache
    if _font_cache is not None:
        return _font_cache

    roots = [Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/dejavu"),
             Path("/Library/Fonts")]
    for root in roots:
        for name in _FONT_CANDIDATES:
            candidate = root / name
            if candidate.is_file():
                _font_cache = str(candidate).replace("\\", "/").replace(":", r"\:")
                return _font_cache
    _font_cache = ""
    return _font_cache


def _drawtext_font() -> str:
    font = _font_file()
    return f"fontfile='{font}':" if font else ""


def _hex_to_ffmpeg(colour: str) -> str:
    value = str(colour or "#000000").lstrip("#")
    return f"0x{value}" if len(value) in (6, 8) else "0x000000"


def _position(clip: Clip) -> str:
    return {
        "top": "x=(w-text_w)/2:y=h*0.12",
        "bottom": "x=(w-text_w)/2:y=h*0.80",
    }.get(clip.position, "x=(w-text_w)/2:y=(h-text_h)/2")


def build_command(timeline: Timeline, output: str | Path, *,
                  crf: int = 20) -> tuple[list[str], str]:
    """The exact ffmpeg invocation for this timeline. (argv, human-readable)."""
    binary = inventory.which("ffmpeg") or "ffmpeg"
    width, height = timeline.size
    duration = max(0.04, timeline.duration_s)

    args: list[str] = [binary, "-y", "-loglevel", "error"]
    inputs: list[tuple[Clip, int]] = []

    # Input 0 is always the background, so there is a canvas even for a
    # timeline that is nothing but text.
    args += ["-f", "lavfi", "-i",
             f"color=c={_hex_to_ffmpeg(timeline.background)}:"
             f"s={width}x{height}:r={timeline.fps}:d={duration:.3f}"]

    index = 1
    for clip in timeline.clips:
        if clip.kind in (VIDEO, IMAGE, AUDIO):
            if clip.in_ms:
                args += ["-ss", f"{clip.in_ms / 1000:.3f}"]
            if clip.kind == IMAGE:
                args += ["-loop", "1", "-t", f"{clip.duration_ms / 1000:.3f}"]
            args += ["-i", str(clip.source)]
            inputs.append((clip, index))
            index += 1

    filters: list[str] = []
    current = "0:v"

    # Visual clips, scaled to fit and composited at their own time window.
    stage = 0
    for clip, input_index in inputs:
        if clip.kind not in (VIDEO, IMAGE):
            continue
        label = f"v{stage}"
        crop = ""
        if clip.crop:
            x, y, w, h = clip.crop
            crop = f"crop={w}:{h}:{x}:{y},"
        filters.append(
            f"[{input_index}:v]{crop}scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={_hex_to_ffmpeg(timeline.background)},"
            f"setsar=1[{label}]")
        out = f"c{stage}"
        start = clip.start_ms / 1000
        end = clip.end_ms / 1000
        filters.append(
            f"[{current}][{label}]overlay=enable='between(t,{start:.3f},{end:.3f})'[{out}]")
        current = out
        stage += 1

    # Text and captions are drawn last so nothing covers them.
    for clip in timeline.clips:
        if clip.kind not in (TEXT, CAPTION):
            continue
        out = f"t{stage}"
        start = clip.start_ms / 1000
        end = clip.end_ms / 1000
        size = clip.font_size if clip.kind == TEXT else max(28, clip.font_size - 16)
        box = ":box=1:boxcolor=0x000000AA:boxborderw=18" if clip.kind == CAPTION else ""
        filters.append(
            f"[{current}]drawtext={_drawtext_font()}text='{_escape_text(clip.text)}':"
            f"fontcolor={_hex_to_ffmpeg(clip.color if clip.color != '#000000' else '#ffffff')}:"
            f"fontsize={size}:{_position(clip)}{box}:"
            f"enable='between(t,{start:.3f},{end:.3f})'[{out}]")
        current = out
        stage += 1

    # Audio: mix every audio clip, delayed to its start.
    audio_labels = []
    for clip, input_index in inputs:
        if clip.kind != AUDIO:
            continue
        label = f"a{len(audio_labels)}"
        filters.append(
            f"[{input_index}:a]adelay={clip.start_ms}|{clip.start_ms},"
            f"volume={max(0.0, clip.volume):.2f}[{label}]")
        audio_labels.append(label)

    audio_out = ""
    if audio_labels:
        if len(audio_labels) == 1:
            audio_out = audio_labels[0]
        else:
            joined = "".join(f"[{l}]" for l in audio_labels)
            filters.append(f"{joined}amix=inputs={len(audio_labels)}:"
                           f"dropout_transition=0[amixed]")
            audio_out = "amixed"

    if filters:
        args += ["-filter_complex", ";".join(filters), "-map", f"[{current}]"]
    else:
        args += ["-map", "0:v"]
    if audio_out:
        args += ["-map", f"[{audio_out}]", "-c:a", "aac", "-b:a", "192k"]

    args += ["-t", f"{duration:.3f}",
             "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
             "-pix_fmt", "yuv420p", "-r", str(timeline.fps),
             "-movflags", "+faststart", str(output)]

    return args, " ".join(shlex.quote(a) for a in args)


def render(timeline: Timeline, output: str | Path, *,
           timeout_s: int = DEFAULT_TIMEOUT_S,
           expect_audio: bool | None = None) -> Render:
    """Render, then VERIFY. The exit code is not the answer."""
    result = Render(path=str(output))

    problems = timeline.problems()
    if problems:
        result.reason = "the timeline is not valid: " + "; ".join(problems[:3])
        return result

    if not inventory.which("ffmpeg"):
        result.reason = ("ffmpeg is not installed, so there is nothing to render "
                         "with. Install it and put it on PATH.")
        return result

    missing = [c.source for c in timeline.clips
               if c.kind in (VIDEO, AUDIO, IMAGE) and not Path(c.source).exists()]
    if missing:
        result.reason = f"source file(s) missing: {', '.join(missing[:3])}"
        return result

    args, readable = build_command(timeline, output)
    result.command = readable

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    try:
        completed = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout_s,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        result.duration_s = time.time() - started
        result.reason = f"ffmpeg did not finish within {timeout_s}s"
        return result
    except Exception as exc:  # noqa: BLE001
        result.reason = f"{type(exc).__name__}: {exc}"
        return result

    result.duration_s = time.time() - started
    result.stderr = (completed.stderr or "")[-2000:]

    if expect_audio is None:
        expect_audio = bool(timeline.of_kind(AUDIO))

    # The only thing that decides whether this worked.
    result.media = verification.verify_render(
        output, expect_audio=expect_audio, expect_aspect=timeline.aspect,
        min_duration_s=max(0.2, timeline.duration_s * 0.8))
    result.ok = result.media.ok
    result.reason = (result.media.reason if result.ok else
                     f"{result.media.reason}"
                     + (f" (ffmpeg said: {result.stderr.strip()[:200]})"
                        if result.stderr.strip() else ""))
    return result


def status() -> dict[str, Any]:
    available = bool(inventory.which("ffmpeg"))
    return {
        "state": "ONLINE" if available else "DEPENDENCY_MISSING",
        "ffmpeg": available,
        "engine": "ffmpeg filter graph built from the timeline structure",
        "supports": ["video clips with seek and crop", "still images",
                     "text and captions", "multi-track audio mixing",
                     "letterboxing to any profile aspect"],
        "verification": ("every render is probed afterwards -- ffmpeg exits 0 on "
                         "files nobody can watch, so the exit code is not the answer"),
        "no_model": "deterministic media operations never go near an AI model",
    }
