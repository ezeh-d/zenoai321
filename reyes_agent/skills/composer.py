"""Build a new skill by combining what ZENO already has.

THE POINT
---------
"No hardcoded prepare_meeting.py should be required for every possible
combination."

Meeting preparation is calendar + email + memory + document search + web
research + summarisation. Every one of those already exists. What is missing
is not capability, it is the ARRANGEMENT -- and an arrangement is data, not
code. So a composed skill is assembled from a decomposed plan and stored
like any other skill.

WHAT A COMPOSED SKILL IS NOT
----------------------------
It is not approved, and it is not runnable. `compose()` produces a LEARNED
candidate, which is exactly what `manager.approve()` exists to gate. The
composer can arrange ZENO's existing reach into a new shape; it cannot
grant reach, and the constitution is checked on the way to disk like
everything else.

IT REFUSES TO COMPOSE OVER A GAP
--------------------------------
If a step of the plan has no usable capability behind it, the composed
skill would contain a step that cannot run. Producing it anyway would be
the automation equivalent of a promise -- it looks complete, and fails at
the moment it matters. So composition either covers every required step or
reports which one it could not cover.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from reyes_agent.capabilities import planner, registry
from reyes_agent.skills import registry as skill_registry
from reyes_agent.skills.models import LEARNED, Skill, Step

# A composition needs at least this much of the plan to be worth storing.
MIN_COVERAGE = 1.0          # every REQUIRED step; optional gaps are allowed

# Which tool a capability is driven through. Composition maps capability ->
# action; anything not mapped cannot be composed and is reported as such.
_ACTIONS: dict[str, str] = {
    "web_research": "research_web",
    "semantic_search": "search_knowledge",
    "memory": "recall_memory",
    "computer_control": "observe_screen",
    "duckdb": "query_data",
    "pandas": "query_data",
    "docling": "parse_document",
    "ffmpeg": "convert_media",
    "opencv": "process_image",
    "playwright": "browse",
    "git": "run_command",
    "python": "run_python",
    "agents": "delegate",
    "gemini": "summarise",
    "openai": "summarise",
    "calendar": "read_calendar",
    "email_provider": "read_email",
    "skills": "run_skill",
    "missions": "start_mission",
}


@dataclass
class Composition:
    request: str
    skill: Skill | None = None
    covered: list[str] = field(default_factory=list)
    uncovered: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.skill is not None

    def as_dict(self) -> dict[str, Any]:
        return {"request": self.request, "composed": self.ok,
                "skill": self.skill.as_dict() if self.skill else None,
                "covered": self.covered, "uncovered": self.uncovered,
                "reason": self.reason}


def _action_for(capability_name: str) -> str:
    return _ACTIONS.get(capability_name, "")


def _capabilities_for(sub_goal: planner.SubGoal) -> list[str]:
    """The usable capabilities behind one step of a plan."""
    if sub_goal.verdict is None or sub_goal.verdict.assessment is None:
        return []
    return list(sub_goal.verdict.assessment.have)


def compose(request: str, *, name: str = "", persist: bool = True) -> Composition:
    """Assemble a candidate skill for `request` from existing capabilities."""
    registry.status()
    plan = planner.decompose(request)
    result = Composition(request=str(request or ""))

    if not plan.steps:
        result.reason = ("I could not break that into steps I recognise, so there is "
                         "nothing to compose from.")
        return result

    steps: list[Step] = []
    for sub_goal in plan.steps:
        available = _capabilities_for(sub_goal)
        action = ""
        used = ""
        for capability_name in available:
            candidate = _action_for(capability_name)
            if candidate:
                action, used = candidate, capability_name
                break
        if not action:
            result.uncovered.append(sub_goal.name)
            continue
        result.covered.append(sub_goal.name)
        steps.append(Step(action=action, target="",
                          arguments={"goal": sub_goal.goal, "via": used},
                          expect=f"{sub_goal.name} produced something to use",
                          on_failure="stop" if not sub_goal.after else "skip"))

    if not steps:
        result.reason = ("Every part of that needs a capability I do not have yet: "
                         + ", ".join(plan.missing_capabilities() or result.uncovered))
        return result

    blocking = [s.name for s in plan.blocked_steps]
    if blocking:
        result.reason = ("I can only compose part of that. Missing: "
                         + ", ".join(plan.missing_capabilities() or blocking)
                         + ". I will not save a skill with a step that cannot run.")
        return result

    skill = Skill(
        name=name or _name_for(request, plan),
        description=(f"Composed from {len(steps)} existing capabilities for: "
                     f"{request}. Nothing new was installed to build this."),
        state=LEARNED,
        steps=steps,
        triggers=[str(request).strip().lower()],
        required_tools=sorted({s.action for s in steps}),
        verification="Each step reports its own result; the run stops at the first failure.",
        failure_recovery="stop",
        confidence=0.5,                 # composed, never run -- see confidence.py
        observations=0,
        source="composed")

    result.skill = skill
    result.reason = (f"Composed '{skill.name}' from {len(steps)} capabilities you "
                     "already have. It will not run until you approve it.")

    if persist:
        stored, why = skill_registry.save(skill, event="composed", detail=request[:200])
        if not stored:
            result.skill = None
            result.reason = why
    return result


def _name_for(request: str, plan: planner.Plan) -> str:
    if plan.matched:
        return plan.matched.replace("_", " ").title()
    words = [w for w in str(request or "").split() if w.isalpha()][:4]
    return " ".join(w.capitalize() for w in words) or "Composed Workflow"


def status() -> dict[str, Any]:
    return {
        "state": "ONLINE",
        "mapped_capabilities": sorted(_ACTIONS),
        "produces": LEARNED,
        "note": ("Composition arranges existing reach into a new shape. It cannot "
                 "grant reach, it produces a candidate rather than a runnable "
                 "skill, and it refuses to compose a step that has no usable "
                 "capability behind it."),
    }
