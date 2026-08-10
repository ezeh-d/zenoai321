"""ZENO's orchestration seam.

ZENO is the executive; specialists are delegated to, not consulted by
reflex. `registry` reports who exists, `router` decides how much machinery
a request earns, `health` reports the real supervisor's state.

None of these schedule anything themselves -- `agent_teams`,
`agent_runtime` and `worker_pool` already do that, correctly, with
cancellation, timeouts, retries and backpressure. Microsoft Agent Framework
is an adapter seam (`ZENO_AGENT_FRAMEWORK_ENABLED`), off by default: two
schedulers with two views of who is busy is how a task runs twice.
"""

from __future__ import annotations

from reyes_agent.agents import health, registry, router

__all__ = ["health", "registry", "router", "describe", "decide"]

describe = registry.describe
decide = router.decide
