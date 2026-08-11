"""Turn "watch how I do this" into a workflow that still works tomorrow.

THE INSTRUCTION THAT SHAPES EVERYTHING HERE
-------------------------------------------
"Do NOT simply record mouse coordinates."

A recorded click at (412, 306) is worthless the moment the window moves,
the screen resolution changes, a notification shifts the layout, or the app
adds a toolbar row. It looks like learning and is actually a photograph.

So each observed action is generalised to the most durable identifier the
element actually offered, in this order:

    1  automation id   stable across layout, locale and window position
    2  DOM selector    for pages
    3  role + name     "the button called Export" -- survives moving
    4  role + index    "the third tab" -- weak, but still not a pixel
    5  coordinates     recorded ONLY as a last resort, and marked fragile

`generalise()` reports which rung each step landed on, so a demonstration
that produced nothing but coordinates is visibly a bad recording rather
than a working skill.

ONE DEMONSTRATION IS NOT A SKILL
--------------------------------
A single watched run becomes a LEARNED candidate that cannot execute. The
owner approves it, exactly as with every other skill. Watching someone do
something once is evidence of how they did it once.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from reyes_agent.skills import registry as skill_registry
from reyes_agent.skills.models import LEARNED, Skill, Step

# Strength of each identifier, best first. The index is the rung reported.
AUTOMATION_ID = "automation_id"
SELECTOR = "selector"
ROLE_NAME = "role_and_name"
ROLE_INDEX = "role_and_index"
COORDINATES = "coordinates"

STRENGTH = (AUTOMATION_ID, SELECTOR, ROLE_NAME, ROLE_INDEX, COORDINATES)

# A demonstration whose steps are mostly this weak is not worth keeping.
MAX_FRAGILE_RATIO = 0.34

# Actions that carry a typed value we must NOT store verbatim -- a
# demonstration of logging in would otherwise persist the password.
_SECRET_FIELDS = ("password", "passwd", "pin", "secret", "token", "api key",
                  "card", "cvv", "security code")


@dataclass
class Observation:
    """One thing the owner did, as the vision layer saw it."""

    action: str
    automation_id: str = ""
    selector: str = ""
    role: str = ""
    label: str = ""
    index: int = -1
    position: tuple[int, int] | None = None
    text: str = ""
    window: str = ""


@dataclass
class Generalised:
    step: Step
    rung: str
    fragile: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"action": self.step.action, "target": self.step.target,
                "rung": self.rung, "fragile": self.fragile}


@dataclass
class Learned:
    skill: Skill | None = None
    steps: list[Generalised] = field(default_factory=list)
    reason: str = ""
    redacted: int = 0

    @property
    def ok(self) -> bool:
        return self.skill is not None

    @property
    def fragile_ratio(self) -> float:
        return (sum(1 for s in self.steps if s.fragile) / len(self.steps)
                if self.steps else 0.0)

    def as_dict(self) -> dict[str, Any]:
        return {"learned": self.ok, "reason": self.reason,
                "steps": [s.as_dict() for s in self.steps],
                "fragile_ratio": round(self.fragile_ratio, 2),
                "redacted_values": self.redacted,
                "skill": self.skill.as_dict() if self.skill else None}


def _looks_secret(observation: Observation) -> bool:
    haystack = f"{observation.label} {observation.automation_id}".lower()
    return any(marker in haystack for marker in _SECRET_FIELDS)


def _generalise_one(observation: Observation) -> Generalised:
    """Pick the most durable identifier this element actually offered."""
    action = str(observation.action or "").strip().lower()

    if observation.automation_id:
        return Generalised(Step(action=action, target=observation.automation_id,
                                arguments={"by": AUTOMATION_ID,
                                           "window": observation.window}),
                           AUTOMATION_ID)
    if observation.selector:
        return Generalised(Step(action=action, target=observation.selector,
                                arguments={"by": SELECTOR}), SELECTOR)
    if observation.label:
        return Generalised(Step(action=action, target=observation.label,
                                arguments={"by": ROLE_NAME, "role": observation.role,
                                           "window": observation.window}),
                           ROLE_NAME)
    if observation.role and observation.index >= 0:
        return Generalised(Step(action=action, target=f"{observation.role}#{observation.index}",
                                arguments={"by": ROLE_INDEX}), ROLE_INDEX)

    # Last resort. Recorded, but marked, and counted against the recording.
    position = observation.position or (0, 0)
    return Generalised(Step(action=action, target=f"{position[0]},{position[1]}",
                            arguments={"by": COORDINATES},
                            on_failure="stop"),
                       COORDINATES, fragile=True)


def generalise(observations: list[Observation], *, name: str,
               description: str = "", persist: bool = True) -> Learned:
    """Convert a watched sequence into a durable, non-runnable candidate."""
    result = Learned()
    if not observations:
        result.reason = "I did not see anything to learn from."
        return result

    for observation in observations:
        generalised = _generalise_one(observation)
        # Never persist a typed secret, however the demonstration captured it.
        if observation.text:
            if _looks_secret(observation):
                generalised.step.arguments["value"] = "[[ASK THE OWNER]]"
                result.redacted += 1
            else:
                generalised.step.arguments["value"] = observation.text
        result.steps.append(generalised)

    if result.fragile_ratio > MAX_FRAGILE_RATIO:
        fragile = [s.step.action for s in result.steps if s.fragile]
        result.reason = (
            f"{int(result.fragile_ratio * 100)}% of that demonstration could only be "
            f"recorded as screen positions ({', '.join(fragile[:4])}). That would "
            "break the first time a window moves, so I have not saved it. Show me "
            "again with the application in the foreground and I should be able to "
            "read the controls properly.")
        return result

    skill = Skill(
        name=name,
        description=(description or f"Learned by watching you, on "
                     f"{time.strftime('%d %b %Y')}. "
                     f"{len(result.steps)} steps, identified by control rather "
                     "than by screen position."),
        state=LEARNED,
        steps=[g.step for g in result.steps],
        required_tools=sorted({g.step.action for g in result.steps}),
        verification="Each step is re-grounded against the live window before it runs.",
        failure_recovery="stop",
        confidence=0.4,             # watched once
        observations=1,
        source="demonstrated")

    result.skill = skill
    result.reason = (f"I watched {len(result.steps)} steps and generalised them to "
                     "real controls. It will not run until you approve it.")
    if result.redacted:
        result.reason += (f" I did not keep {result.redacted} value(s) that looked "
                          "like credentials -- I will ask you for those.")

    if persist:
        stored, why = skill_registry.save(skill, event="demonstrated")
        if not stored:
            result.skill = None
            result.reason = why
    return result


def status() -> dict[str, Any]:
    return {
        "state": "ONLINE",
        "identifier_preference": list(STRENGTH),
        "max_fragile_ratio": MAX_FRAGILE_RATIO,
        "produces": LEARNED,
        "note": ("Actions are generalised to the most durable identifier the element "
                 "offered. A demonstration that could only be captured as screen "
                 "positions is refused rather than saved, because it would break the "
                 "first time a window moved."),
        "secrets": "typed values that look like credentials are never stored",
    }
