"""Model-specific benchmark helper; refuses to infer a winner without runs."""
from __future__ import annotations

import statistics
import time
from typing import Any, Callable


def compare(backends: dict[str, Callable[[], Any]], repeats: int = 5) -> dict:
    runs: dict[str, list[float]] = {}
    errors: dict[str, str] = {}
    for name, invoke in backends.items():
        timings: list[float] = []
        try:
            for _ in range(max(2, min(int(repeats), 20))):
                started = time.perf_counter()
                invoke()
                timings.append((time.perf_counter() - started) * 1000)
        except Exception as exc:
            errors[name] = f"{type(exc).__name__}: {exc}"[:240]
        if timings:
            runs[name] = timings
    metrics = {name: {"median_ms": round(statistics.median(values), 3),
                      "worst_ms": round(max(values), 3), "runs": len(values)}
               for name, values in runs.items()}
    winner = min(metrics, key=lambda name: metrics[name]["median_ms"]) if len(metrics) >= 2 else None
    return {"verified": bool(winner), "winner": winner, "metrics": metrics, "errors": errors,
            "reason": "winner requires at least two successful real backends" if not winner else "lowest measured median"}
