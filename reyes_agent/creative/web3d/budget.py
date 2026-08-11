"""Performance budgets, enforced on the built output rather than promised.

    "Do not ship 500MB 3D scenes into a simple landing page."

A budget that lives in a design document is a wish. This measures the files
that were actually written and fails the build when they exceed what a
person on a phone will tolerate.

THE NUMBERS, AND WHY THESE ONES
-------------------------------
They are derived from what the page costs a visitor, not from a round
number that sounded strict. A 4G connection delivers roughly 1.5MB/s in
practice, and the well-known threshold for "this feels broken" is about
three seconds to first meaningful paint. That is the whole budget: ~2MB of
total transfer, of which the 3D portion should be the minority, because
the text is the thing the visitor came for.

WHAT IS NOT COUNTED, AND THE HONESTY ABOUT IT
---------------------------------------------
A CDN import of Three.js is roughly 700KB minified before compression and
is NOT on disk, so a naive directory scan reports a suspiciously tiny site.
Pretending that cost does not exist would make the budget a lie, so it is
added explicitly as `three_estimate_kb` and counted against the total.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Total transfer for the first view.
MAX_TOTAL_KB = 2048

# The 3D portion of it. Geometry, textures and models -- not the page.
MAX_SCENE_KB = 900

# One texture or model. Anything bigger belongs behind a click.
MAX_ASSET_KB = 512

# The page itself must stay readable while the scene loads.
MAX_HTML_KB = 100
MAX_CSS_KB = 60

# Three.js from a CDN, minified, before gzip. Not on disk but really paid for.
THREE_ESTIMATE_KB = 700

_SCENE_SUFFIXES = {".glb", ".gltf", ".fbx", ".obj", ".hdr", ".exr", ".ktx2",
                   ".basis", ".png", ".jpg", ".jpeg", ".webp", ".avif", ".bin"}
_CODE_SUFFIXES = {".js", ".mjs"}


def _kb(path: Path) -> float:
    try:
        return path.stat().st_size / 1024.0
    except OSError:
        return 0.0


def measure(directory: str | Path, *, include_three: bool = True) -> dict[str, Any]:
    """Weigh what was actually written, and say what to do about it."""
    root = Path(directory)
    if not root.is_dir():
        return {"ok": False, "problems": [f"no build directory at {root}"],
                "total_kb": 0.0}

    files = [p for p in root.rglob("*") if p.is_file()]
    scene_kb = sum(_kb(p) for p in files if p.suffix.lower() in _SCENE_SUFFIXES)
    code_kb = sum(_kb(p) for p in files if p.suffix.lower() in _CODE_SUFFIXES)
    html_kb = sum(_kb(p) for p in files if p.suffix.lower() in {".html", ".htm"})
    css_kb = sum(_kb(p) for p in files if p.suffix.lower() == ".css")
    on_disk_kb = sum(_kb(p) for p in files)

    three_kb = THREE_ESTIMATE_KB if include_three else 0.0
    total_kb = on_disk_kb + three_kb

    problems: list[str] = []
    advice: list[str] = []

    if total_kb > MAX_TOTAL_KB:
        problems.append(
            f"the first view would transfer {total_kb / 1024:.1f}MB, over the "
            f"{MAX_TOTAL_KB / 1024:.0f}MB budget -- roughly "
            f"{total_kb / 1536:.1f}s on a normal 4G connection before anything "
            "useful appears")
        advice.append("compress textures to KTX2 or WebP, or load the heavy scene "
                      "after the page is interactive")

    if scene_kb > MAX_SCENE_KB:
        problems.append(f"3D assets are {scene_kb / 1024:.1f}MB, over the "
                        f"{MAX_SCENE_KB / 1024:.1f}MB scene budget")
        advice.append("decimate geometry, or draw the scene procedurally instead "
                      "of shipping a model")

    oversized = []
    for path in files:
        size = _kb(path)
        if path.suffix.lower() in _SCENE_SUFFIXES and size > MAX_ASSET_KB:
            problems.append(f"{path.name} alone is {size / 1024:.1f}MB, over the "
                            f"{MAX_ASSET_KB}KB single-asset limit")
            oversized.append(path)
    if oversized:
        # A budget failure with no remedy is the thing this module exists to
        # avoid being. Say which lever to pull, per file type.
        textures = [p.name for p in oversized
                    if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".avif"}]
        models = [p.name for p in oversized
                  if p.suffix.lower() in {".glb", ".gltf", ".fbx", ".obj", ".bin"}]
        if textures:
            advice.append(f"convert {', '.join(textures[:3])} to KTX2 or WebP and cap "
                          "the longest edge at 2048px")
        if models:
            advice.append(f"run {', '.join(models[:3])} through Draco or meshopt "
                          "compression, or load it after first paint")
        if not textures and not models:
            advice.append("move the oversized asset behind an interaction so it is "
                          "not part of the first view")

    if html_kb > MAX_HTML_KB:
        problems.append(f"HTML is {html_kb:.0f}KB, over {MAX_HTML_KB}KB -- the text "
                        "should arrive almost instantly")
    if css_kb > MAX_CSS_KB:
        problems.append(f"CSS is {css_kb:.0f}KB, over {MAX_CSS_KB}KB")

    return {
        "ok": not problems,
        "total_kb": round(total_kb, 1),
        "on_disk_kb": round(on_disk_kb, 1),
        "three_estimate_kb": three_kb,
        "scene_kb": round(scene_kb, 1),
        "code_kb": round(code_kb, 1),
        "html_kb": round(html_kb, 1),
        "css_kb": round(css_kb, 1),
        "files": len(files),
        "problems": problems,
        "advice": advice,
        "estimated_4g_seconds": round(total_kb / 1536, 2),
        "budgets": {"total_kb": MAX_TOTAL_KB, "scene_kb": MAX_SCENE_KB,
                    "asset_kb": MAX_ASSET_KB, "html_kb": MAX_HTML_KB},
        "note": ("Three.js is counted even though it comes from a CDN and is not "
                 "on disk. A budget that ignores the biggest download is a lie."),
    }


def status() -> dict[str, Any]:
    return {
        "state": "ONLINE",
        "budgets_kb": {"total": MAX_TOTAL_KB, "scene": MAX_SCENE_KB,
                       "single_asset": MAX_ASSET_KB, "html": MAX_HTML_KB,
                       "css": MAX_CSS_KB},
        "three_estimate_kb": THREE_ESTIMATE_KB,
        "measured_on": "the files actually written, not an intention",
    }
