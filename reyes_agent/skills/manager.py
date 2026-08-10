"""The one door into the skill system.

Everything else in this package is deliberately narrow; this is what the
agent, the dashboard and the tools call. It exists so that the promotion
rules -- the part that actually protects the owner -- live in exactly one
place instead of being re-implemented by each caller.

PROMOTION IS ONE-WAY AND NEVER AUTOMATIC
----------------------------------------
    OBSERVED  --learner-->  LEARNED  --owner says yes-->  APPROVED

`approve()` requires a caller to pass who approved it. There is no code
path from LEARNED to APPROVED that does not go through a human decision,
and `suggest()` exists precisely so ZENO can ask rather than assume.
"""

from __future__ import annotations

import time
from typing import Any

from reyes_agent.skills import constitution, executor, learner, registry
from reyes_agent.skills.models import APPROVED, LEARNED, OBSERVED, RETIRED, Skill, Step


def observe() -> list[dict[str, Any]]:
    """Raw repeated sequences. Statistics only -- none of this can run."""
    return learner.observed_sequences()


def learn() -> list[Skill]:
    """Promote qualifying observations to LEARNED (still not runnable)."""
    return learner.propose()


def suggest(limit: int = 3) -> list[dict[str, Any]]:
    """What ZENO would like to offer the owner, best evidence first.

    Deliberately returns the counts alongside each suggestion. "I noticed
    this four times" is a reason; "I think you'd like this" is not.
    """
    candidates = [s for s in registry.all_skills(LEARNED)]
    candidates.sort(key=lambda s: (-s.observations, -s.confidence))
    return [{
        "skill_id": s.skill_id, "name": s.name, "description": s.description,
        "observations": s.observations, "confidence": round(s.confidence, 3),
        "steps": [step.action for step in s.steps],
        "ask": (f"I have seen this {s.observations} times. Want me to keep it as a "
                "skill? It will not run until you say so."),
    } for s in candidates[:limit]]


def approve(skill_id: str, approved_by: str = "owner") -> tuple[bool, str]:
    """The only route to a runnable skill."""
    skill = registry.get(skill_id)
    if skill is None:
        return False, f"no skill {skill_id}"
    if skill.state == APPROVED:
        return True, f"'{skill.name}' was already approved"
    if skill.state == RETIRED:
        return False, f"'{skill.name}' is retired"

    # Checked again here: a skill can be edited on disk between being
    # proposed and being approved.
    verdict = constitution.review(skill)
    if not verdict.allowed:
        registry.audit("blocked", skill, verdict.reason)
        return False, verdict.reason

    skill.state = APPROVED
    skill.approved_by = str(approved_by or "owner")
    ok, reason = registry.save(skill, event="approved", detail=f"by {skill.approved_by}")
    return ok, (f"'{skill.name}' approved and can now run" if ok else reason)


def reject(skill_id: str, why: str = "") -> tuple[bool, str]:
    skill = registry.get(skill_id)
    if skill is None:
        return False, f"no skill {skill_id}"
    skill.state = RETIRED
    registry.save(skill, event="rejected", detail=why[:200])
    return True, f"'{skill.name}' retired and will not be suggested again"


def run(name_or_id: str, *, cancel_check=None) -> executor.Run:
    skill = registry.get(name_or_id) or registry.by_name(name_or_id)
    if skill is None:
        empty = executor.Run(skill_id="", name=str(name_or_id))
        empty.reason = f"I have no skill called '{name_or_id}'"
        return empty
    return executor.execute(skill, cancel_check=cancel_check)


def author(name: str, steps: list[dict[str, Any]], *, description: str = "",
           approved_by: str = "") -> tuple[bool, str]:
    """A skill the owner wrote directly rather than one ZENO noticed.

    Still passes the constitution -- an authored skill is not exempt, because
    the point of the constitution is what the skill DOES.
    """
    skill = Skill(name=name, description=description, source="authored",
                  steps=[Step.from_dict(s) for s in steps],
                  state=APPROVED if approved_by else LEARNED,
                  approved_by=str(approved_by or ""))
    skill.required_tools = sorted({s.action for s in skill.steps})
    return registry.save(skill, event="authored")


def find_for(request: str) -> Skill | None:
    """An approved skill whose trigger matches -- the 'CHECK EXISTING SKILL'
    step of the autonomous loop."""
    text = str(request or "").strip().lower()
    if not text:
        return None
    for skill in registry.all_skills(APPROVED):
        if skill.name.lower() in text:
            return skill
        for trigger in skill.triggers:
            if trigger and trigger.lower() in text:
                return skill
    return None


def status() -> dict[str, Any]:
    counts = registry.stats()
    return {
        "state": "ONLINE",
        **counts,
        "learner": learner.status(),
        "constitution": constitution.explain(),
        "promotion": "OBSERVED -> LEARNED (automatic) -> APPROVED (owner only)",
    }
