"""ZENO's hands.

Two paths, chosen automatically:

  FAST     -- a known deterministic command, routed to the EXISTING gated
              tools (`open_app`, `open_path`, `set_volume`, ...). No
              screenshot, no parse, no model call.
  AGENTIC  -- observe the screen, ground a description to a real element,
              act, then verify what actually changed. Bounded by step count,
              a wall-clock deadline, and a no-progress detector.

`screenshot.py` intentionally re-exports `vision.screen_capture` rather than
holding a second implementation -- one screenshot path, not two.

trycua (`ZENO_CUA_ENABLED`) is an optional adapter. It is off by default
because it runs computer-use agents inside a VM/container, which is the
opposite of driving the owner's own desktop.
"""

from __future__ import annotations

# Dependency order, NOT alphabetical: `agentic` imports safety+verification,
# and `controller` imports agentic+deterministic. Importing alphabetically
# put `agentic` first and it tried to reach back into a package that was
# still half-initialised.
from reyes_agent.computer import safety, verification          # no intra-package deps
from reyes_agent.computer import deterministic, input_guard    # no intra-package deps
from reyes_agent.computer import window                        # no intra-package deps
from reyes_agent.computer import agentic                       # needs the four above
from reyes_agent.computer import controller                    # needs agentic
from reyes_agent.vision import screen_capture as screenshot

__all__ = ["agentic", "controller", "deterministic", "input_guard", "safety",
           "verification", "window", "screenshot", "run", "observe", "status"]

run = controller.run
observe = controller.observe
status = controller.status
