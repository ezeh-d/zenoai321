"""What ZENO can actually do, and how it learns to do more.

    inventory   is it present? (cached; the expensive probes happen once)
    registry    is it present AND configured AND permitted AND healthy?
    graph       what does this goal require, and what exactly is missing?
    engine      the honest answer, and the plan when the answer is no

The rule the whole package exists to enforce: never say "I don't support
that". Say which of the three it is -- I have a skill, I understand it but
lack a named thing, or I don't know yet and can find out.
"""

from __future__ import annotations

from reyes_agent.capabilities import inventory          # no intra-package deps
from reyes_agent.capabilities import registry           # needs inventory
from reyes_agent.capabilities import graph              # needs registry
from reyes_agent.capabilities import engine             # needs all of the above
from reyes_agent.capabilities.engine import (CAN_DO, HAVE_SKILL, UNDERSTOOD,
                                             UNKNOWN, Verdict)

__all__ = ["inventory", "registry", "graph", "engine", "Verdict",
           "HAVE_SKILL", "CAN_DO", "UNDERSTOOD", "UNKNOWN",
           "can_i", "plan", "what_can_you_do", "status"]

can_i = engine.can_i
plan = engine.plan
what_can_you_do = engine.what_can_you_do
status = engine.status
