"""ZENO's own animation: draw -> animate -> a real, verified clip.

One test renders for REAL (ffmpeg is present), because the bug that mattered
most here -- zoompan multiplying a 5-second idea into a 102-second clip -- was
invisible to every check except reading the actual output duration. The rest
mock the network and the renderer.
"""

from __future__ import annotations

import os
import shutil

import pytest

os.environ.setdefault("ZENO_ENV", "test")

from reyes_agent.creative import animate  # noqa: E402
from reyes_agent.creative.rights import registry  # noqa: E402
from reyes_agent.tools import TOOLS  # noqa: E402

_HAS_FFMPEG = shutil.which("ffmpeg") is not None


@pytest.fixture()
def isolated_rights(tmp_path, monkeypatch):
    """Keep declarations out of the real rights store."""
    store = tmp_path / "rights.json"
    monkeypatch.setattr(registry, "_path", lambda: store)
    registry.reset_cache()
    yield
    registry.reset_cache()


def _images(tmp_path, n=3, declare=True):
    from PIL import Image

    paths = []
    for i, colour in enumerate([(90, 140, 220), (200, 90, 120), (120, 200, 140),
                                (220, 200, 90), (150, 110, 200), (90, 200, 200)][:n]):
        p = tmp_path / f"img{i}.png"
        Image.new("RGB", (1200, 800), colour).save(p)
        if declare:
            registry.declare(str(p), registry.OWNER_CREATED, owner="owner", social=True)
        paths.append(str(p))
    return paths


# --- the rights guardrail ------------------------------------------------
def test_it_refuses_images_it_cannot_clear(tmp_path, isolated_rights):
    paths = _images(tmp_path, 2, declare=False)   # undeclared -> unknown rights
    result = animate.animate_images(paths, tmp_path / "out.mp4")
    assert result.ok is False
    assert result.refused           # named the ones it would not use


def test_missing_file_is_reported(tmp_path, isolated_rights):
    result = animate.animate_images([str(tmp_path / "nope.png")], tmp_path / "out.mp4")
    assert result.ok is False
    assert "not found" in result.reason


def test_no_images_is_reported(tmp_path):
    assert animate.animate_images([], tmp_path / "out.mp4").ok is False


# --- the real thing ------------------------------------------------------
@pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg not installed")
def test_it_renders_a_real_clip_of_about_the_right_length(tmp_path, isolated_rights):
    paths = _images(tmp_path, 3)
    out = tmp_path / "real.mp4"
    result = animate.animate_images(paths, out, caption="ZENO", seconds_each=1.5,
                                    aspect="9:16")
    assert result.ok, result.reason
    assert out.exists() and out.stat().st_size > 2000

    # The clip must be about 3*1.5 - 2*0.7 = 3.1s, NOT 100s. This is the exact
    # assertion the zoompan multiplication bug would have failed.
    import subprocess

    from reyes_agent.capabilities import inventory
    ffprobe = inventory.which("ffprobe") or "ffprobe"
    dur = float(subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip())
    assert 2.0 < dur < 5.0, f"clip is {dur}s, expected ~3.1s"


@pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg not installed")
def test_a_single_image_still_animates(tmp_path, isolated_rights):
    paths = _images(tmp_path, 1)
    result = animate.animate_images(paths, tmp_path / "one.mp4", seconds_each=1.5)
    assert result.ok, result.reason


def test_the_duration_guard_rejects_an_inflated_clip(tmp_path, isolated_rights, monkeypatch):
    """If something inflates the frame count again, it must be refused, not
    posted. Simulated by making verify_render report a wild duration."""
    paths = _images(tmp_path, 2)

    from reyes_agent.creative import verification

    class FakeMedia:
        ok = True
        reason = "verified playable"
        duration_s = 90.0        # should have been ~4s

    monkeypatch.setattr(animate.inventory, "which", lambda name: "ffmpeg")
    monkeypatch.setattr(animate.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stderr": "", "returncode": 0})())
    monkeypatch.setattr(verification, "verify_render", lambda *a, **k: FakeMedia())
    result = animate.animate_images(paths, tmp_path / "x.mp4", seconds_each=2.0)
    assert result.ok is False
    assert "inflated" in result.reason or "should be about" in result.reason


# --- the tools -----------------------------------------------------------
def test_create_animation_draws_and_animates(tmp_path, isolated_rights, monkeypatch):
    """ZENO generates its own frames (mocked network) and animates them."""
    from PIL import Image

    made = []

    def fake_generate(prompt, index):
        p = tmp_path / f"gen{index}.jpg"
        Image.new("RGB", (1024, 1024), (50 + index * 40, 100, 160)).save(p)
        made.append(str(p))
        return str(p)

    import reyes_agent.tools.animation_tools as at
    monkeypatch.setattr(at, "_generate_frame", fake_generate)
    monkeypatch.setattr(at, "_OUT_DIR", tmp_path)

    if not _HAS_FFMPEG:
        pytest.skip("ffmpeg not installed")
    out = TOOLS["create_animation"].func(concept="a glowing AI orb", scenes=2,
                                         caption="ZENO", seconds_each=1.2)
    assert "animation" in out.lower()
    assert len(made) == 2          # it drew its own frames


def test_create_animation_handles_a_dead_image_service(tmp_path, monkeypatch):
    import reyes_agent.tools.animation_tools as at
    monkeypatch.setattr(at, "_generate_frame", lambda p, i: None)
    out = TOOLS["create_animation"].func(concept="anything")
    assert "couldn't generate" in out.lower()


def test_animate_files_refuses_unowned_then_accepts_with_declaration(tmp_path, isolated_rights, monkeypatch):
    paths = _images(tmp_path, 2, declare=False)
    import reyes_agent.tools.animation_tools as at
    monkeypatch.setattr(at, "_OUT_DIR", tmp_path)

    refused = TOOLS["animate_files"].func(paths=paths)
    assert "rights" in refused.lower() or "clear" in refused.lower()

    if not _HAS_FFMPEG:
        pytest.skip("ffmpeg not installed")
    ok = TOOLS["animate_files"].func(paths=paths, i_own_these=True, seconds_each=1.2)
    assert "animated" in ok.lower()


# --- registration + routing ---------------------------------------------
def test_animation_tools_registered_and_routed():
    from reyes_agent.routing import capability

    for name in ("create_animation", "animate_files"):
        assert name in TOOLS
    for msg in ("make an animation about my project", "create a reel",
                "draw me a picture of a dragon"):
        assert "creative" in capability.tools_for(msg).capabilities, msg
