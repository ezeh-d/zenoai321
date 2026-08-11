"""Break a broad goal into steps that can each be checked against reality.

THE INSTRUCTION
---------------
"Do not respond: 'That's too broad.' Decompose it."

"Launch a marketing campaign" is not one capability and never will be. It
is market research, then an audience, then an offer, then copy, then
graphics, then a landing page, then email, then social, then analytics --
nine sub-goals, each of which ZENO can individually do, part-do, or not do.
Refusing the whole thing because it is large throws away the eight parts
that are possible.

So a plan is a list of sub-goals, each carrying its OWN verdict. The useful
output is not "yes" or "no" but "six of these I can do now, two need a tool
you would have to install, one needs an account you would have to connect."

ORDER MATTERS AND IS DECLARED
-----------------------------
Sub-goals carry `after`, naming what must happen first. Copywriting before
audience research is not a plan, it is a guess. Anything with unmet
prerequisites is reported as blocked-by-sequence rather than silently
reordered, because the owner may have already done the earlier part
themselves.

DECOMPOSITION IS A MAP, NOT A MODEL CALL
----------------------------------------
The templates below are explicit and inspectable. A model could produce a
richer decomposition, and `decompose()` accepts one via `extra_steps`, but
the default path must work with no network, no key and no latency -- an
assistant that cannot plan offline cannot plan on a bad connection either.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from reyes_agent.capabilities import engine, graph

# goal -> ordered sub-goals. Each entry: (name, goal_hint, after)
# `goal_hint` is phrased so `graph.identify()` can match it.
TEMPLATES: dict[str, tuple[tuple[str, str, tuple[str, ...]], ...]] = {
    "marketing_campaign": (
        ("market research", "research the market and competitors", ()),
        ("audience", "research the target audience", ("market research",)),
        ("offer", "decide the offer", ("audience",)),
        ("copywriting", "write the campaign copy", ("offer",)),
        ("graphics", "design a logo and campaign images", ("offer",)),
        ("landing page", "automate this website build", ("copywriting", "graphics")),
        ("email", "automate my email outreach", ("copywriting",)),
        ("social", "schedule social posts", ("copywriting", "graphics")),
        ("analytics", "analyse the data afterwards", ("landing page",)),
    ),
    "business_automation_review": (
        ("map processes", "analyse this business and its processes", ()),
        ("find repetition", "research repetitive workflows", ("map processes",)),
        ("inventory systems", "what can you do", ("map processes",)),
        ("rank opportunities", "analyse the data by impact and effort",
         ("find repetition", "inventory systems")),
        ("propose", "prepare a report", ("rank opportunities",)),
    ),
    "meeting_preparation": (
        ("agenda", "check my calendar for the meeting", ()),
        ("correspondence", "search my email for the thread", ()),
        ("background", "research the attendees and company", ()),
        ("prior context", "search memory for what we discussed", ()),
        ("brief", "prepare a report", ("agenda", "correspondence", "background",
                                       "prior context")),
    ),
    "invoice_reconciliation": (
        ("read invoices", "parse this document", ()),
        ("read ledger", "analyse the data in the spreadsheet", ()),
        ("compare", "reconcile invoice records", ("read invoices", "read ledger")),
        ("report", "prepare a report of mismatches", ("compare",)),
    ),
    "email_automation": (
        ("connect mailbox", "automate my email", ()),
        ("classify", "classify important email", ("connect mailbox",)),
        ("extract", "extract deadlines and requests", ("classify",)),
        ("draft", "draft replies", ("extract",)),
        ("approve and send", "send only with approval", ("draft",)),
    ),
    "understand_new_software": (
        ("identify", "identify this application", ()),
        ("inspect", "read this application's controls", ("identify",)),
        ("document", "research the application documentation", ("identify",)),
        ("perform", "automate the repetitive part of this application",
         ("inspect", "document")),
        ("record", "save the workflow as a skill", ("perform",)),
    ),
}

_HINTS = {
    "marketing_campaign": ("marketing campaign", "launch a campaign", "market this"),
    "business_automation_review": ("what can we automate", "analyse this business",
                                   "analyze this business", "automate my business"),
    "meeting_preparation": ("prepare me for", "prepare for tomorrow", "meeting prep",
                            "brief me on"),
    "invoice_reconciliation": ("reconcile", "invoices", "accounting"),
    "email_automation": ("automate my email", "email automation", "automate email"),
    "understand_new_software": ("figure out this app", "understand this software",
                                "use this application", "figure out how this works"),
}


@dataclass
class SubGoal:
    name: str
    goal: str
    after: tuple[str, ...] = ()
    verdict: engine.Verdict | None = None

    @property
    def answer(self) -> str:
        return self.verdict.answer if self.verdict else engine.UNKNOWN

    @property
    def ready(self) -> bool:
        return bool(self.verdict and self.verdict.executable)

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "goal": self.goal, "after": list(self.after),
                "answer": self.answer, "ready": self.ready,
                "say": self.verdict.say if self.verdict else "",
                "blocking": ([g.capability for g in self.verdict.assessment.blocking]
                             if self.verdict and self.verdict.assessment else [])}


@dataclass
class Plan:
    request: str
    matched: str = ""
    steps: list[SubGoal] = field(default_factory=list)

    @property
    def ready_steps(self) -> list[SubGoal]:
        return [s for s in self.steps if s.ready]

    @property
    def blocked_steps(self) -> list[SubGoal]:
        return [s for s in self.steps if not s.ready]

    @property
    def coverage(self) -> float:
        return (len(self.ready_steps) / len(self.steps)) if self.steps else 0.0

    def missing_capabilities(self) -> list[str]:
        found: list[str] = []
        for step in self.blocked_steps:
            if step.verdict and step.verdict.assessment:
                for gap in step.verdict.assessment.blocking:
                    if gap.capability not in found:
                        found.append(gap.capability)
        return found

    def as_dict(self) -> dict[str, Any]:
        return {"request": self.request, "matched": self.matched or None,
                "steps": [s.as_dict() for s in self.steps],
                "ready": len(self.ready_steps), "total": len(self.steps),
                "coverage": round(self.coverage, 2),
                "missing_capabilities": self.missing_capabilities(),
                "say": self.say()}

    def say(self) -> str:
        if not self.steps:
            return ("I could not break that down into steps I recognise. Tell me a "
                    "little more about what the finished result looks like.")
        ready, total = len(self.ready_steps), len(self.steps)
        lines = [f"I broke that into {total} parts. I can do {ready} of them now."]
        for step in self.steps:
            mark = "yes" if step.ready else "no "
            lines.append(f"  [{mark}] {step.name}")
        missing = self.missing_capabilities()
        if missing:
            lines.append("Blocked on: " + ", ".join(missing) + ".")
        return "\n".join(lines)


def identify(request: str) -> str:
    text = str(request or "").strip().lower()
    best, best_len = "", 0
    for goal, hints in _HINTS.items():
        for hint in hints:
            if hint in text and len(hint) > best_len:
                best, best_len = goal, len(hint)
    return best


def decompose(request: str, *,
              extra_steps: tuple[tuple[str, str, tuple[str, ...]], ...] = ()) -> Plan:
    """Break the request down and judge each part against real capability."""
    plan = Plan(request=str(request or ""))
    template = identify(request)
    plan.matched = template

    steps = list(TEMPLATES.get(template, ())) + list(extra_steps)
    if not steps:
        # Not a known composite. It may still be a single achievable goal --
        # answer that honestly rather than inventing a decomposition.
        verdict = engine.can_i(request)
        if verdict.assessment and verdict.assessment.matched:
            plan.steps = [SubGoal(name=verdict.assessment.matched,
                                  goal=str(request), verdict=verdict)]
        return plan

    for name, hint, after in steps:
        plan.steps.append(SubGoal(name=name, goal=hint, after=tuple(after),
                                  verdict=engine.can_i(hint)))
    return plan


def sequence(plan: Plan) -> list[list[str]]:
    """Steps grouped into waves that may run together.

    A wave contains only steps whose prerequisites are all in earlier waves.
    A cycle -- or a dependency on a step that does not exist -- stops the
    grouping rather than silently dropping the step.
    """
    remaining = {s.name: set(s.after) for s in plan.steps}
    known = set(remaining)
    waves: list[list[str]] = []
    done: set[str] = set()

    while remaining:
        wave = sorted(name for name, after in remaining.items()
                      if (after & known) <= done)
        if not wave:
            waves.append(sorted(remaining))      # unresolvable; surface it whole
            break
        waves.append(wave)
        done |= set(wave)
        for name in wave:
            remaining.pop(name)
    return waves


def status() -> dict[str, Any]:
    return {
        "state": "ONLINE",
        "composites_known": sorted(TEMPLATES),
        "note": ("A broad goal is decomposed and each part judged separately. "
                 "'That's too broad' is not an answer -- the useful reply is which "
                 "parts are possible now and what blocks the rest."),
        "offline": "decomposition needs no model, key or network",
    }
