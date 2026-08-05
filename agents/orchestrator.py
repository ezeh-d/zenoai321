"""
Multi-agent orchestrator.

Given a task it (1) routes to the best specialist by intent, or (2) for a
complex goal, drafts a plan and runs the relevant agents step by step, then
synthesizes one answer. Routing is keyword-based so it works with no LLM; the
agents themselves use the LLM when available.
"""
from __future__ import annotations

from agents.specialists import ALL_AGENTS, Analyst


# intent keywords -> agent name
_ROUTES: dict[str, tuple[str, ...]] = {
    "researcher": ("research", "find", "look up", "search", "news", "who is",
                   "what is", "compare", "latest"),
    "coder": ("code", "bug", "debug", "python", "javascript", "function",
              "script", "build a", "app", "website", "api", "refactor"),
    "operator": ("open", "launch", "click", "type", "screenshot", "file",
                 "folder", "run command", "install", "desktop"),
    "writer": ("write", "draft", "email", "post", "summarize", "rewrite",
               "edit", "message"),
    "analyst": ("analyze", "should i", "recommend", "pros and cons",
                "trade-off", "decide", "evaluate", "plan for"),
}


class Orchestrator:
    def __init__(self, llm=None):
        self._llm = llm
        self._agents = {cls.name: cls(llm=llm) for cls in ALL_AGENTS}

    # -- routing -------------------------------------------------------------
    def route(self, task: str) -> str:
        t = task.lower()
        best, score = "analyst", 0
        for name, keys in _ROUTES.items():
            hits = sum(1 for k in keys if k in t)
            if hits > score:
                best, score = name, hits
        return best

    def agent(self, name: str):
        return self._agents.get(name, self._agents["analyst"])

    # -- execution -----------------------------------------------------------
    def dispatch(self, task: str, agent: str | None = None, context: str = "") -> str:
        chosen = agent or self.route(task)
        result = self.agent(chosen).run(task, context=context)
        return f"[{result.agent}] {result.output}"

    def solve(self, goal: str) -> str:
        """Plan the goal, run each step with the fitting agent, synthesize."""
        from core.planner import Planner

        plan = Planner(llm=self._llm).make_plan(goal)
        transcript: list[str] = [plan.render(), ""]
        context = ""
        for step in plan.steps:
            name = self.route(step.action)
            out = self.agent(name).run(step.action, context=context).output
            plan.mark(step.n, result=f"({name}) done")
            transcript.append(f"Step {step.n} · {name}: {out}")
            context = (context + "\n" + out)[-4000:]  # carry rolling context

        summary = Analyst(llm=self._llm).run(
            "Synthesize the step results into one clear final answer for the "
            f"original goal: {goal}",
            context="\n".join(transcript[2:]),
        ).output
        transcript.append("")
        transcript.append(f"FINAL: {summary}")
        return "\n".join(transcript)


# convenience wrappers for tool use
def delegate(task: str, agent: str | None = None) -> str:
    return Orchestrator().dispatch(task, agent=agent)


def solve_goal(goal: str) -> str:
    return Orchestrator().solve(goal)
