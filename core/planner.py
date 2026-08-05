"""
Planning & reasoning.

Turns a goal into an ordered, checkable plan. Uses the LLM when available and
falls back to a deterministic heuristic so planning still works fully offline.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


@dataclass
class Step:
    n: int
    action: str
    done: bool = False
    result: str = ""

    def render(self) -> str:
        box = "✓" if self.done else " "
        tail = f"  → {self.result}" if self.result else ""
        return f"  [{box}] {self.n}. {self.action}{tail}"


@dataclass
class Plan:
    goal: str
    steps: list[Step] = field(default_factory=list)

    def render(self) -> str:
        head = f"Plan for: {self.goal}"
        body = "\n".join(s.render() for s in self.steps) or "  (no steps)"
        return f"{head}\n{body}"

    def next_step(self) -> Step | None:
        return next((s for s in self.steps if not s.done), None)

    def mark(self, n: int, result: str = "") -> None:
        for s in self.steps:
            if s.n == n:
                s.done = True
                s.result = result

    @property
    def complete(self) -> bool:
        return all(s.done for s in self.steps) if self.steps else False


_PLAN_PROMPT = (
    "You are a planning module. Break the user's goal into 2-6 concrete, ordered "
    "steps. Reply with ONLY a JSON array of short imperative strings, e.g. "
    '["Do X", "Then Y", "Verify Z"]. No prose, no markdown.'
)


class Planner:
    """Produces and reasons over plans."""

    def __init__(self, llm=None):
        self._llm = llm  # inject for testing; created lazily otherwise

    @property
    def llm(self):
        if self._llm is None:
            from llm import LLM  # lazy so importing planner needs no LLM deps
            self._llm = LLM()
        return self._llm

    def make_plan(self, goal: str) -> Plan:
        steps = self._llm_steps(goal)
        if not steps:
            steps = self._heuristic_steps(goal)
        return Plan(goal=goal, steps=[Step(i + 1, s) for i, s in enumerate(steps)])

    # -- internal ------------------------------------------------------------
    def _llm_steps(self, goal: str) -> list[str]:
        try:
            raw = self.llm.complete(
                [
                    {"role": "system", "content": _PLAN_PROMPT},
                    {"role": "user", "content": goal},
                ]
            )
        except Exception:
            return []
        return self._parse_steps(raw)

    @staticmethod
    def _parse_steps(raw: str) -> list[str]:
        if not raw:
            return []
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
        return [str(x).strip() for x in data if str(x).strip()][:6]

    @staticmethod
    def _heuristic_steps(goal: str) -> list[str]:
        """Offline fallback: split on connectives, else a generic 3-step arc."""
        parts = re.split(r"\s+(?:and then|then|and|after that|,)\s+", goal.strip())
        parts = [p.strip(" .").capitalize() for p in parts if len(p.strip()) > 2]
        if len(parts) >= 2:
            return parts[:6]
        return [
            f"Clarify what success looks like for: {goal}",
            f"Carry out the core work for: {goal}",
            "Verify the result and report back",
        ]


def quick_plan(goal: str) -> str:
    """Convenience for tool use: return a rendered plan string."""
    return Planner().make_plan(goal).render()
