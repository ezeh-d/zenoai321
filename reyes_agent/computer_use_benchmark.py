"""Small ZENO-specific, verifier-led computer-use evaluation contract.

This does not touch the owner's desktop automatically. A caller supplies an
executor in an isolated test desktop; each result must include independent
verification evidence.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ComputerUseCase:
    case_id: str
    command: str
    expected_capability: str
    verification_strategy: str


DEFAULT_CASES = (
    ComputerUseCase("open-notepad", "Open Notepad", "open_app", "process_or_window"),
    ComputerUseCase("create-text-file", "Create a text file with expected content", "write_project_file", "file"),
    ComputerUseCase("browser-navigation", "Open an isolated test page", "browser_open", "page_state"),
    ComputerUseCase("cancel-active-task", "Cancel the active test task", "emergency_stop", "task_state"),
)


class ZenoComputerUseBenchmark:
    def __init__(self, cases: tuple[ComputerUseCase, ...] = DEFAULT_CASES) -> None:
        self.cases = cases

    def run(self, executor: Callable[[ComputerUseCase], dict[str, Any]]) -> dict[str, Any]:
        rows = []
        for case in self.cases:
            started = time.perf_counter()
            try:
                result = executor(case)
                verified = bool(result.get("verified"))
                error = str(result.get("error") or "")
            except Exception as exc:
                result, verified, error = {}, False, f"{type(exc).__name__}: {exc}"
            rows.append({"case_id": case.case_id, "verified": verified,
                         "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                         "evidence": result.get("evidence", {}), "error": error})
        passed = sum(row["verified"] for row in rows)
        return {"passed": passed, "total": len(rows),
                "pass_rate": round(passed / len(rows), 4) if rows else None,
                "results": rows}
