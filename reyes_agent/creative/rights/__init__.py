"""Who owns a piece of media, and what may be done with it.

An asset nobody classified is UNKNOWN_RIGHTS and cannot be published. A
refusal always carries the rights-compliant alternative, because blocking
someone's project without telling them how to get what they wanted is not
safety, it is an obstacle.
"""

from __future__ import annotations

from reyes_agent.creative.rights import registry          # no intra-package deps
from reyes_agent.creative.rights import validator         # needs registry
from reyes_agent.creative.rights.registry import (CLASSIFICATIONS, OWNER_CREATED,
                                                  PUBLIC_DOMAIN, THIRD_PARTY_COPYRIGHTED,
                                                  UNKNOWN_RIGHTS, USER_LICENSED, Asset)

__all__ = ["registry", "validator", "Asset", "CLASSIFICATIONS",
           "OWNER_CREATED", "USER_LICENSED", "PUBLIC_DOMAIN",
           "UNKNOWN_RIGHTS", "THIRD_PARTY_COPYRIGHTED",
           "declare", "check", "check_all", "status"]

declare = registry.declare
check = validator.check
check_all = validator.check_all


def status() -> dict:
    return {"state": "ONLINE", "registry": registry.status(),
            "validator": validator.status()}
