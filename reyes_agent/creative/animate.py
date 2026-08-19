"""ZENO makes its own animation: still images -> a moving clip.

WHAT THIS ADDS OVER THE RENDERER
--------------------------------
`video/renderer.py` composes a timeline of STATIC clips. This adds MOTION --
the two effects that turn stills into something worth watching:

  * Ken Burns: a slow zoom/pan across each image (ffmpeg zoompan)
  * crossfades between images (ffmpeg xfade)

plus an optional caption. The images can be ones the owner already has, or
ones ZENO generated itself (see the create_animation tool).

VERIFIED, NOT ASSUMED
---------------------
ffmpeg exits 0 on files nobody can play, so success is decided by ffprobe --
the same `verification.verify_render` the renderer uses. A clip is "made" only
when there is a real video stream of about the right length.

RIGHTS
------
Every input image is run through the existing rights validator before it is
animated. ZENO does not animate material it has no right to use, and it says
which file it refused.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reyes_agent.capabilities import inventory
from reyes_agent.creative import verification
from reyes_agent.creative.rights import validator
from reyes_agent.creative.video import renderer

# 9:16 for reels/TikTok, 16:9 for YouTube, 1:1 for feed posts.
ASPECTS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}
FPS = 30
DEFAULT_TIMEOUT_S = 180


@dataclass
class Animation:
    ok: bool = False
    path: str = ""
    reason: str = ""
    seconds: float = 0.0
    command: str = ""
    refused: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "path": self.path, "reason": self.reason,
                "seconds": round(self.seconds, 2), "refused": self.refused}


def _filter_complex(count: int, w: int, h: int, seconds_each: float,
                    crossfade: float, caption: str) -> str:
    """Ken Burns per image, then chained crossfades, then a caption.

    Offset for the k-th crossfade is k*(seconds_each - crossfade): each xfade
    consumes `crossfade` seconds of overlap, so the accumulated clip grows by
    (seconds_each - crossfade) each time. Getting that offset wrong is how
    xfade chains produce a black clip that still exits 0 -- which ffprobe
    would then reject.
    """
    frames = max(1, int(round(seconds_each * FPS)))
    parts = []
    for i in range(count):
        # Fill the frame, then a slow zoom. force_original_aspect_ratio keeps
        # the image from distorting; crop trims the overflow.
        parts.append(
            f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},"
            f"zoompan=z='min(zoom+0.0012,1.35)':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={FPS},"
            f"setsar=1,format=yuv420p,setpts=PTS-STARTPTS[v{i}]")

    if count == 1:
        last = "v0"
    else:
        prev = "v0"
        for i in range(1, count):
            offset = i * (seconds_each - crossfade)
            out = f"x{i}"
            parts.append(
                f"[{prev}][v{i}]xfade=transition=fade:"
                f"duration={crossfade}:offset={offset:.3f}[{out}]")
            prev = out
        last = prev

    if caption.strip():
        font = renderer._drawtext_font()
        text = renderer._escape_text(caption.strip())
        parts.append(
            f"[{last}]drawtext={font}text='{text}':"
            f"fontcolor=white:fontsize={max(28, w // 24)}:"
            f"box=1:boxcolor=black@0.5:boxborderw=18:"
            f"x=(w-text_w)/2:y=h-(h/8)[out]")
        last = "out"

    return ";".join(parts), last


def animate_images(image_paths: list[str], output: str | Path, *,
                   caption: str = "", seconds_each: float = 2.5,
                   crossfade: float = 0.7, aspect: str = "9:16",
                   commercial: bool = False,
                   timeout_s: int = DEFAULT_TIMEOUT_S) -> Animation:
    """Animate images into one clip with Ken Burns motion and crossfades."""
    result = Animation(path=str(output))

    paths = [str(p).strip() for p in image_paths if str(p).strip()]
    if not paths:
        result.reason = "no images were given to animate"
        return result
    if not inventory.which("ffmpeg"):
        result.reason = "ffmpeg is not installed, so there is nothing to render with"
        return result

    for path in paths:
        if not Path(path).exists():
            result.reason = f"image not found: {path}"
            return result
        verdict = validator.check(path, intent="publish", commercial=commercial)
        if not verdict.allowed:
            result.refused.append(path)
    if result.refused:
        result.reason = ("refused to animate material without the right to use it: "
                         + ", ".join(Path(p).name for p in result.refused))
        return result

    w, h = ASPECTS.get(aspect, ASPECTS["9:16"])
    crossfade = min(crossfade, seconds_each - 0.3) if len(paths) > 1 else 0.0
    filter_complex, last = _filter_complex(len(paths), w, h, seconds_each,
                                           crossfade, caption)

    binary = inventory.which("ffmpeg") or "ffmpeg"
    args: list[str] = [binary, "-y"]
    for path in paths:
        # A SINGLE frame per image, deliberately. zoompan emits `d` output
        # frames for EVERY input frame, so a looped `-t` input (dozens of
        # frames) makes it emit d x N -- which rendered a 5-second idea as a
        # 102-second clip that still played and still passed a minimum-length
        # check. One input frame -> exactly `d` output frames -> the intended
        # length. Caught only by rendering for real and reading the duration.
        args += ["-i", path]
    args += ["-filter_complex", filter_complex, "-map", f"[{last}]",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS),
             "-movflags", "+faststart", str(output)]
    result.command = " ".join(args)

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    try:
        completed = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout_s,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        result.reason = f"ffmpeg did not finish within {timeout_s}s"
        return result
    except Exception as exc:  # noqa: BLE001
        result.reason = f"{type(exc).__name__}: {exc}"
        return result
    result.seconds = time.time() - started

    # ffprobe decides, not the exit code.
    expected = len(paths) * seconds_each - (len(paths) - 1) * crossfade
    media = verification.verify_render(
        output, expect_audio=False, expect_aspect=aspect,
        min_duration_s=max(0.4, expected * 0.75))
    result.ok = media.ok
    if not result.ok:
        tail = (completed.stderr or "").strip()[-200:]
        result.reason = media.reason + (f" (ffmpeg: {tail})" if tail else "")
        return result

    # verify_render checks a MINIMUM length, which a runaway clip sails past --
    # that is how the zoompan multiplication once shipped a 102s clip for a
    # 5s idea. A clip far LONGER than intended is also broken, so it is caught
    # here rather than posted.
    if expected > 0 and media.duration_s > expected * 1.6 + 1:
        result.ok = False
        result.reason = (f"the clip came out {media.duration_s:.0f}s long but should be "
                         f"about {expected:.0f}s -- something inflated the frame count, "
                         "not shipping it")
        return result

    result.reason = f"rendered {media.reason}, {media.duration_s:.1f}s"
    return result
