"""Connecting ZENO to external SaaS services, at the narrowest access that works.

    catalog      what could be connected, and what each would cost in reach
    connections  what IS connected, at which tier, checked before every use
    routing      which engine a piece of work belongs on

Composio and its equivalents are the standardised way to reach hundreds of
SaaS APIs. Neither Composio nor Activepieces is installed here, so the
catalogue describes the connections and their scopes without pretending a
broker exists -- and connecting anything remains an act the owner performs.

NAMING
------
Called `connectors`, not `integrations`, because `reyes_agent/integrations.py`
already exists and holds the Phase 1 feature flags. A package of that name
would shadow the module and break every consumer of `OMNIPARSER_ENABLED` --
which is exactly what happened for one commit-less minute, and is the same
collision that broke `voice/stt` twice.
"""

from __future__ import annotations

from reyes_agent.connectors import catalog          # no intra-package deps
from reyes_agent.connectors import connections      # needs catalog
from reyes_agent.connectors import routing          # independent

__all__ = ["catalog", "connections", "routing",
           "begin", "confirm", "revoke", "may", "decide", "status"]

begin = connections.begin
confirm = connections.confirm
revoke = connections.revoke
may = connections.may
decide = routing.decide


def status() -> dict:
    return {"state": "ONLINE",
            "catalog": catalog.status(),
            "connections": connections.status(),
            "routing": routing.status()}
