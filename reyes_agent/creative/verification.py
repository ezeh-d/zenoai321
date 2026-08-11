"""A render is finished when the file plays, not when the command returns.

    "Do not show 'Video Generated' if no playable video exists."

THE FAILURE THIS PREVENTS
-------------------------
Encoders exit 0 and leave a 48-byte file. A pipeline crashes after writing
the container header. A generation step produces something with a valid
duration and no video stream at all. In every one of those cases the naive
check -- did the command succeed, does the path exist -- says yes.

So a render is verified by ASKING THE FILE what it contains. `ffprobe` is
installed here, so this is a real measurement rather than an assertion: the
duration, the streams, the codec, the resolution and the audio all come out
of the container.

`verify_render()` returns a failure with a specific reason. "Render failed"
teaches nobody anything; "the file has no video stream, only audio" says
which stage of the pipeline broke.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reyes_agent.capabilities import inventory

# Below this a "video" is a container header and an error.
MIN_BYTES = 4096
MIN_DURATION_S = 0.4

# Probing must not hang a creative job forever.
PROBE_TIMEOUT_S = 30


@dataclass
class Media:
    ok: bool = False
    path: str = ""
    reason: str = ""
    bytes: int = 0
    duration_s: float = 0.0
    width: int = 0
    height: int = 0
    video_codec: str = ""
    audio_codec: str = ""
    fps: float = 0.0
    has_audio: bool = False
    checks: list[str] = field(default_factory=list)

    @property
    def aspect(self) -> str:
        if not self.width or not self.height:
            return ""
        from math import gcd

        divisor = gcd(self.width, self.height) or 1
        return f"{self.width // divisor}:{self.height // divisor}"

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "path": self.path, "reason": self.reason,
                "bytes": self.bytes, "duration_s": round(self.duration_s, 2),
                "width": self.width, "height": self.height, "aspect": self.aspect,
                "video_codec": self.video_codec, "audio_codec": self.audio_codec,
                "fps": round(self.fps, 2), "has_audio": self.has_audio,
                "checks": self.checks}

    def summary(self) -> str:
        if not self.ok:
            return f"NOT verified: {self.reason}"
        audio = f", {self.audio_codec} audio" if self.has_audio else ", no audio"
        return (f"{self.width}x{self.height} ({self.aspect}) {self.video_codec}, "
                f"{self.duration_s:.1f}s at {self.fps:.0f}fps{audio}, "
                f"{self.bytes / 1_048_576:.1f}MB")


def probe(path: str | Path) -> dict[str, Any] | None:
    """Ask the container what it holds. None when ffprobe cannot answer."""
    binary = inventory.which("ffprobe")
    if not binary:
        return None
    try:
        result = subprocess.run(
            [binary, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT_S,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode != 0:
            return None
        return json.loads(result.stdout or "{}")
    except Exception:  # noqa: BLE001
        return None


def _fps(stream: dict[str, Any]) -> float:
    raw = str(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1")
    try:
        numerator, _, denominator = raw.partition("/")
        return float(numerator) / float(denominator or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


def verify_render(path: str | Path, *, expect_audio: bool = False,
                  min_duration_s: float = MIN_DURATION_S,
                  expect_aspect: str = "", expect_min_height: int = 0) -> Media:
    """Is there actually a playable video here, matching what was asked for."""
    target = Path(path)
    media = Media(path=str(target))

    if not target.exists():
        media.reason = "no file was produced"
        return media
    media.bytes = target.stat().st_size
    media.checks.append("file exists")

    if media.bytes < MIN_BYTES:
        media.reason = (f"the file is only {media.bytes} bytes -- that is a container "
                        "header, not a video")
        return media
    media.checks.append("file has real content")

    data = probe(target)
    if data is None:
        media.reason = ("ffprobe could not read it, so I cannot say it plays. "
                        + ("ffprobe is not installed here."
                           if not inventory.which("ffprobe")
                           else "The file is probably corrupt."))
        return media
    media.checks.append("container is readable")

    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if video is None:
        media.reason = ("there is no video stream in that file"
                        + (" -- only audio" if audio else " at all"))
        return media
    media.checks.append("has a video stream")

    media.video_codec = str(video.get("codec_name") or "")
    media.width = int(video.get("width") or 0)
    media.height = int(video.get("height") or 0)
    media.fps = _fps(video)
    media.has_audio = audio is not None
    media.audio_codec = str((audio or {}).get("codec_name") or "")

    try:
        media.duration_s = float((data.get("format") or {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        media.duration_s = 0.0

    if media.duration_s < min_duration_s:
        media.reason = (f"it is only {media.duration_s:.2f}s long, which is not a "
                        "video anyone asked for")
        return media
    media.checks.append("duration is real")

    if not media.width or not media.height:
        media.reason = "the video stream reports no dimensions"
        return media
    media.checks.append("has real dimensions")

    if expect_min_height and media.height < expect_min_height:
        media.reason = (f"rendered at {media.width}x{media.height}, below the "
                        f"{expect_min_height}p that was asked for")
        return media

    if expect_aspect and media.aspect != expect_aspect:
        media.reason = (f"aspect is {media.aspect}, not the {expect_aspect} that was "
                        "asked for -- it would be letterboxed or cropped")
        return media
    if expect_aspect:
        media.checks.append(f"aspect is {expect_aspect}")

    if expect_audio and not media.has_audio:
        media.reason = "audio was expected and the file has none"
        return media
    if expect_audio:
        media.checks.append("has audio")

    media.ok = True
    media.reason = "verified playable"
    return media


@dataclass
class Site:
    ok: bool = False
    reason: str = ""
    files: dict[str, bool] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "reason": self.reason, "files": self.files,
                "problems": self.problems}


# What a built site must actually contain before ZENO calls it done.
_REQUIRED = ("index.html",)
_SEO_FILES = ("robots.txt", "sitemap.xml")


def verify_site(directory: str | Path, *, require_seo: bool = True) -> Site:
    """Did a build really produce a site. Checks files, not a build log."""
    root = Path(directory)
    site = Site()

    if not root.is_dir():
        site.reason = f"there is no build directory at {root}"
        return site

    for name in _REQUIRED:
        present = (root / name).is_file()
        site.files[name] = present
        if not present:
            site.problems.append(f"{name} is missing -- there is no site here")

    index = root / "index.html"
    if index.is_file():
        try:
            markup = index.read_text(encoding="utf-8", errors="replace")
        except OSError:
            markup = ""
        if len(markup) < 200:
            site.problems.append("index.html is nearly empty")
        if "<title" not in markup.lower():
            site.problems.append("index.html has no <title>")
        # The brief's 3D rule: meaning must not live only in a canvas.
        stripped = markup.lower()
        if "<canvas" in stripped and stripped.count("<h1") == 0:
            site.problems.append(
                "the page renders into a canvas but has no <h1> -- search engines "
                "and screen readers would see nothing")

    if require_seo:
        for name in _SEO_FILES:
            present = (root / name).is_file()
            site.files[name] = present
            if not present:
                site.problems.append(f"{name} is missing")

    site.ok = not site.problems
    site.reason = ("the build produced a real site" if site.ok
                   else f"{len(site.problems)} problem(s) with the build output")
    return site


def status() -> dict[str, Any]:
    probe_available = bool(inventory.which("ffprobe"))
    return {
        "state": "ONLINE" if probe_available else "DEGRADED",
        "ffprobe": probe_available,
        "video_checks": ["file exists", "real size", "readable container",
                         "video stream present", "duration", "dimensions",
                         "aspect", "audio when expected"],
        "site_checks": ["index.html present and non-trivial", "has a title",
                        "canvas pages still carry semantic content",
                        "robots.txt", "sitemap.xml"],
        "note": ("A render counts as done when the file plays, not when the command "
                 "returns zero. Encoders exit 0 and leave 48-byte files."),
    }
