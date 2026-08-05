"""Conservative resource allocation and idle-resource recovery."""

from __future__ import annotations

import sys
from typing import Any


def sweep() -> dict[str, Any]:
    """Release only resources whose ownership/lifecycle is unambiguous."""
    slept = 0
    browser_closed = False
    if "reyes_agent.agent_runtime" in sys.modules:
        try:
            from reyes_agent import agent_runtime

            slept = agent_runtime.sleep_idle_agents()
        except Exception:  # noqa: BLE001
            pass
    if "reyes_agent.browser_controller" in sys.modules:
        try:
            from reyes_agent.browser_runtime import get_browser_runtime

            # Synchronous Playwright contexts are owner-thread affine; idle
            # cleanup therefore goes through the same dedicated runtime.
            browser_closed = get_browser_runtime().close_if_idle()
        except Exception:  # noqa: BLE001
            pass
    return {"agents_slept": slept, "browser_closed": browser_closed}


def start_background() -> None:
    from reyes_agent.scheduler import get_scheduler
    from reyes_agent.worker_pool import PRIORITY_MAINTENANCE

    get_scheduler().schedule(
        "resource-sweep", sweep, delay=120.0, interval=120.0,
        priority=PRIORITY_MAINTENANCE, timeout=15,
    )
