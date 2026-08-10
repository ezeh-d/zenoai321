"""ZENO's web autonomy.

Two strategies, chosen by `router.choose`:

  DETERMINISTIC -- Playwright through the EXISTING `browser_controller` /
                   `browser_runtime`, which already own a bounded,
                   owner-visible session. Milliseconds, cannot hallucinate.
  AGENTIC       -- browser-use for pages ZENO has no map of. Off by default
                   (`ZENO_BROWSER_AGENT_ENABLED`); falls back to Playwright
                   driven by ZENO's own vision/grounding loop.

Bulk submission is refused outright rather than gated: mass-applying or
mass-messaging violates platform terms and can get the owner's accounts
banned. One at a time, and the final submit stays his.
"""

from __future__ import annotations

from reyes_agent.browser import router, verification
from reyes_agent.browser import session_manager

__all__ = ["router", "verification", "session_manager", "choose", "status"]

choose = router.choose


def status() -> dict:
    return {"strategies": router.available(),
            "sessions": session_manager.status()}
