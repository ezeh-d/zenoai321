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

__all__ = ["rights", "verification", "verify_render", "verify_site", "status"]

verify_render = verification.verify_render
verify_site = verification.verify_site


def status() -> dict:
    return {"state": "ONLINE", "rights": rights.status(),
            "verification": verification.status()}
