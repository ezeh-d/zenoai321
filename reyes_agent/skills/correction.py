"""Take a correction now; change the skill only when it has earned it.

    "No ZENO, click Export before Save."

TWO THINGS THAT MUST NOT BE CONFLATED
-------------------------------------
The correction applies to THIS RUN immediately -- the owner said what they
want, and arguing is not an option.

Whether it should change the stored SKILL is a different question, and the
brief is explicit: "Do not rewrite skill after one accidental correction
unless confidence is sufficient." People misspeak, click the wrong thing,
change their mind, and correct for a one-off reason ("do it in that order
just this once, the file is locked"). A skill rewritten on every stray
remark degrades toward whatever the owner last said under pressure.

So a correction is recorded as EVIDENCE. The stored skill changes when the
same correction has arrived enough times, or when the owner says outright
that it is permanent.

VERSIONS, NOT EDITS
-------------------
When a correction is applied, the previous version is kept. "Never silently
destroy a working skill" -- if the correction turns out to be the mistake,
there is something to go back to.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from reyes_agent.skills import registry as skill_registry, versions
from reyes_agent.skills.models import Skill, Step

# How many times the same correction must arrive before it rewrites a skill.
# Two: one could be a slip, twice is a pattern.
CONFIRMATIONS_REQUIRED = 2

# Corrections older than this stop counting -- a workflow that changed six
# months ago should not be re-litigated by a stale note.
EVIDENCE_TTL_S = 60 * 60 * 24 * 30

REORDER = "reorder"
REPLACE = "replace"
INSERT = "insert"
REMOVE = "remove"

_evidence: dict[str, list[dict[str, Any]]] = {}


@dataclass
class Correction:
    skill_id: str
    kind: str
    subject: str = ""            # the step being moved/replaced/removed
    before: str = ""             # for REORDER: subject must come before this
    replacement: str = ""        # for REPLACE/INSERT
    permanent: bool = False      # the owner said "always"
    at: float = field(default_factory=time.time)

    def signature(self) -> str:
        """Two corrections are 'the same' when this matches."""
        return f"{self.kind}:{self.subject}:{self.before}:{self.replacement}".lower()

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "subject": self.subject, "before": self.before,
                "replacement": self.replacement, "permanent": self.permanent,
                "at": self.at}


@dataclass
class Outcome:
    applied_now: bool = False
    skill_updated: bool = False
    new_version: int = 0
    confirmations: int = 0
    needed: int = CONFIRMATIONS_REQUIRED
    say: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"applied_now": self.applied_now, "skill_updated": self.skill_updated,
                "new_version": self.new_version or None,
                "confirmations": self.confirmations, "needed": self.needed,
                "say": self.say}


def _fresh(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cutoff = time.time() - EVIDENCE_TTL_S
    return [e for e in entries if e["at"] >= cutoff]


def _apply(steps: list[Step], correction: Correction) -> list[Step] | None:
    """Return the reordered/edited steps, or None if it does not apply."""
    def find(target: str) -> int:
        target = target.strip().lower()
        for index, step in enumerate(steps):
            if target in f"{step.action} {step.target}".lower():
                return index
        return -1

    working = list(steps)

    if correction.kind == REORDER:
        moving, anchor = find(correction.subject), find(correction.before)
        if moving < 0 or anchor < 0 or moving == anchor:
            return None
        step = working.pop(moving)
        anchor = find_in(working, correction.before)
        if anchor < 0:
            return None
        working.insert(anchor, step)
        return working

    if correction.kind == REPLACE:
        index = find(correction.subject)
        if index < 0:
            return None
        working[index] = Step(action=correction.replacement or working[index].action,
                              target=working[index].target,
                              arguments=dict(working[index].arguments),
                              expect=working[index].expect)
        return working

    if correction.kind == INSERT:
        anchor = find(correction.before) if correction.before else len(working)
        if anchor < 0:
            return None
        working.insert(anchor, Step(action=correction.replacement, target=""))
        return working

    if correction.kind == REMOVE:
        index = find(correction.subject)
        if index < 0:
            return None
        working.pop(index)
        return working

    return None


def find_in(steps: list[Step], target: str) -> int:
    target = target.strip().lower()
    for index, step in enumerate(steps):
        if target in f"{step.action} {step.target}".lower():
            return index
    return -1


def correct(correction: Correction) -> Outcome:
    """Record a correction; rewrite the skill only once it is confirmed."""
    outcome = Outcome(needed=CONFIRMATIONS_REQUIRED)
    skill = skill_registry.get(correction.skill_id)
    if skill is None:
        outcome.say = "I do not have that skill, so there is nothing to correct."
        return outcome

    # The current run always obeys, whatever the evidence says.
    outcome.applied_now = _apply(skill.steps, correction) is not None
    if not outcome.applied_now:
        outcome.say = ("I could not match that correction to a step in "
                       f"'{skill.name}'. Which step did you mean?")
        return outcome

    entries = _fresh(_evidence.get(correction.skill_id, []))
    signature = correction.signature()
    entries.append({"signature": signature, "at": correction.at})
    _evidence[correction.skill_id] = entries
    outcome.confirmations = sum(1 for e in entries if e["signature"] == signature)

    if not (correction.permanent or outcome.confirmations >= CONFIRMATIONS_REQUIRED):
        outcome.say = (f"Done for this run. I have not changed '{skill.name}' itself "
                       "yet -- if you tell me again next time, or say 'always', I "
                       "will make it permanent.")
        return outcome

    updated = _apply(skill.steps, correction)
    if updated is None:
        outcome.say = "I could not apply that to the stored skill."
        return outcome

    # Keep what worked before touching it.
    versions.archive(skill, why=f"before correction: {correction.kind} "
                                f"{correction.subject}")
    skill.steps = updated
    skill.version += 1
    skill.confidence = max(0.3, skill.confidence * 0.8)   # changed: re-earn trust
    stored, why = skill_registry.save(skill, event="corrected",
                                      detail=correction.signature())
    if not stored:
        outcome.say = why
        return outcome

    outcome.skill_updated = True
    outcome.new_version = skill.version
    outcome.say = (f"Done, and I have updated '{skill.name}' to v{skill.version} so it "
                   "does that from now on. The previous version is kept if you want "
                   "it back.")
    return outcome


def evidence(skill_id: str) -> list[dict[str, Any]]:
    return _fresh(_evidence.get(skill_id, []))


def reset() -> None:
    _evidence.clear()


def status() -> dict[str, Any]:
    return {
        "state": "ONLINE",
        "kinds": [REORDER, REPLACE, INSERT, REMOVE],
        "confirmations_required": CONFIRMATIONS_REQUIRED,
        "evidence_ttl_days": round(EVIDENCE_TTL_S / 86400),
        "tracking": len(_evidence),
        "note": ("A correction applies to the current run immediately. It rewrites "
                 "the stored skill only after being confirmed, or when you say it "
                 "is permanent -- one stray remark should not reshape a workflow."),
    }
