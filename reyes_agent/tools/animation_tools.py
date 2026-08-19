"""ZENO makes its own animated clips -- draw, animate, ready to post.

create_animation is the whole loop: ZENO generates its OWN images from a
concept (so provenance is certain and the rights layer clears them), then
animates them with Ken Burns motion and crossfades into a real MP4 that the
social system can post. animate_files does the same from images the owner
already has and vouches for.

Nothing here posts or sells on its own. It produces a file; posting goes
through the social system's approval gate, and selling goes through the
owner-approved paid-work flow.
"""

from __future__ import annotations

import time
from pathlib import Path

from reyes_agent import config
from reyes_agent.tools import register

_OUT_DIR = Path(config.PROJECT_ROOT) / "data" / "animations"


def _generate_frame(prompt: str, index: int) -> str | None:
    """One image from ZENO's existing image generator, saved locally."""
    import urllib.parse

    import requests

    seed = abs(hash(prompt)) % 100000 + index
    url = (f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}"
           f"?width=1024&height=1024&nologo=true&seed={seed}")
    try:
        resp = requests.get(url, timeout=90)
        resp.raise_for_status()
    except requests.RequestException:
        return None
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = _OUT_DIR / f"frame-{int(time.time())}-{index}.jpg"
    path.write_bytes(resp.content)
    return str(path)


@register(
    name="create_animation",
    description=(
        "Create an original short animated video from a concept: ZENO draws "
        "its OWN images and animates them with motion (slow zoom/pan) and "
        "crossfades into a real MP4 -- ready to post. Use for 'make an "
        "animation about X', 'create a reel for my ZENO project'. Produces a "
        "file and verifies it actually plays; it does not post or sell on its "
        "own."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "concept": {"type": "string", "description": "What the animation is about."},
            "scenes": {"type": "integer", "description": "How many images/scenes (2-6). Default 3."},
            "caption": {"type": "string", "description": "Optional on-screen caption."},
            "aspect": {"type": "string", "description": "9:16 (reels/TikTok, default), 16:9, 1:1, 4:5."},
            "style": {"type": "string", "description": "Optional art style, e.g. 'anime', 'cinematic', 'watercolour'."},
            "seconds_each": {"type": "number", "description": "Seconds per scene. Default 2.5."},
        },
        "required": ["concept"],
    },
)
def create_animation(concept: str, scenes: int = 3, caption: str = "",
                     aspect: str = "9:16", style: str = "",
                     seconds_each: float = 2.5) -> str:
    from reyes_agent.creative import animate
    from reyes_agent.creative.rights import registry

    concept = str(concept or "").strip()
    if not concept:
        return "What should the animation be about?"
    scenes = max(2, min(int(scenes or 3), 6))

    style_suffix = f", {style.strip()} style" if str(style or "").strip() else ", cinematic"
    prompts = [f"{concept}{style_suffix}, scene {i + 1} of {scenes}, high detail"
               for i in range(scenes)]

    frames: list[str] = []
    for i, prompt in enumerate(prompts):
        path = _generate_frame(prompt, i)
        if path is None:
            if frames:
                break  # animate what we got
            return ("Couldn't generate any frames -- the image service didn't "
                    "respond. Try again in a moment.")
        # ZENO drew these, so they are owner-created and the rights layer clears
        # them for publication. That is a true provenance claim, not a bypass.
        registry.declare(path, registry.OWNER_CREATED, owner="ZENO",
                         source="ZENO image generation", social=True, commercial=True)
        frames.append(path)

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    output = _OUT_DIR / f"animation-{int(time.time())}.mp4"
    result = animate.animate_images(frames, output, caption=caption,
                                    seconds_each=float(seconds_each or 2.5),
                                    aspect=aspect, commercial=True)
    if not result.ok:
        return f"Drew {len(frames)} frames but couldn't render the animation: {result.reason}"
    return (f"Made an animation from {len(frames)} original frames: {result.path}\n"
            f"{result.reason}. It's ready -- ask me to post it and it'll go through "
            "the social approval gate first.")


@register(
    name="animate_files",
    description=(
        "Animate images the owner ALREADY has into a video with motion and "
        "crossfades. Use for 'make a reel from these photos'. The images must "
        "be the owner's own or cleared to use; ZENO checks each against the "
        "rights layer and refuses any it cannot clear."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "paths": {"type": "array", "items": {"type": "string"},
                      "description": "Image file paths, in order."},
            "caption": {"type": "string", "description": "Optional on-screen caption."},
            "aspect": {"type": "string", "description": "9:16, 16:9, 1:1, 4:5."},
            "seconds_each": {"type": "number", "description": "Seconds per image. Default 2.5."},
            "i_own_these": {"type": "boolean",
                            "description": "Owner confirms these are theirs/cleared. Declares them owner-created."},
        },
        "required": ["paths"],
    },
)
def animate_files(paths: list, caption: str = "", aspect: str = "9:16",
                  seconds_each: float = 2.5, i_own_these: bool = False) -> str:
    from reyes_agent.creative import animate
    from reyes_agent.creative.rights import registry

    files = [str(p).strip() for p in (paths or []) if str(p).strip()]
    if not files:
        return "Give me the image files to animate."
    missing = [f for f in files if not Path(f).exists()]
    if missing:
        return f"These files don't exist: {', '.join(missing[:3])}"

    if i_own_these:
        for f in files:
            registry.declare(f, registry.OWNER_CREATED, owner="owner",
                             source="owner-supplied", social=True)

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    output = _OUT_DIR / f"animation-{int(time.time())}.mp4"
    result = animate.animate_images(files, output, caption=caption,
                                    seconds_each=float(seconds_each or 2.5),
                                    aspect=aspect)
    if not result.ok:
        if result.refused:
            return (f"I won't animate images I can't clear the rights for: "
                    f"{', '.join(Path(p).name for p in result.refused)}. If they're "
                    "yours, say so and I'll record that.")
        return f"Couldn't render: {result.reason}"
    return f"Animated {len(files)} images into {result.path} ({result.reason})."
