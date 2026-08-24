"""Read-only self-diagnostics and dependency-root-cause reporting."""
from __future__ import annotations

import time
from typing import Any


class DependencyHealthGraph:
    def snapshot(self) -> dict[str, Any]:
        from reyes_agent.capability_truth import get_truth
        return {"capabilities": get_truth().dashboard(), "edges": get_truth().dependencies()}


class DiagnosticsEngine:
    def diagnose(self, capability: str = "") -> dict[str, Any]:
        started = time.perf_counter()
        if capability:
            from reyes_agent.capability_truth import get_truth
            return {"scope": capability, "diagnosis": get_truth().diagnose(capability),
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2)}
        from reyes_agent import system_health
        from reyes_agent.capability_snapshot import system_status
        from reyes_agent.evidence_ledger import get_evidence_ledger
        from reyes_agent.quality_score import get_quality_score
        from reyes_agent.resource_governor import get_resource_governor
        from reyes_agent.unified_session import get_session_state
        report = {
            "title": "ZENO SYSTEM HEALTH",
            "health": system_health.snapshot(),
            "capabilities": system_status(),
            "session": get_session_state().snapshot(),
            "evidence": get_evidence_ledger().stats(),
            "resources": get_resource_governor().evaluate(),
            "quality": get_quality_score().score(),
        }
        report["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return report


class ZenoDoctor(DiagnosticsEngine):
    pass


_doctor = ZenoDoctor()


def get_doctor() -> ZenoDoctor:
    return _doctor
