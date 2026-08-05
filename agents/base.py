"""
Base class for REYES specialist agents.

An agent is a focused persona with its own system prompt and an optional set of
tools it's allowed to touch. Agents are cheap: they wrap the shared LLM and can
be run standalone or dispatched by the Orchestrator.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentResult:
    agent: str
    output: str
    steps: list[str] = field(default_factory=list)


class Agent:
    name: str = "agent"
    role: str = "a helpful specialist"
    # tool names (from the Brain registry) this agent is allowed to request
    tools: tuple[str, ...] = ()

    def __init__(self, llm=None):
        self._llm = llm

    @property
    def llm(self):
        if self._llm is None:
            from llm import LLM
            self._llm = LLM()
        return self._llm

    def system_prompt(self) -> str:
        tool_note = (
            f" You may rely on these capabilities: {', '.join(self.tools)}."
            if self.tools else ""
        )
        return (
            f"You are REYES's {self.name} agent — {self.role}. "
            "Be precise and concise. Do the specific job you were handed and "
            "return a clean, usable result." + tool_note
        )

    def run(self, task: str, context: str = "") -> AgentResult:
        messages = [{"role": "system", "content": self.system_prompt()}]
        if context:
            messages.append({"role": "user", "content": f"[CONTEXT]\n{context}"})
        messages.append({"role": "user", "content": task})
        try:
            output = self.llm.complete(messages)
        except Exception as e:  # pragma: no cover - depends on live LLM
            output = f"[{self.name} could not complete the task: {e}]"
        return AgentResult(agent=self.name, output=output.strip())
