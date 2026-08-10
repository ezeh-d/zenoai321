"""Which technique a computer task should go through.

`ladder` answers that and nothing else -- `controller.py` remains the only
thing that acts. Rungs 1-5 (native API, UIA, DOM, approved skills,
accessibility actions) need no optional dependency and handle real work on
this machine today. Rungs 6-8 (CUA/UFO, Agent TARS, vision grounding) are
OPTIONAL_PLUGIN, off by default, and say so when absent.
"""

from __future__ import annotations

from reyes_agent.computer.agent_backends import ladder
from reyes_agent.computer.agent_backends.ladder import (ACCESSIBILITY, COORDINATES,
                                                        CUA, DOM, LADDER, NATIVE,
                                                        TARS, UIA, VISION, WORKFLOW,
                                                        Choice, choose, describe)

__all__ = ["ladder", "Choice", "choose", "describe", "status", "LADDER",
           "NATIVE", "UIA", "DOM", "WORKFLOW", "ACCESSIBILITY", "CUA", "TARS",
           "VISION", "COORDINATES"]

status = ladder.status
