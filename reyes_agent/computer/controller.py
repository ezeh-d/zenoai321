"""The one entry point for computer control -- and the fast/agentic split.

    request -> deterministic match?  -> FAST PATH   (existing gated tools)
                     no match        -> AGENTIC PATH (observe/ground/act/verify)

The split exists because perception is expensive and usually unnecessary.
"Open Chrome" is a solved problem: `open_app` does it in milliseconds with
no screenshot, no parse and no model call. Reserving the agentic loop for
things that genuinely need eyes is what keeps ZENO fast.

Nothing here bypasses existing safety. The fast path calls `run_tool`, so
the permission engine and confirmation gate apply unchanged; the agentic
path adds its own gate on top because a grounded click is a new kind of
reach that the tool registry never had to reason about.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from reyes_agent.computer import agentic, deterministic, input_guard, safety

FAST, AGENTIC = "FAST", "AGENTIC"


@dataclass
class Result:
    ok: bool
    path: str
    summary: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    needs_approval: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "path": self.path, "summary": self.summary,
                "needs_approval": self.needs_approval, "detail": self.detail}


def classify(request: str) -> str:
    """Which path a request belongs on."""
    return FAST if deterministic.match(request) else AGENTIC


def observe() -> str:
    """What is on screen right now, as text a model can reason about."""
    from reyes_agent import vision

    return vision.observe().summary()


def run(request: str, plan: list[dict] | None = None, *, approved: bool = False,
        cancel_check: Callable[[], None] | None = None) -> Result:
    """Do the thing.

    With no `plan`, only the fast path can run -- ZENO must supply grounded
    steps for anything agentic, because this module deliberately does not
    call a model itself. Keeping the planner out of the executor is what
    stops a runaway loop from planning its own next move forever.
    """
    started = time.time()

    fast = deterministic.run(request)
    if fast.handled:
        return Result(fast.ok, FAST, fast.result[:400] or fast.reason or f"ran {fast.tool}",
                      {"tool": fast.tool, "duration_ms": int((time.time() - started) * 1000),
                       "executed": fast.ok})

    if not plan:
        return Result(False, AGENTIC,
                      "This needs the agentic path: give me the grounded steps "
                      "(observe the screen first, then a list of {action, target}).",
                      {"reason": fast.reason,
                       "screen": observe()[:1200]})

    outcome = agentic.run(request, plan, approved=approved, cancel_check=cancel_check)
    return Result(outcome.ok, AGENTIC, outcome.summary(),
                  {**outcome.as_dict(), "duration_ms": int((time.time() - started) * 1000)},
                  needs_approval=outcome.needs_approval)


def status() -> dict[str, Any]:
    from reyes_agent import integrations, vision

    return {
        "paths": [FAST, AGENTIC],
        "vision": vision.scene_state.stats(),
        "cua_enabled": integrations.CUA_ENABLED,
        "cua_installed": integrations.available("agent"),
        "limits": {"max_steps": agentic.MAX_STEPS, "deadline_s": agentic.DEADLINE_S,
                   "max_no_change": agentic.MAX_NO_CHANGE},
        "risk_tiers": list(safety.TIERS),
        "input_guard": input_guard.status(),
        "note": ("Deterministic commands never touch the screen. Agentic steps are "
                 "grounded against real elements -- coordinates are never invented -- "
                 "and payments, credential changes and security settings are refused "
                 "outright rather than gated. ZENO will not take the pointer while "
                 "you are actively using it, and always puts it back."),
    }
