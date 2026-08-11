"""Which engine a piece of work belongs on.

    SIMPLE TASK                  -> direct tool call
    REUSABLE MULTI-STEP TASK     -> a ZENO skill
    LONG INTEGRATION AUTOMATION  -> n8n / Activepieces, where they earn it
    DURABLE MULTI-DAY MISSION    -> the mission store

THE INSTRUCTION THAT MATTERS MOST
---------------------------------
"Do not replace simple direct tool calls with huge workflows unnecessarily."

Workflow engines are seductive because their diagrams look like
architecture. But routing "what's the time" through n8n adds a service, a
webhook, a queue and a failure mode to something that was a function call.
Every rung below the one you need costs latency, a dependency and a place
for the work to get stuck.

So the ladder is ordered by COST, like the computer backend ladder, and
`decide()` returns the cheapest rung that can actually carry the work.

WHEN A WORKFLOW ENGINE GENUINELY EARNS ITS PLACE
------------------------------------------------
One property, and it is not "multi-step": an EXTERNAL TRIGGER ZENO cannot
observe. "When a new email arrives, create a CRM lead and notify Slack" has
to keep running when ZENO is closed, on a machine that is awake, listening
to a provider webhook. That is what n8n and Activepieces are for.

Multi-step work that ZENO itself starts is a skill. Multi-day work that must
survive a restart is a mission. Neither needs a second runtime.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

DIRECT = "direct_tool"
SKILL = "zeno_skill"
WORKFLOW_ENGINE = "workflow_engine"
MISSION = "mission"

LADDER = (DIRECT, SKILL, WORKFLOW_ENGINE, MISSION)

_DESCRIPTIONS = {
    DIRECT: "one tool call -- no orchestration, nothing to get stuck",
    SKILL: "a reusable sequence ZENO runs itself, approved once",
    WORKFLOW_ENGINE: "an external trigger firing while ZENO is closed",
    MISSION: "work spanning days that must survive a restart",
}

# An external system starts this, not the owner and not ZENO.
_EXTERNAL_TRIGGER = re.compile(
    r"\b(when|whenever|every time|as soon as)\b.{0,40}"
    r"\b(arrives?|comes? in|is (created|added|received|submitted)|new (email|lead|"
    r"issue|message|row|file|order)|webhook|incoming)\b", re.I)

# Explicitly scheduled but short -- the existing scheduler, not a workflow engine.
_SCHEDULED = re.compile(r"\b(every (morning|day|week|hour)|at \d{1,2}(:\d{2})?\s*(am|pm)?|"
                        r"daily|weekly|each morning|remind me)\b", re.I)

# Work measured in days.
_LONG_RUNNING = re.compile(
    r"\b(over the next (few )?(days?|weeks?)|for the next \w+ days?|"
    r"across (several|multiple) days?|keep (working|going) (on|until)|"
    r"until (it|they|we) (finish|complete)|long[- ]running)\b", re.I)

# More than one distinct action in one request.
_MULTI_STEP = re.compile(r"\b(then|after that|and then|followed by|next,)\b", re.I)

# Recurrence of the SAME work -- what makes something worth keeping as a skill.
_REUSABLE = re.compile(r"\b(every time i ask|whenever i say|from now on|"
                       r"each time|always do|as usual|the usual)\b", re.I)


@dataclass(frozen=True)
class Route:
    engine: str
    reason: str
    external_trigger: bool = False
    available: bool = True
    fallback: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"engine": self.engine, "reason": self.reason,
                "description": _DESCRIPTIONS.get(self.engine, ""),
                "external_trigger": self.external_trigger,
                "available": self.available, "fallback": self.fallback}


def engine_available() -> tuple[bool, str]:
    """Is an external workflow engine actually reachable."""
    try:
        from reyes_agent.workflow_integrations import n8n

        state = n8n.status()
        ready = str(state.get("state", "")).upper() in {"READY", "ONLINE", "STANDBY"}
        return bool(state.get("enabled")) and ready, str(state.get("state", "unknown"))
    except Exception:  # noqa: BLE001
        return False, "not configured"


def decide(request: str, *, steps: int = 0) -> Route:
    """The cheapest engine that can carry this work."""
    text = str(request or "")

    # The one property that genuinely requires an external engine.
    if _EXTERNAL_TRIGGER.search(text):
        ready, state = engine_available()
        if ready:
            return Route(WORKFLOW_ENGINE,
                         "something outside ZENO starts this, so it has to keep "
                         "running when ZENO is closed", external_trigger=True)
        return Route(WORKFLOW_ENGINE,
                     "this needs to fire while ZENO is closed, which needs a workflow "
                     f"engine -- n8n is {state} here",
                     external_trigger=True, available=False,
                     fallback=("ZENO can do it on a schedule while it is running, "
                               "which covers most of it but not the moment ZENO is off"))

    if _LONG_RUNNING.search(text):
        return Route(MISSION, "this spans days, so it must survive a restart")

    if _SCHEDULED.search(text):
        return Route(SKILL, "recurring but short -- the existing scheduler runs a "
                            "skill, no second runtime needed")

    if _REUSABLE.search(text) or steps >= 3 or _MULTI_STEP.search(text):
        return Route(SKILL, "several steps you will want again -- worth keeping as a "
                            "skill rather than rebuilding each time")

    return Route(DIRECT, "one action; orchestrating it would add failure modes and "
                         "no capability")


def explain() -> dict[str, Any]:
    ready, state = engine_available()
    return {
        "ladder": [{"engine": name, "rung": index + 1,
                    "description": _DESCRIPTIONS[name]}
                   for index, name in enumerate(LADDER)],
        "workflow_engine": {"n8n": state, "ready": ready,
                            "activepieces": "not installed"},
        "rule": ("Ordered by cost. A workflow engine earns its place only when an "
                 "external trigger must fire while ZENO is closed -- multi-step work "
                 "ZENO starts itself is a skill, and multi-day work is a mission."),
    }


status = explain
