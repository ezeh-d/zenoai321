"""AVA's security-testing engine: scope, toolkit, engagement, real targets.

AVA is ZENO's offensive AND defensive security specialist. She operates only
on targets the owner has personally authorized (`authorization`), plans across
the full kill chain from a comprehensive toolkit (`catalog`), refuses the
techniques that cause indiscriminate harm regardless of scope (`engagement`),
loads real authorized targets from bug-bounty scope and publicly-sanctioned
hosts (`bounty`), and stands up real vulnerable servers on localhost (`lab`).
"""

from reyes_agent.security.testing import (  # noqa: F401
    authorization,
    bounty,
    catalog,
    engagement,
    lab,
)

__all__ = ["authorization", "catalog", "engagement", "bounty", "lab"]
