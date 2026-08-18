"""Observable central task lifecycle over ZENO's existing executor.

This does not schedule or execute work itself. It records the single agent
loop's real stages, autonomy decisions, results and verification evidence.
"""

from __future__ import annotations

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
    outcome: str = "returned"
    verification_state: str = "unverified"


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
        # Reuse the authoritative tool-result classifier.  A function
        # returning normally is not proof its requested effect happened.
        # The former trace treated every non-error string as verified, which
        # contradicted the execution gate and made diagnostics overclaim.
        from reyes_agent.tools import classify_tool_result

        classification = classify_tool_result(result)
        outcome = str(classification.get("outcome") or "returned")
        verification_state = str(classification.get("verification_state") or "unverified")
        ok = outcome not in {"failed"}
        self.evidence.append(Evidence(
            name, ok, text[:500], autonomy,
            outcome=outcome, verification_state=verification_state,
        ))
        if not ok:
            self.may_recover()

    def verification(self) -> dict[str, Any]:
        self.enter(Stage.VERIFY)
        if not self.evidence:
            return {"verified": True, "basis": "talk-only response", "autonomy": talk_only().as_dict()}
        failures = [item for item in self.evidence if not item.ok]
        unverified = [item for item in self.evidence
                      if item.verification_state != "verified"]
        return {"verified": not failures and not unverified,
                "tool_results": len(self.evidence),
                "failures": [item.tool for item in failures],
                "unverified": [item.tool for item in unverified]}

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
                              "outcome": item.outcome,
                              "verification_state": item.verification_state,
                              "autonomy": item.autonomy} for item in self.evidence],
                "error": self.error}
