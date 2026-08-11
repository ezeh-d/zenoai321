"""The honest answer to "can you do this?" -- and the plan when the answer is no.

THE THREE ANSWERS, AND WHY THERE ARE EXACTLY THREE
--------------------------------------------------
The brief is precise about this, and it is the whole point of the module:

    HAVE_SKILL   "Yes -- I have a skill for that you have approved."
    UNDERSTOOD   "I understand it, but I don't have what it needs: <named
                  thing>." Actionable, because the missing piece is named.
    UNKNOWN      "I don't know enough yet. I can research it and tell you
                  what it would take."

A fourth answer -- "I don't support that" -- is banned, because it hides
which of the three is true.

WHAT THIS DOES NOT DO
---------------------
It does not acquire capabilities by itself. `plan()` produces the steps that
WOULD close a gap, and every one of them that installs software, connects an
account or spends money is marked as needing the owner. An engine that can
silently grant itself new reach is the thing `skills/constitution.py` exists
to prevent, and this does not get an exception.

Nothing here fabricates. If a mailbox is not connected, ZENO says so; it
does not invent an inbox to demonstrate with.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from reyes_agent.capabilities import graph, inventory, registry

HAVE_SKILL = "HAVE_SKILL"
CAN_DO = "CAN_DO"
UNDERSTOOD = "UNDERSTOOD"
UNKNOWN = "UNKNOWN"

# Steps that must never happen without the owner saying yes.
NEEDS_OWNER = frozenset({"install", "connect_account", "purchase", "grant_permission"})


@dataclass
class Step:
    action: str
    detail: str
    needs_owner: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"action": self.action, "detail": self.detail,
                "needs_owner": self.needs_owner}


@dataclass
class Verdict:
    answer: str
    request: str
    say: str = ""
    skill: str = ""
    assessment: graph.Assessment | None = None
    steps: list[Step] = field(default_factory=list)
    at: float = field(default_factory=time.time)

    @property
    def executable(self) -> bool:
        return self.answer in (HAVE_SKILL, CAN_DO)

    def as_dict(self) -> dict[str, Any]:
        return {"answer": self.answer, "request": self.request, "say": self.say,
                "skill": self.skill or None, "executable": self.executable,
                "steps": [s.as_dict() for s in self.steps],
                "assessment": self.assessment.as_dict() if self.assessment else None}


def _approved_skill(request: str):
    try:
        from reyes_agent import skills

        return skills.manager.find_for(request)
    except Exception:  # noqa: BLE001
        return None


def can_i(request: str) -> Verdict:
    """The honest answer. Never bluffs, never fakes, always specific."""
    text = str(request or "").strip()
    if not text:
        return Verdict(UNKNOWN, text, say="Ask me for something and I will tell you "
                                          "whether I can do it.")

    # 1. An approved skill is the strongest possible yes: the owner has
    #    already agreed to this exact sequence.
    skill = _approved_skill(text)
    if skill is not None:
        return Verdict(HAVE_SKILL, text, skill=skill.name,
                       say=(f"Yes. I have a skill for that -- '{skill.name}', which you "
                            f"approved, and it has worked "
                            f"{skill.history.successes} of {skill.history.runs} times."))

    # 2. Do I have what this needs?
    assessment = graph.assess(text)

    if not assessment.matched:
        return Verdict(UNKNOWN, text, assessment=assessment,
                       say=("I don't know enough about that yet. I can research what it "
                            "involves and tell you what it would take -- I would rather "
                            "do that than guess."),
                       steps=[Step("research", f"find out what '{text}' actually requires"),
                              Step("assess", "check that against what this machine has"),
                              Step("report", "tell you what is missing before doing anything")])

    if assessment.can_do:
        missing = [g.capability for g in assessment.gaps if g.optional]
        note = (f" I'd do it without {', '.join(missing)}, which would make it less "
                "thorough." if missing else "")
        return Verdict(CAN_DO, text, assessment=assessment,
                       say=(f"Yes. I have what that needs: "
                            f"{', '.join(assessment.have) or 'no extra tools'}.{note}"))

    # 3. Understood, but blocked -- and the blocker is named.
    blocking = assessment.blocking
    reasons = "; ".join(f"{g.capability} ({g.state.lower().replace('_', ' ')})"
                        for g in blocking)
    hints = [g.hint for g in blocking if g.hint]
    return Verdict(UNDERSTOOD, text, assessment=assessment,
                   say=(f"I understand what that means, but I can't do it yet: {reasons}."
                        + (" " + " ".join(hints) if hints else "")),
                   steps=_steps_for(blocking))


def _steps_for(gaps: list[graph.Gap]) -> list[Step]:
    """What would close each gap, and who has to do it."""
    steps: list[Step] = []
    for gap in gaps:
        if gap.state == registry.AUTH_REQUIRED:
            steps.append(Step("connect_account",
                              f"{gap.capability}: {gap.why}", needs_owner=True))
        elif gap.state == registry.DEPENDENCY_MISSING:
            steps.append(Step("install",
                              gap.hint or f"install what {gap.capability} needs",
                              needs_owner=True))
        elif gap.state == registry.STANDBY:
            steps.append(Step("configure", f"{gap.capability}: {gap.why}",
                              needs_owner=True))
        else:
            steps.append(Step("diagnose", f"{gap.capability} is {gap.state}: {gap.why}"))
    return steps


def what_can_you_do(category: str = "") -> dict[str, Any]:
    """Answered from the registry, not from a hardcoded list."""
    described = registry.describe(category)
    reachable = graph.status()
    return {
        "summary": described["summary"],
        "can_do_now": reachable["reachable_now"],
        "blocked": reachable["blocked"],
        "capabilities": described["categories"],
        "note": ("This is read from what is actually installed and configured on "
                 "this machine right now, not from a list someone wrote."),
    }


def plan(request: str) -> dict[str, Any]:
    """The verdict plus what it would take -- without doing any of it."""
    verdict = can_i(request)
    return {
        **verdict.as_dict(),
        "owner_actions": [s.as_dict() for s in verdict.steps if s.needs_owner],
        "zeno_actions": [s.as_dict() for s in verdict.steps if not s.needs_owner],
        "note": ("Nothing here has been done. Installing software, connecting an "
                 "account or spending money is yours to approve."),
    }


def record_use(capability_name: str, ok: bool) -> None:
    capability = registry.get(capability_name)
    if capability is not None:
        capability.record(ok)


def status() -> dict[str, Any]:
    return {
        "state": "ONLINE",
        "answers": [HAVE_SKILL, CAN_DO, UNDERSTOOD, UNKNOWN],
        "capabilities": registry.status(),
        "goals": graph.status(),
        "inventory": inventory.stats(),
        "never": ("'I don't support that' -- it hides whether the problem is "
                  "understanding, a missing tool, or a missing permission."),
    }
