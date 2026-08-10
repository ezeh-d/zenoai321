"""What a ZENO skill IS, and the three states it can be in.

THE DISTINCTION THAT MATTERS
----------------------------
The brief is explicit that ZENO must not turn one random action into
powerful automation, so a skill is not one thing that either exists or does
not. It moves through three states, and they mean genuinely different
things:

  OBSERVED   ZENO noticed a sequence repeat. It is a statistic, nothing
             more. It cannot run. It cannot be triggered. Most observations
             die here and that is the correct outcome.

  LEARNED    The sequence cleared a confidence threshold over enough
             separate occasions. ZENO may now SUGGEST it. It still cannot
             run on its own.

  APPROVED   The owner said yes. Only now can it execute, and only through
             the same permission engine every other tool answers to.

Nothing promotes itself. `learner` can propose OBSERVED -> LEARNED;
only an explicit human act reaches APPROVED.

VERSIONS AND HISTORY
--------------------
A skill records what actually happened to it -- runs, successes, failures,
and when it last worked. That history is what `improver` reasons about, and
it is also the honest answer to "should I trust this?". A skill with two
runs is not a proven skill and says so.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

OBSERVED = "OBSERVED"
LEARNED = "LEARNED"
APPROVED = "APPROVED"
RETIRED = "RETIRED"          # kept for history, never runs again

STATES = (OBSERVED, LEARNED, APPROVED, RETIRED)

# Promotion never skips a rung.
_NEXT = {OBSERVED: LEARNED, LEARNED: APPROVED}


@dataclass
class Step:
    """One action in a skill. Mirrors the shape the executors already take."""

    action: str
    target: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    expect: str = ""              # what must be true afterwards
    on_failure: str = "stop"      # stop | skip | retry

    def as_dict(self) -> dict[str, Any]:
        return {"action": self.action, "target": self.target,
                "arguments": self.arguments, "expect": self.expect,
                "on_failure": self.on_failure}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Step":
        return cls(action=str(raw.get("action", "")), target=str(raw.get("target", "")),
                   arguments=dict(raw.get("arguments") or {}),
                   expect=str(raw.get("expect", "")),
                   on_failure=str(raw.get("on_failure", "stop")))


@dataclass
class History:
    runs: int = 0
    successes: int = 0
    failures: int = 0
    last_run_at: float = 0.0
    last_success_at: float = 0.0
    last_error: str = ""

    @property
    def success_rate(self) -> float:
        return (self.successes / self.runs) if self.runs else 0.0

    @property
    def proven(self) -> bool:
        """Enough runs, and enough of them worked, to be worth trusting."""
        return self.runs >= 5 and self.success_rate >= 0.8

    def as_dict(self) -> dict[str, Any]:
        return {"runs": self.runs, "successes": self.successes, "failures": self.failures,
                "success_rate": round(self.success_rate, 3), "proven": self.proven,
                "last_run_at": self.last_run_at, "last_success_at": self.last_success_at,
                "last_error": self.last_error[:300]}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "History":
        return cls(runs=int(raw.get("runs", 0)), successes=int(raw.get("successes", 0)),
                   failures=int(raw.get("failures", 0)),
                   last_run_at=float(raw.get("last_run_at", 0.0)),
                   last_success_at=float(raw.get("last_success_at", 0.0)),
                   last_error=str(raw.get("last_error", "")))


@dataclass
class Skill:
    name: str
    description: str = ""
    state: str = OBSERVED
    steps: list[Step] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    verification: str = ""
    failure_recovery: str = ""
    version: int = 1
    confidence: float = 0.0
    observations: int = 0            # how many times the sequence was really seen
    history: History = field(default_factory=History)
    skill_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    approved_by: str = ""
    source: str = "learned"          # learned | authored

    @property
    def runnable(self) -> bool:
        """Only an owner-approved skill may execute. No exceptions."""
        return self.state == APPROVED and bool(self.steps)

    def next_state(self) -> str | None:
        return _NEXT.get(self.state)

    def as_dict(self) -> dict[str, Any]:
        return {"skill_id": self.skill_id, "name": self.name,
                "description": self.description, "state": self.state,
                "steps": [s.as_dict() for s in self.steps],
                "triggers": list(self.triggers),
                "required_tools": list(self.required_tools),
                "permissions": list(self.permissions),
                "verification": self.verification,
                "failure_recovery": self.failure_recovery,
                "version": self.version, "confidence": round(self.confidence, 3),
                "observations": self.observations, "history": self.history.as_dict(),
                "created_at": self.created_at, "updated_at": self.updated_at,
                "approved_by": self.approved_by, "source": self.source,
                "runnable": self.runnable}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Skill":
        skill = cls(
            name=str(raw.get("name", "")), description=str(raw.get("description", "")),
            state=str(raw.get("state", OBSERVED)),
            steps=[Step.from_dict(s) for s in raw.get("steps") or []],
            triggers=list(raw.get("triggers") or []),
            required_tools=list(raw.get("required_tools") or []),
            permissions=list(raw.get("permissions") or []),
            verification=str(raw.get("verification", "")),
            failure_recovery=str(raw.get("failure_recovery", "")),
            version=int(raw.get("version", 1)),
            confidence=float(raw.get("confidence", 0.0)),
            observations=int(raw.get("observations", 0)),
            history=History.from_dict(raw.get("history") or {}),
            approved_by=str(raw.get("approved_by", "")),
            source=str(raw.get("source", "learned")))
        if raw.get("skill_id"):
            skill.skill_id = str(raw["skill_id"])
        skill.created_at = float(raw.get("created_at", skill.created_at))
        skill.updated_at = float(raw.get("updated_at", skill.updated_at))
        return skill

    def summary(self) -> str:
        bits = [f"{self.name} [{self.state}] v{self.version}"]
        if self.observations:
            bits.append(f"seen {self.observations}x")
        if self.history.runs:
            bits.append(f"{self.history.successes}/{self.history.runs} succeeded")
        if self.state != APPROVED:
            bits.append("cannot run until you approve it")
        return " -- ".join(bits)
