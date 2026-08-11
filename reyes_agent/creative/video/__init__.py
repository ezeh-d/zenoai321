"""Video as structure, rendered by ffmpeg and verified afterwards."""

from __future__ import annotations

from reyes_agent.creative.video import timeline          # no intra-package deps
from reyes_agent.creative.video import renderer          # needs timeline
from reyes_agent.creative.video import highlights        # needs verification
from reyes_agent.creative.video import reframe           # needs cv2
from reyes_agent.creative.video.timeline import (ASPECTS, AUDIO, CAPTION, IMAGE,
                                                 TEXT, VIDEO, Clip, Timeline)

__all__ = ["timeline", "renderer", "highlights", "reframe", "Timeline", "Clip", "ASPECTS",
           "VIDEO", "AUDIO", "TEXT", "CAPTION", "IMAGE",
           "render", "build_command", "find_highlights", "plan_reframe", "status"]

render = renderer.render
build_command = renderer.build_command
find_highlights = highlights.find
plan_reframe = reframe.plan


def status() -> dict:
    return {"state": "ONLINE", "timeline": timeline.status(),
            "renderer": renderer.status(),
            "highlights": highlights.status(), "reframe": reframe.status()}
