"""Observable central task lifecycle over ZENO's existing executor.

This does not schedule or execute work itself. It records the single agent
loop's real stages, autonomy decisions, results and verification evidence.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from reyes_agent.autonomy import classify_tool, talk_only


class Stage(str, Enum):
    UNDERSTAND = "UNDERSTAND"
    RETRIEVE_MEMORY = "RETRIEVE_MEMORY"
    PLAN = "PLAN"
    SELECT_AGENT = "SELECT_AGENT"
    SELECT_TOOL = "SELECT_TOOL"
    EXECUTE = "EXECUTE"
    OBSERVE_RESULT = "OBSERVE_RESULT"
    VERIFY = "VERIFY"
    STORE_MEMORY = "STORE_MEMORY"
    RESPOND = "RESPOND"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class Evidence:
    tool: str
    ok: bool
    result: str
    autonomy: dict[str, Any]


@dataclass
class ExecutionTrace:
    goal: str
    correlation_id: str = ""
    max_recovery_attempts: int = 2
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    stage: Stage = Stage.UNDERSTAND
    started_at: float = field(default_factory=time.time)
    evidence: list[Evidence] = field(default_factory=list)
    recovery_attempts: int = 0
    error: str = ""

    def __post_init__(self) -> None:
        self.max_recovery_attempts = max(0, min(3, int(self.max_recovery_attempts)))
        self._publish()

    def enter(self, stage: Stage, **detail: Any) -> None:
        self.stage = stage
        self._publish(detail)

    def selected_tool(self, name: str, *, requires_confirmation: bool = False) -> dict[str, Any]:
        self.enter(Stage.SELECT_AGENT if name == "delegate" else Stage.SELECT_TOOL, tool=name)
        decision = classify_tool(name, requires_confirmation=requires_confirmation).as_dict()
        self._publish({"tool": name, "autonomy": decision})
        return decision

    def observed(self, name: str, result: str, autonomy: dict[str, Any]) -> None:
        self.enter(Stage.OBSERVE_RESULT, tool=name)
        text = str(result or "")
        folded = text.casefold().lstrip()
        failure_prefixes = ("error", "blocked", "cancelled", "canceled", "failed")
        failure_fragments = ("timed out", "timeout", " has not run", " nothing ran", " has not been run")
        ok = not (folded.startswith(failure_prefixes) or any(marker in folded for marker in failure_fragments))
        if folded.startswith("{"):
            try:
                structured = json.loads(text)
                if isinstance(structured, dict):
                    if structured.get("ok") is False or structured.get("success") is False:
                        ok = False
                    state = str(structured.get("state") or structured.get("status") or "").casefold()
                    if state in {"failed", "error", "blocked", "cancelled", "canceled", "timeout"}:
                        ok = False
            except (json.JSONDecodeError, TypeError):
                pass
        self.evidence.append(Evidence(name, ok, text[:500], autonomy))
        if not ok:
            self.may_recover()

    def verification(self) -> dict[str, Any]:
        self.enter(Stage.VERIFY)
        if not self.evidence:
            return {"verified": True, "basis": "talk-only response", "autonomy": talk_only().as_dict()}
        failures = [item for item in self.evidence if not item.ok]
        return {"verified": not failures, "tool_results": len(self.evidence),
                "failures": [item.tool for item in failures]}

    def may_recover(self) -> bool:
        if self.recovery_attempts >= self.max_recovery_attempts:
            return False
        self.recovery_attempts += 1
        self._publish({"recovery_attempt": self.recovery_attempts})
        return True

    def finish(self, *, stored: bool = False) -> None:
        if stored:
            self.enter(Stage.STORE_MEMORY)
        self.enter(Stage.RESPOND)

    def fail(self, error: str) -> None:
        self.error = str(error)[:500]
        self.enter(Stage.FAILED, error=self.error)

    def _publish(self, detail: dict[str, Any] | None = None) -> None:
        try:
            from reyes_agent import event_bus

            event_bus.publish("execution.lifecycle", {
                "trace_id": self.trace_id, "stage": self.stage.value,
                "goal": self.goal[:240], "recovery_attempts": self.recovery_attempts,
                "evidence_count": len(self.evidence), **(detail or {}),
            }, source="execution_lifecycle", correlation_id=self.correlation_id)
        except Exception:
            pass

    def snapshot(self) -> dict[str, Any]:
        return {"trace_id": self.trace_id, "stage": self.stage.value,
                "duration_ms": round((time.time() - self.started_at) * 1000, 1),
                "recovery_attempts": self.recovery_attempts,
                "evidence": [{"tool": item.tool, "ok": item.ok,
                              "autonomy": item.autonomy} for item in self.evidence],
                "error": self.error}
