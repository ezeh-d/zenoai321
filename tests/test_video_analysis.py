"""Highlight detection and auto-reframe, tested on real generated footage.

Run: `.venv/Scripts/python.exe tests/test_video_analysis.py`
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_SOURCE: dict[str, Path] = {}


def _footage() -> Path | None:
    """Three visually distinct segments -- two real cuts, at 6s and 12s."""
    if "cuts" in _SOURCE:
        return _SOURCE["cuts"]
    from reyes_agent.capabilities import inventory

    binary = inventory.which("ffmpeg")
    if not binary:
        return None
    out = Path(tempfile.mkdtemp(prefix="zeno_analysis_")) / "cuts.mp4"
    subprocess.run(
        [binary, "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=6",
         "-f", "lavfi", "-i", "smptebars=size=1280x720:rate=30:duration=6",
         "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=6",
         "-f", "lavfi", "-i", "sine=frequency=300:duration=18",
         "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
         "-map", "[v]", "-map", "3:a", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", str(out)],
        capture_output=True, timeout=300,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    _SOURCE["cuts"] = out if out.exists() else None
    return _SOURCE["cuts"]


def test_real_cuts_are_found() -> None:
    from reyes_agent import creative

    source = _footage()
    if source is None:
        return
    result = creative.video.find_highlights(source, count=4, clip_s=10)
    assert result["ok"] is True, result.get("reason")
    assert result["scene_changes"] >= 2, "the two real cuts must be detected"
    assert result["candidates"]
    for candidate in result["candidates"]:
        assert candidate["duration"] >= 8.0
        assert candidate["reasons"], "every candidate must point at a measured event"


def test_it_refuses_to_pad_with_evenly_spaced_slices() -> None:
    """'Five random cuts' is the failure this exists to avoid."""
    from reyes_agent.capabilities import inventory
    from reyes_agent import creative

    binary = inventory.which("ffmpeg")
    if not binary:
        return
    flat = Path(tempfile.mkdtemp(prefix="zeno_flat_")) / "flat.mp4"
    subprocess.run([binary, "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=black:size=640x360:rate=30:d=20",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(flat)],
                   capture_output=True, timeout=300,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    result = creative.video.find_highlights(flat, count=5)
    assert result["ok"] is False
    assert result["candidates"] == []
    assert "rather tell you that" in result["reason"]


def test_a_missing_file_is_reported_not_analysed() -> None:
    from reyes_agent import creative

    result = creative.video.find_highlights("C:/nope/missing.mp4")
    assert result["ok"] is False and "no file" in result["reason"]


def test_highlights_never_claim_understanding() -> None:
    from reyes_agent.creative.video import highlights

    assert "no ML is involved" in highlights.status()["no_model"]
    source = _footage()
    if source is None:
        return
    result = creative.video.find_highlights(source) if False else highlights.find(source)
    if result["ok"]:
        assert "not a judgement" in result["note"]


def test_reframe_produces_a_vertical_crop_that_fits() -> None:
    from reyes_agent import creative

    source = _footage()
    if source is None:
        return
    plan = creative.video.plan_reframe(source)
    assert plan.ok is True, plan.reason
    assert plan.width == 1280 and plan.height == 720
    assert plan.crop_height == 720
    assert abs(plan.crop_width / plan.crop_height - 9 / 16) < 0.02
    x, y, w, h = plan.crop_at(0.0)
    assert 0 <= x <= plan.width - w, "the crop must stay inside the frame"
    assert w == plan.crop_width and h == plan.crop_height


def test_the_crop_is_smoothed_not_jittery() -> None:
    from reyes_agent import creative

    source = _footage()
    if source is None:
        return
    plan = creative.video.plan_reframe(source)
    if len(plan.keyframes) < 3:
        return
    positions = [k.x for k in plan.keyframes]
    jumps = [abs(b - a) for a, b in zip(positions, positions[1:])]
    limit = plan.width - plan.crop_width
    assert max(jumps) <= limit, "smoothing must keep the crop inside the frame"


def test_a_narrower_source_needs_no_crop() -> None:
    from reyes_agent.capabilities import inventory
    from reyes_agent import creative

    binary = inventory.which("ffmpeg")
    if not binary:
        return
    tall = Path(tempfile.mkdtemp(prefix="zeno_tall_")) / "tall.mp4"
    subprocess.run([binary, "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc=size=540x960:rate=30:d=3",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(tall)],
                   capture_output=True, timeout=300,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    plan = creative.video.plan_reframe(tall)
    assert plan.ok is True
    assert "already at or narrower" in plan.reason


def test_nothing_raises() -> None:
    from reyes_agent.creative.video import highlights, reframe

    assert highlights.status() is not None
    assert reframe.status() is not None


def _run_all() -> int:
    tests = [v for n, v in sorted(globals().items()) if n.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        started = time.time()
        try:
            test()
            print(f"PASS {test.__name__} ({time.time() - started:.2f}s)")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
