"""Finite browser fallback orchestration with required postcondition proof."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


def execute_with_recovery(
    operation: str,
    backends: list[tuple[str, Callable[[], Any]]],
    verify: Callable[[Any], tuple[bool, str]],
    *,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for backend, invoke in backends[:5]:
        if cancelled and cancelled():
            return {"ok": False, "state": "CANCELLED", "operation": operation, "attempts": attempts}
        try:
            result = invoke()
            verified, evidence = verify(result)
        except Exception as exc:  # backend isolation
            attempts.append({"backend": backend, "ok": False, "reason": f"{type(exc).__name__}: {exc}"[:240]})
            continue
        attempts.append({"backend": backend, "ok": verified, "evidence": str(evidence)[:300]})
        if verified:
            return {"ok": True, "state": "COMPLETED", "verified": True,
                    "backend": backend, "evidence": evidence, "attempts": attempts, "result": result}
    return {"ok": False, "state": "FAILED", "verified": False, "operation": operation,
            "reason": "all available browser backends failed verification", "attempts": attempts}
