"""Rights, render verification and SEO — tested against real files.

The video tests generate REAL media with ffmpeg and probe it, including the
broken cases: a truncated file, an audio-only file, a wrong aspect ratio.
Verification that has only ever seen a mock has not been tested.

Run: `.venv/Scripts/python.exe tests/test_creative_studio.py`
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

_MEDIA: dict[str, Path] = {}


def _ffmpeg() -> str | None:
    from reyes_agent.capabilities import inventory

    return inventory.which("ffmpeg")


def _make_media() -> dict[str, Path]:
    """Generate the real files once: good, audio-only, truncated, landscape."""
    if _MEDIA:
        return _MEDIA
    binary = _ffmpeg()
    if not binary:
        return {}
    out = Path(tempfile.mkdtemp(prefix="zeno_media_"))

    def run(args):
        subprocess.run([binary, "-y", "-loglevel", "error", *args],
                       capture_output=True, timeout=120,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    good = out / "good_vertical.mp4"
    run(["-f", "lavfi", "-i", "testsrc=size=1080x1920:rate=30:duration=2",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
         str(good)])

    silent = out / "silent_landscape.mp4"
    run(["-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30:duration=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent)])

    audio_only = out / "audio_only.m4a"
    run(["-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "aac",
         str(audio_only)])

    truncated = out / "truncated.mp4"
    if good.exists():
        truncated.write_bytes(good.read_bytes()[:2000])

    empty = out / "empty.mp4"
    empty.write_bytes(b"")

    _MEDIA.update({"good": good, "silent": silent, "audio_only": audio_only,
                   "truncated": truncated, "empty": empty,
                   "missing": out / "never_created.mp4"})
    return _MEDIA


def _isolated_rights():
    from reyes_agent.creative.rights import registry

    temp = Path(tempfile.mkdtemp(prefix="zeno_rights_"))
    registry._path = lambda: temp / "rights.json"          # noqa: SLF001
    registry.reset_cache()
    return temp


# --- ACCEPTANCE 80: copyright ------------------------------------------

def test_unknown_rights_are_never_treated_as_permission() -> None:
    from reyes_agent.creative import rights

    _isolated_rights()
    verdict = rights.check("C:/Downloads/some_random_clip.mp4")
    assert verdict.allowed is False
    assert verdict.asset.classification == rights.UNKNOWN_RIGHTS
    assert verdict.alternatives, "a refusal must carry the alternative"


def test_third_party_footage_is_not_reposted() -> None:
    """'Take 10 minutes from this anime and upload it.'"""
    from reyes_agent.creative import rights

    _isolated_rights()
    rights.declare("D:/anime/episode_04.mkv", rights.THIRD_PARTY_COPYRIGHTED,
                   owner="the studio", source="a download")
    verdict = rights.check("D:/anime/episode_04.mkv", intent="publish")

    assert verdict.allowed is False
    assert verdict.decision == "BLOCKED"
    assert "not going to repost" in verdict.say
    joined = " ".join(verdict.alternatives).lower()
    for offer in ("review", "commentary", "analysis", "recap"):
        assert offer in joined, offer


def test_a_suspicious_ownership_claim_is_questioned() -> None:
    """Nobody's home video is called S01E04.1080p.WEB-DL.x265."""
    from reyes_agent.creative import rights

    _isolated_rights()
    asset, why = rights.declare("D:/rips/Show.S01E04.1080p.WEB-DL.x265.mkv",
                                rights.OWNER_CREATED)
    assert asset is None
    assert "looks like a commercial release" in why
    assert rights.check("D:/rips/Show.S01E04.1080p.WEB-DL.x265.mkv").allowed is False


def test_owner_created_material_is_allowed() -> None:
    from reyes_agent.creative import rights

    _isolated_rights()
    asset, _ = rights.declare("D:/my_footage/podcast_ep12.mp4", rights.OWNER_CREATED,
                              owner="me", social=True, commercial=True)
    assert asset is not None
    verdict = rights.check("D:/my_footage/podcast_ep12.mp4", intent="publish")
    assert verdict.allowed is True


def test_a_licence_that_expired_stops_publication() -> None:
    from reyes_agent.creative import rights

    _isolated_rights()
    rights.declare("D:/stock/clip.mp4", rights.USER_LICENSED, social=True,
                   expires_at=time.time() - 10)
    verdict = rights.check("D:/stock/clip.mp4")
    assert verdict.allowed is False and "expired" in verdict.say


def test_personal_licence_blocks_commercial_use() -> None:
    from reyes_agent.creative import rights

    _isolated_rights()
    rights.declare("D:/stock/music.mp3", rights.USER_LICENSED, social=True,
                   commercial=False)
    assert rights.check("D:/stock/music.mp3", commercial=True).allowed is False
    assert rights.check("D:/stock/music.mp3", commercial=False).allowed is True


def test_rights_cannot_be_granted_by_asking_nicely() -> None:
    """A NEEDS_PROOF classification cannot carry publish permissions."""
    from reyes_agent.creative import rights

    _isolated_rights()
    asset, _ = rights.declare("D:/unknown/clip.mp4", rights.UNKNOWN_RIGHTS,
                              social=True, commercial=True)
    assert asset.social_post_allowed is False
    assert asset.commercial_allowed is False


def test_a_repost_with_talking_over_it_is_not_commentary() -> None:
    from reyes_agent.creative.rights import validator

    repost = validator.transformative_plan(borrowed_seconds=560, original_seconds=40)
    assert repost["shape_ok"] is False
    assert any("repost" in p for p in repost["problems"])

    commentary = validator.transformative_plan(borrowed_seconds=90, original_seconds=420)
    assert commentary["shape_ok"] is True
    assert "not legal advice" in commentary["disclaimer"]


def test_one_blocked_asset_blocks_the_publication() -> None:
    from reyes_agent.creative import rights

    _isolated_rights()
    rights.declare("D:/mine/a.mp4", rights.OWNER_CREATED, social=True)
    outcome = rights.check_all(["D:/mine/a.mp4", "D:/unknown/b.mp4"])
    assert outcome["allowed"] is False
    assert "D:/unknown/b.mp4" in outcome["blocked"]


# --- ACCEPTANCE 65/74/75: render verification --------------------------

def test_a_real_render_verifies() -> None:
    media = _make_media()
    if not media or not media["good"].exists():
        return                                   # no ffmpeg on this machine
    from reyes_agent import creative

    result = creative.verify_render(media["good"], expect_audio=True,
                                    expect_aspect="9:16")
    assert result.ok is True, result.reason
    assert result.width == 1080 and result.height == 1920
    assert result.duration_s >= 1.5
    assert result.has_audio is True
    assert result.video_codec


def test_a_missing_file_is_never_a_finished_render() -> None:
    from reyes_agent import creative

    result = creative.verify_render(_make_media().get("missing", "nope.mp4"))
    assert result.ok is False
    assert "no file was produced" in result.reason


def test_an_empty_or_truncated_file_is_caught() -> None:
    media = _make_media()
    if not media:
        return
    from reyes_agent import creative

    empty = creative.verify_render(media["empty"])
    assert empty.ok is False
    assert "bytes" in empty.reason or "no file" in empty.reason

    truncated = creative.verify_render(media["truncated"])
    assert truncated.ok is False, "a truncated container must not pass"


def test_audio_only_output_is_not_a_video() -> None:
    media = _make_media()
    if not media or not media["audio_only"].exists():
        return
    from reyes_agent import creative

    result = creative.verify_render(media["audio_only"])
    assert result.ok is False
    assert "no video stream" in result.reason
    assert "only audio" in result.reason


def test_the_wrong_aspect_ratio_fails_a_vertical_render() -> None:
    media = _make_media()
    if not media or not media["silent"].exists():
        return
    from reyes_agent import creative

    result = creative.verify_render(media["silent"], expect_aspect="9:16")
    assert result.ok is False
    assert "aspect is 16:9" in result.reason

    # ...and it passes when asked for what it actually is.
    assert creative.verify_render(media["silent"], expect_aspect="16:9").ok is True


def test_missing_audio_fails_when_audio_was_expected() -> None:
    media = _make_media()
    if not media or not media["silent"].exists():
        return
    from reyes_agent import creative

    result = creative.verify_render(media["silent"], expect_audio=True)
    assert result.ok is False and "audio" in result.reason


# --- ACCEPTANCE 66: website verification --------------------------------

def test_an_empty_build_directory_is_not_a_website() -> None:
    from reyes_agent import creative

    empty = Path(tempfile.mkdtemp(prefix="zeno_site_"))
    result = creative.verify_site(empty)
    assert result.ok is False
    assert any("index.html is missing" in p for p in result.problems)


def test_a_canvas_only_page_is_flagged() -> None:
    """The 3D rule: meaning must not live only inside WebGL."""
    from reyes_agent import creative

    site = Path(tempfile.mkdtemp(prefix="zeno_site_"))
    (site / "index.html").write_text(
        "<html><head><title>Cyber</title></head><body><canvas id='c'></canvas>"
        + "<script>/* everything is in here */</script>" + "x" * 300 + "</body></html>",
        encoding="utf-8")
    (site / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")
    (site / "sitemap.xml").write_text("<urlset/>", encoding="utf-8")

    result = creative.verify_site(site)
    assert result.ok is False
    assert any("screen readers would see nothing" in p for p in result.problems)


# --- ACCEPTANCE 78: SEO -------------------------------------------------

def _pages():
    from reyes_agent.seo import Page

    body = ("ZENO is a Windows assistant that hears, sees and acts on your machine. "
            "It runs locally and verifies every action it takes before reporting it.")
    return [
        Page(url="https://example.com/", title="ZENO — local AI assistant",
             body_text=body, priority=1.0, changed_at=time.time()),
        Page(url="https://example.com/features", title="ZENO features",
             body_text=body, priority=0.8),
        Page(url="https://example.com/admin", title="Admin", body_text=body),
        Page(url="https://example.com/draft-post", title="Draft",
             body_text=body, indexable=False),
        Page(url="https://example.com/dup", title="ZENO features",
             body_text=body, canonical="https://example.com/features"),
    ]


def test_the_sitemap_excludes_private_noindex_and_duplicate_urls() -> None:
    from reyes_agent import seo

    xml, report = seo.build_sitemap(_pages(), base_url="https://example.com")
    assert "https://example.com/" in xml
    assert "https://example.com/features" in xml
    for excluded in ("/admin", "/draft-post", "/dup"):
        assert excluded not in xml, excluded
    assert report["included"] == 2
    reasons = {e["url"]: e["why"] for e in report["excluded"]}
    assert reasons["https://example.com/admin"] == "private route"
    assert reasons["https://example.com/draft-post"] == "noindex"


def test_robots_cannot_hide_the_whole_production_site() -> None:
    from reyes_agent import seo

    text, problems = seo.build_robots(sitemap_url="https://example.com/sitemap.xml",
                                      disallow=("/", "/admin"))
    assert "Disallow: /admin" in text
    assert "\nDisallow: /\n" not in text
    assert any("hide everything" in p for p in problems)
    assert "Sitemap: https://example.com/sitemap.xml" in text

    bad = seo.engine.validate_robots("User-agent: *\nDisallow: /")
    assert bad["ok"] is False


def test_a_description_is_not_invented() -> None:
    from reyes_agent import seo
    from reyes_agent.seo import Page

    text, problems = seo.engine.describe_page(
        Page(url="https://example.com/x", title="X", body_text=""))
    assert text == ""
    assert any("will not invent" in p for p in problems)


def test_fabricated_claims_are_stripped_from_descriptions() -> None:
    from reyes_agent import seo
    from reyes_agent.seo import Page

    page = Page(url="https://example.com/x", title="X",
                description="Award-winning tool rated 4.9 used by 10000 customers.",
                body_text="A tool for editing text on Windows.")
    text, problems = seo.engine.describe_page(page)
    assert problems, "an invented claim must be reported"
    assert "award-winning" not in text.lower()


def test_structured_data_refuses_unsourced_ratings_and_prices() -> None:
    from reyes_agent import seo

    payload, problems = seo.json_ld("Product", {
        "name": "ZENO", "description": "A local assistant",
        "aggregateRating": {"ratingValue": "4.9", "reviewCount": "812"},
        "offers": {"price": "0"}})
    assert "aggregateRating" not in payload
    assert "offers" not in payload
    assert len(problems) == 2
    assert "ZENO" in payload

    sourced, problems = seo.json_ld("Product", {
        "name": "ZENO", "aggregateRating": {"ratingValue": "4.9"},
        "aggregateRating_source": "our own review database"})
    assert "aggregateRating" in sourced and not problems


def test_duplicate_titles_are_reported() -> None:
    from reyes_agent import seo

    problems = seo.audit(_pages())["problems"]
    assert any("share the title" in p for p in problems)


def test_seo_files_are_really_written() -> None:
    from reyes_agent import seo

    out = Path(tempfile.mkdtemp(prefix="zeno_seo_"))
    result = seo.write_site_files(out, _pages(), base_url="https://example.com",
                                  disallow=("/admin",))
    assert (out / "sitemap.xml").is_file()
    assert (out / "robots.txt").is_file()
    assert result["sitemap"]["bytes"] > 100
    assert result["robots"]["ok"] is True

    xml = (out / "sitemap.xml").read_text(encoding="utf-8")
    assert xml.startswith("<?xml")
    assert "sitemaps.org/schemas/sitemap" in xml


def test_head_tags_are_escaped_and_canonical() -> None:
    from reyes_agent import seo
    from reyes_agent.seo import Page

    tags = seo.head_tags(Page(url="https://example.com/x",
                              title='Tools & "gear" <fast>',
                              body_text="A page about tools and gear for Windows users "
                                        "who want to work faster every day."),
                         site_name="ZENO")
    assert "&amp;" in tags and "&quot;" in tags and "<fast>" not in tags
    assert 'rel="canonical" href="https://example.com/x"' in tags
    assert 'content="index, follow"' in tags


def test_noindex_pages_say_noindex() -> None:
    from reyes_agent import seo
    from reyes_agent.seo import Page

    tags = seo.head_tags(Page(url="https://example.com/draft", title="Draft",
                              body_text="x" * 200, indexable=False))
    assert 'content="noindex, nofollow"' in tags


# --- ACCEPTANCE 45: no promises ----------------------------------------

def test_seo_never_promises_a_ranking() -> None:
    from reyes_agent import seo

    outcome = seo.report(deployed=True, sitemap_written=True, sitemap_submitted=True)

    # Check what would be SHOWN. `never_claimed` necessarily contains those
    # words -- it is the list of things being disclaimed.
    shown = (outcome["say"] + " " + " ".join(outcome["facts"])).lower()
    for promise in ("#1", "guarantee", "instant index", "top of google", "rank first"):
        assert promise not in shown, promise

    assert "the site is deployed and responding" in outcome["facts"]
    assert "guaranteed visibility" in outcome["never_claimed"]
    assert seo.report()["say"] == "nothing verified yet"


def test_nothing_raises() -> None:
    from reyes_agent import creative, seo

    for call in (creative.status, creative.rights.status, creative.verification.status,
                 seo.status):
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
