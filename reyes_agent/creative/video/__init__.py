"""Video as structure, rendered by ffmpeg and verified afterwards."""

from __future__ import annotations

from reyes_agent.creative.video import timeline          # no intra-package deps
from reyes_agent.creative.video import renderer          # needs timeline
from reyes_agent.creative.video.timeline import (ASPECTS, AUDIO, CAPTION, IMAGE,
                                                 TEXT, VIDEO, Clip, Timeline)

__all__ = ["timeline", "renderer", "Timeline", "Clip", "ASPECTS",
           "VIDEO", "AUDIO", "TEXT", "CAPTION", "IMAGE",
           "render", "build_command", "status"]

render = renderer.render
build_command = renderer.build_command


def status() -> dict:
    return {"state": "ONLINE", "timeline": timeline.status(),
            "renderer": renderer.status()}
