"""How much machinery a request deserves.

    DIRECT      -- ZENO answers. No tool, no agent.
    TOOL        -- one tool call.
    SPECIALIST  -- one delegated agent.
    TEAM        -- a few agents in parallel.
    COUNCIL     -- explicitly asked for, or genuinely needs many views.

The point is restraint. "Ultra-smart" must not mean waking thirteen agents
to answer "what is Node.js" -- that is slower, costs more, and produces a
worse answer than replying directly.

This does NOT re-decide fast/deep: `cognition.route` already did that with
real signals, in microseconds. This maps that decision onto the delegation
shape, so there is one router, not two disagreeing ones.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DIRECT, TOOL, SPECIALIST, TEAM, COUNCIL = "DIRECT", "TOOL", "SPECIALIST", "TEAM", "COUNCIL"
SHAPES = (DIRECT, TOOL, SPECIALIST, TEAM, COUNCIL)


@dataclass(frozen=True)
class Delegation:
    shape: str
    reason: str
    max_agents: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"shape": self.shape, "reason": self.reason, "max_agents": self.max_agents}


def decide(message: str, decision=None) -> Delegation:
    """Map an already-routed turn onto a delegation shape."""
    from reyes_agent import cognition

    if decision is None:
        decision = cognition.route(message)

    modes = set(decision.modes)

    if cognition.COUNCIL in modes:
        return Delegation(COUNCIL, "the council was explicitly asked for", max_agents=13)

    if decision.path == cognition.FAST:
        if cognition.ACTION in modes:
            return Delegation(TOOL, "a fast, concrete action -- one tool, no delegation")
        return Delegation(DIRECT, "ordinary conversation; delegation would only add latency")

    # DEEP from here. Specialists are allowed, but count is earned.
    if not decision.allow_specialists:
        return Delegation(DIRECT, "deep reasoning ZENO should do itself")

    if cognition.SPECIALIST in modes:
        # Genuinely cross-domain work is the only thing that earns a team.
        cross_domain = len(modes & {cognition.RESEARCH, cognition.ACTION,
                                    cognition.ADVICE, cognition.MEMORY}) >= 2
        if cross_domain and decision.complexity >= 0.6:
            return Delegation(TEAM, f"spans several domains ({', '.join(sorted(modes))}) "
                                    f"at complexity {decision.complexity:.2f}", max_agents=3)
        return Delegation(SPECIALIST, "one domain needs real depth", max_agents=1)

    if cognition.ACTION in modes:
        return Delegation(TOOL, "deep, but the work is a tool call")
    return Delegation(DIRECT, "deep reasoning, no specialist domain identified")


def directive(delegation: Delegation) -> str:
    """A short per-turn nudge, or nothing for the common case."""
    if delegation.shape == DIRECT:
        return ""
    if delegation.shape == TOOL:
        return "[Delegation: one tool call. Do not convene specialists for this.]"
    if delegation.shape == SPECIALIST:
        return ("[Delegation: delegate to ONE specialist for depth, then answer in your "
                "own voice. Do not fan out.]")
    if delegation.shape == TEAM:
        return (f"[Delegation: up to {delegation.max_agents} specialists IN PARALLEL "
                "(fire the delegate calls in the same turn), then combine into one reply.]")
    return "[Delegation: Council Mode was requested. Convene it.]"
