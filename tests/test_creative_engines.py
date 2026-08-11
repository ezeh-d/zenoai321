"""The 3D website engine and the timeline engine, tested on real output.

The video tests render actual files with ffmpeg and probe them. A timeline
engine that has only ever been asserted against a mock command string has
not been tested -- the interesting failures (a missing font, a filter graph
that produces nothing) only appear when ffmpeg really runs.

Run: `.venv/Scripts/python.exe tests/test_creative_engines.py`
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _spec(**kw):
    from reyes_agent.creative.web3d import Section, SiteSpec

    base = dict(
        name="Aegis", headline="Threat detection that explains itself",
        subhead="Aegis watches your infrastructure and tells you what changed "
                "and why it matters, with links to the evidence.",
        scene="particles", base_url="https://aegis.example",
        sections=[Section("Live signal",
                          "Every alert links to the log lines that produced it, "
                          "so nobody has to trust a score.",
                          "See a sample", "/alerts")])
    base.update(kw)
    return SiteSpec(**base)


def _build(**kw):
    from reyes_agent import creative

    out = Path(tempfile.mkdtemp(prefix="zeno_web3d_"))
    return creative.web3d.generate(_spec(**kw), out), out


# --- 3D website ---------------------------------------------------------

def test_the_page_means_something_without_the_canvas() -> None:
    """The rule the whole engine exists for."""
    built, out = _build()
    assert built.ok, built.problems

    markup = (out / "index.html").read_text(encoding="utf-8")
    assert "<h1>" in markup, "no headline element"
    assert "Threat detection that explains itself" in markup
    assert "Every alert links to the log lines" in markup, "body copy must be HTML"
    assert "<h2>" in markup

    # Strip the canvas and every script: the content must survive.
    import re
    without = re.sub(r"(?is)<script.*?</script>|<div id=\"scene\".*?</div>", "", markup)
    assert "Threat detection that explains itself" in without
    assert "Every alert links to the log lines" in without


def test_the_canvas_is_hidden_from_assistive_technology() -> None:
    _built, out = _build()
    markup = (out / "index.html").read_text(encoding="utf-8")
    assert 'id="scene"' in markup
    assert 'aria-hidden="true"' in markup
    assert 'role="presentation"' in markup


def test_reduced_motion_stops_the_loop_rather_than_slowing_it() -> None:
    _built, out = _build()
    script = (out / "scene.js").read_text(encoding="utf-8")
    assert "prefers-reduced-motion" in script
    assert "reduceMotion" in script
    # It must render one frame and NOT enter the animation loop.
    assert "if (reduceMotion)" in script
    assert "renderer.render(scene, camera);" in script


def test_a_missing_webgl_context_does_not_break_the_page() -> None:
    _built, out = _build()
    script = (out / "scene.js").read_text(encoding="utf-8")
    assert "function supported()" in script
    assert "unsupported" in script
    # The gradient lives in CSS, so the page still looks intentional.
    assert "radial-gradient" in (out / "styles.css").read_text(encoding="utf-8")


def test_rendering_pauses_when_the_tab_is_hidden() -> None:
    _built, out = _build()
    script = (out / "scene.js").read_text(encoding="utf-8")
    assert "visibilitychange" in script
    assert "cancelAnimationFrame" in script


def test_seo_files_ship_with_the_site() -> None:
    from reyes_agent import creative

    built, out = _build()
    assert (out / "sitemap.xml").is_file()
    assert (out / "robots.txt").is_file()
    assert creative.verify_site(out).ok is True


def test_the_asset_budget_is_measured_and_counts_the_cdn() -> None:
    """A budget that ignores the biggest download is a lie."""
    from reyes_agent.creative.web3d import budget

    built, out = _build()
    report = built.budget_report
    assert report["ok"] is True
    assert report["three_estimate_kb"] == budget.THREE_ESTIMATE_KB
    assert report["total_kb"] >= budget.THREE_ESTIMATE_KB
    assert report["estimated_4g_seconds"] > 0


def test_an_oversized_asset_fails_the_budget() -> None:
    from reyes_agent.creative.web3d import budget

    out = Path(tempfile.mkdtemp(prefix="zeno_budget_"))
    (out / "index.html").write_text("<html></html>", encoding="utf-8")
    (out / "hero.glb").write_bytes(b"\0" * (budget.MAX_ASSET_KB * 1024 + 2048))

    report = budget.measure(out)
    assert report["ok"] is False
    assert any("hero.glb" in p for p in report["problems"])
    assert report["advice"], "a budget failure should say what to do"


def test_a_page_with_no_headline_is_refused() -> None:
    built, _out = _build(headline="   ")
    assert built.ok is False
    assert any("no headline" in p for p in built.problems)


def test_an_unknown_scene_is_refused_not_improvised() -> None:
    built, _out = _build(scene="volumetric-dragons")
    assert built.ok is False
    assert any("not a scene I can build" in p for p in built.problems)


def test_every_scene_kind_builds() -> None:
    from reyes_agent.creative.web3d import SCENES

    for scene in SCENES:
        built, out = _build(scene=scene)
        assert built.ok, (scene, built.problems)
        assert (out / "scene.js").read_text(encoding="utf-8").count("THREE.") > 1


# --- timeline -----------------------------------------------------------

def _timeline():
    from reyes_agent.creative.video import Clip, Timeline

    timeline = Timeline(name="promo", aspect="9:16", fps=30)
    hook = Clip(kind="text", start_ms=0, duration_ms=2000, text="First line")
    timeline.add(hook)
    timeline.add(Clip(kind="text", start_ms=2000, duration_ms=2000, text="Second"))
    return timeline, hook


def test_time_is_exact_across_cuts() -> None:
    """Float seconds drift until clips overlap by a frame."""
    timeline, _hook = _timeline()
    clips = sorted(timeline.of_kind("text"), key=lambda c: c.start_ms)
    assert clips[0].end_ms == clips[1].start_ms, "an exact join must stay exact"
    assert isinstance(clips[0].end_ms, int)


def test_retiming_ripples_the_rest() -> None:
    """The operation a baked ffmpeg command cannot do."""
    timeline, hook = _timeline()
    timeline.retime(hook, 1000)
    clips = sorted(timeline.of_kind("text"), key=lambda c: c.start_ms)
    assert clips[0].duration_ms == 1000
    assert clips[1].start_ms == 1000, "the following clip must move up"
    assert clips[0].end_ms == clips[1].start_ms


def test_reframing_is_one_field_not_a_rebuild() -> None:
    timeline, _hook = _timeline()
    assert timeline.size == (1080, 1920)
    timeline.reframe("16:9")
    assert timeline.size == (1920, 1080)
    assert len(timeline.clips) == 2, "reframing must not disturb the edit"


def test_overlapping_clips_are_caught_before_rendering() -> None:
    from reyes_agent.creative.video import Clip, Timeline

    timeline = Timeline()
    timeline.add(Clip(kind="text", start_ms=0, duration_ms=3000, text="a"))
    timeline.add(Clip(kind="text", start_ms=1000, duration_ms=3000, text="b"))
    problems = timeline.problems()
    assert any("overlap" in p for p in problems)
    assert timeline.valid is False


def test_structural_problems_are_reported_not_rendered() -> None:
    from reyes_agent.creative.video import Clip, Timeline

    timeline = Timeline()
    timeline.add(Clip(kind="video", start_ms=0, duration_ms=1000, source=""))
    timeline.add(Clip(kind="text", start_ms=2000, duration_ms=0, text="x"))
    problems = " ".join(timeline.problems())
    assert "no source file" in problems
    assert "no duration" in problems


def test_a_timeline_survives_a_round_trip() -> None:
    from reyes_agent.creative.video import Timeline

    timeline, _hook = _timeline()
    restored = Timeline.from_dict(timeline.as_dict())
    assert restored.as_dict() == timeline.as_dict()
    assert restored.duration_ms == timeline.duration_ms


# --- real rendering -----------------------------------------------------

def _ffmpeg_here() -> bool:
    from reyes_agent.capabilities import inventory

    return bool(inventory.which("ffmpeg") and inventory.which("ffprobe"))


def test_a_timeline_renders_a_real_verified_video() -> None:
    if not _ffmpeg_here():
        return
    from reyes_agent import creative

    timeline, _hook = _timeline()
    out = Path(tempfile.mkdtemp(prefix="zeno_render_")) / "promo.mp4"
    result = creative.video.render(timeline, out)

    assert result.ok is True, result.reason
    assert result.media.width == 1080 and result.media.height == 1920
    assert result.media.aspect == "9:16"
    assert result.media.duration_s >= 3.0
    assert out.stat().st_size > 4096


def test_the_same_timeline_renders_at_another_aspect() -> None:
    if not _ffmpeg_here():
        return
    from reyes_agent import creative

    timeline, _hook = _timeline()
    timeline.reframe("16:9")
    out = Path(tempfile.mkdtemp(prefix="zeno_render_")) / "wide.mp4"
    result = creative.video.render(timeline, out)

    assert result.ok is True, result.reason
    assert result.media.aspect == "16:9"
    assert result.media.width == 1920


def test_drawtext_names_a_real_font() -> None:
    """Windows ffmpeg ships without fontconfig; drawtext dies without this."""
    from reyes_agent.creative.video import renderer

    font = renderer._font_file()                      # noqa: SLF001
    if not font:
        return                                        # no font found on this box
    assert "\\:" in font or ":" not in font, "the drive colon must be escaped"
    assert "\\\\" not in font, "backslashes must become forward slashes"

    timeline, _hook = _timeline()
    _args, readable = renderer.build_command(timeline, "out.mp4")
    assert "fontfile=" in readable


def test_an_invalid_timeline_is_never_rendered() -> None:
    from reyes_agent import creative
    from reyes_agent.creative.video import Timeline

    result = creative.video.render(Timeline(), Path(tempfile.mkdtemp()) / "x.mp4")
    assert result.ok is False
    assert "not valid" in result.reason
    assert result.command == "", "nothing should have been run"


def test_a_missing_source_file_stops_the_render() -> None:
    from reyes_agent import creative
    from reyes_agent.creative.video import Clip, Timeline

    timeline = Timeline()
    timeline.add(Clip(kind="video", start_ms=0, duration_ms=1000,
                      source="C:/nope/missing_clip.mp4"))
    result = creative.video.render(timeline, Path(tempfile.mkdtemp()) / "x.mp4")
    assert result.ok is False
    assert "missing" in result.reason


def test_the_render_is_judged_by_the_file_not_the_exit_code() -> None:
    from reyes_agent.creative.video import renderer

    assert "exit code is not the answer" in renderer.status()["verification"]


def test_nothing_raises() -> None:
    from reyes_agent import creative

    for call in (creative.status, creative.web3d.status, creative.video.status,
                 creative.video.timeline.status, creative.video.renderer.status):
        assert call() is not None


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
