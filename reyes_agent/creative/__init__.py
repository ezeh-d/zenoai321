"""ZENO's creative production surface.

    rights        who owns it and what may be done with it -- checked first
    verification  a render is done when the file plays, not when a command exits

Rights come first here on purpose. Everything else in a creative studio
makes things faster; the rights engine is what decides whether the studio
is a production tool or a reposting machine.
"""

from __future__ import annotations

from reyes_agent.creative import rights
from reyes_agent.creative import verification
from reyes_agent.creative import blender
from reyes_agent.creative import design
from reyes_agent.creative import web3d
from reyes_agent.creative import video

__all__ = ["rights", "verification", "web3d", "video", "blender", "design",
           "verify_render", "verify_site", "status"]

verify_render = verification.verify_render
verify_site = verification.verify_site


def status() -> dict:
    return {"state": "ONLINE", "rights": rights.status(),
            "verification": verification.status(),
            "web3d": web3d.status(), "video": video.status(),
            "blender": blender.status(), "design": design.status()}
