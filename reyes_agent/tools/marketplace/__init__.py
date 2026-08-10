"""Safe discovery of MCP servers.

Finding a server tells ZENO it exists and nothing else. A server reaches
ENABLED only through APPROVED, and APPROVED requires a person. What a
server ASKS for and what it RECEIVES are separate fields, so an unknown
server never gets automatic full-system access.
"""

from __future__ import annotations

from reyes_agent.tools.marketplace import trust               # no intra-package deps
from reyes_agent.tools.marketplace import registry            # needs trust
from reyes_agent.tools.marketplace.trust import (APPROVED, BLOCKED, DISABLED,
                                                 DISCOVERED, ENABLED, INSTALLED,
                                                 REVIEWED, STATES, UNTRUSTED,
                                                 Manifest, Review)

__all__ = ["trust", "registry", "Manifest", "Review", "STATES",
           "DISCOVERED", "UNTRUSTED", "REVIEWED", "APPROVED", "INSTALLED",
           "ENABLED", "DISABLED", "BLOCKED",
           "record", "screen", "move", "may_call", "status"]

record = registry.record
screen = registry.screen
move = registry.move
may_call = registry.may_call
status = registry.status
