"""Run an approved skill -- through the same gates as everything else.

A skill is not a privileged path. Each step goes through `run_tool`, so the
permission engine, the confirmation gate and every existing safety check
apply exactly as they would if the owner had asked for that action directly.
A learned skill gets no more authority than the actions it was learned from.

Three independent stops, because a skill is automation running unattended:
step count, wall-clock deadline, and the first failure. There is no retry
loop that can grind -- `on_failure: retry` gets exactly one more attempt.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from reyes_agent.skills import constitution, registry
from reyes_agent.skills.models import Skill

MAX_STEPS = 20
DEADLINE_S = 300.0


@dataclass
class StepResult:
    action: str
    ok: bool = False
    detail: str = ""
    skipped: bool = False
    attempts: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"action": self.action, "ok": self.ok, "detail": self.detail[:400],
                "skipped": self.skipped, "attempts": self.attempts}


@dataclass
class Run:
    skill_id: str
    name: str
    ok: bool = False
    reason: str = ""
    steps: list[StepResult] = field(default_factory=list)
    duration_s: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"skill_id": self.skill_id, "name": self.name, "ok": self.ok,
                "reason": self.reason, "duration_s": round(self.duration_s, 2),
                "steps": [s.as_dict() for s in self.steps]}

    def summary(self) -> str:
        lines = [f"{self.name}: {self.reason}"]
        for step in self.steps:
            mark = "skip" if step.skipped else ("ok  " if step.ok else "FAIL")
            lines.append(f"  {mark} {step.action} -- {step.detail[:100]}")
        return "\n".join(lines)


def _call_tool(action: str, arguments: dict[str, Any]) -> tuple[bool, str]:
    """One step, through the ordinary gated tool path."""
    try:
        from reyes_agent.tools import run_tool
    except Exception as exc:  # noqa: BLE001
        return False, f"tool registry unavailable: {type(exc).__name__}: {exc}"
    try:
        result = run_tool(action, arguments or {})
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    text = str(result)
    # `run_tool` reports refusals as text rather than raising, so a step that
    # was blocked must not be recorded as a success.
    lowered = text.lower()
    blocked = any(marker in lowered for marker in
                  ("not allowed", "permission", "needs your", "requires confirmation",
                   "refused", "blocked"))
    return (not blocked), text


def execute(skill: Skill, *, cancel_check: Callable[[], None] | None = None) -> Run:
    """Run an APPROVED skill. Anything else is refused."""
    run = Run(skill_id=skill.skill_id, name=skill.name)
    started = time.time()

    # Re-check the constitution against the steps as they are RIGHT NOW.
    # A verdict from when the skill was stored says nothing about the file
    # on disk today.
    verdict = constitution.review(skill)
    if not verdict.allowed:
        run.reason = "refused: " + verdict.reason
        registry.audit("blocked", skill, verdict.reason)
        return run

    if not skill.runnable:
        run.reason = (f"'{skill.name}' is {skill.state}, not APPROVED -- I will not run "
                      "a skill you have not approved.")
        return run

    for index, step in enumerate(skill.steps[:MAX_STEPS]):
        if cancel_check:
            try:
                cancel_check()
            except Exception:  # noqa: BLE001
                run.reason = "cancelled"
                _record(skill, run, started)
                return run
        if time.time() - started > DEADLINE_S:
            run.reason = f"stopped at the {DEADLINE_S:.0f}s deadline after {index} step(s)"
            _record(skill, run, started)
            return run

        outcome = StepResult(action=step.action)
        attempts = 2 if step.on_failure == "retry" else 1
        for attempt in range(1, attempts + 1):
            outcome.attempts = attempt
            outcome.ok, outcome.detail = _call_tool(step.action, step.arguments)
            if outcome.ok:
                break
        run.steps.append(outcome)

        if not outcome.ok:
            if step.on_failure == "skip":
                outcome.skipped = True
                continue
            run.reason = f"step {index + 1} ({step.action}) failed: {outcome.detail[:160]}"
            _record(skill, run, started)
            return run

    run.ok = True
    run.reason = f"completed {len(run.steps)} step(s)"
    _record(skill, run, started)
    return run


def _record(skill: Skill, run: Run, started: float) -> None:
    """A skill's history is what actually happened to it, not what we hoped."""
    run.duration_s = time.time() - started
    skill.history.runs += 1
    skill.history.last_run_at = time.time()
    if run.ok:
        skill.history.successes += 1
        skill.history.last_success_at = time.time()
    else:
        skill.history.failures += 1
        skill.history.last_error = run.reason[:300]
    registry.save(skill, event="ran", detail=run.reason[:200])
