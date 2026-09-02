"""Small, dependency-free benchmarks for ZENO's deterministic hot paths.

These helpers deliberately benchmark only in-process work.  They do not
start ZENO, connect a provider, or initialize optional hardware.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable, Iterable
from typing import Any


ROUTE_CASES = (
    "Hello ZENO, how are you?",
    "What time is it?",
    "Open Chrome",
    "Search YouTube for football highlights",
    "Remember that blue is my test colour",
    "Look at my screen",
    "Fix this Python traceback",
)


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return round(ordered[index], 4)


def summarize(
    samples_ms: Iterable[float], *, attempts: int, failures: int
) -> dict[str, int | float | None]:
    """Return JSON-safe latency distribution data without hiding failures."""
    if attempts < 0:
        raise ValueError("attempts must be non-negative")
    if failures < 0 or failures > attempts:
        raise ValueError("failures must be between zero and attempts")

    samples = [float(sample) for sample in samples_ms]
    if len(samples) + failures != attempts:
        raise ValueError("samples plus failures must equal attempts")

    return {
        "samples": len(samples),
        "attempts": attempts,
        "failures": failures,
        "failure_rate_pct": round((failures / attempts * 100) if attempts else 0.0, 4),
        "p50_ms": _percentile(samples, 0.50),
        "p90_ms": _percentile(samples, 0.90),
        "p95_ms": _percentile(samples, 0.95),
        "p99_ms": _percentile(samples, 0.99),
        "max_ms": round(max(samples), 4) if samples else None,
    }


def run_case(
    name: str,
    action: Callable[[], object],
    *,
    iterations: int = 200,
    warmups: int = 5,
) -> dict[str, Any]:
    """Measure a local action, excluding warmups but retaining failures."""
    if iterations < 1:
        raise ValueError("iterations must be at least one")
    if warmups < 0:
        raise ValueError("warmups must be non-negative")

    for _ in range(warmups):
        try:
            action()
        except Exception:  # noqa: BLE001 - warmups never decide suite success
            pass

    samples: list[float] = []
    errors: dict[str, int] = {}
    failures = 0
    for _ in range(iterations):
        started = time.perf_counter_ns()
        try:
            action()
        except Exception as exc:  # noqa: BLE001 - evidence must retain failure count
            failures += 1
            error_name = type(exc).__name__
            if error_name in errors or len(errors) < 10:
                errors[error_name] = errors.get(error_name, 0) + 1
        else:
            samples.append((time.perf_counter_ns() - started) / 1_000_000)

    return {
        "name": str(name),
        **summarize(samples, attempts=iterations, failures=failures),
        "errors": errors,
    }


def run_router_benchmark(
    *, iterations: int = 200, warmups: int = 5
) -> dict[str, Any]:
    """Benchmark fixed capability-routing cases without launching ZENO."""
    from reyes_agent.routing import capability

    cases: list[dict[str, Any]] = []
    for message in ROUTE_CASES:
        calls = 0
        final_route: dict[str, Any] = {"tools_exposed": None}

        def action(message: str = message) -> object:
            nonlocal calls
            calls += 1
            capability.clear_context()
            route = capability.tools_for(message)
            if calls > warmups:
                final_route["tools_exposed"] = route.exposed
            return route

        row = run_case(message, action, iterations=iterations, warmups=warmups)
        row["tools_exposed"] = final_route["tools_exposed"]
        cases.append(row)

    return {
        "suite": "router",
        "iterations": iterations,
        "warmups": warmups,
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    """Run the explicit local-only benchmark suite and print one JSON result."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--router-only", action="store_true",
                        help="benchmark fixed in-process capability routes")
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--warmups", type=int, default=5)
    args = parser.parse_args(argv)
    if not args.router_only:
        parser.error("--router-only is required")
    try:
        result = run_router_benchmark(
            iterations=args.iterations, warmups=args.warmups
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
