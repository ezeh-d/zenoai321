"""Rolling-window reputation for tools and providers.

WHY
---
The router should prefer what actually works *lately*, not what worked once or
what failed during a five-minute outage six hours ago. This keeps a bounded
rolling window of recent outcomes per tool and turns them into a confidence
score the router can rank on.

Design choices that keep it stable:

* **Rolling window, not lifetime totals** -- a temporary provider outage decays
  out instead of permanently condemning a good tool (pack #20).
* **Wilson lower bound for confidence** -- a tool with 2/2 successes is *not*
  more trustworthy than one with 190/200; the lower bound is conservative when
  samples are few and only rises with evidence.
* **In-memory + thread-safe + bounded** -- no I/O on the hot path, fixed memory,
  never raises into a caller. Advisory data; it rebuilds quickly after a restart.
"""

from __future__ import annotations

import math
import threading
from collections import deque
from typing import Any, Deque

# How many recent outcomes to keep per tool. Enough to be stable, small enough
# that a tool that started failing is reflected within a handful of calls.
WINDOW = 100
_Z = 1.96  # 95% confidence for the Wilson interval


class _Stats:
    __slots__ = ("outcomes", "latencies")

    def __init__(self) -> None:
        self.outcomes: Deque[bool] = deque(maxlen=WINDOW)
        self.latencies: Deque[float] = deque(maxlen=WINDOW)


class ToolReputation:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tools: dict[str, _Stats] = {}

    def record(self, tool: str, ok: bool, *, latency_ms: float = 0.0) -> None:
        """Record one outcome. Never raises."""
        try:
            name = str(tool or "").strip()
            if not name:
                return
            with self._lock:
                stats = self._tools.get(name)
                if stats is None:
                    stats = self._tools[name] = _Stats()
                stats.outcomes.append(bool(ok))
                if latency_ms and latency_ms > 0:
                    stats.latencies.append(float(latency_ms))
        except Exception:  # noqa: BLE001 -- telemetry must never break a tool run
            pass

    def reputation(self, tool: str) -> dict[str, Any]:
        """Current reputation for one tool. Zeroed (confidence 0) if unseen."""
        name = str(tool or "").strip()
        with self._lock:
            stats = self._tools.get(name)
            outcomes = list(stats.outcomes) if stats else []
            latencies = sorted(stats.latencies) if stats else []
        return _summarise(name, outcomes, latencies)

    def all_reputations(self) -> list[dict[str, Any]]:
        with self._lock:
            items = [(n, list(s.outcomes), sorted(s.latencies))
                     for n, s in self._tools.items()]
        out = [_summarise(n, o, lat) for n, o, lat in items]
        out.sort(key=lambda r: (-r["confidence"], -r["samples"]))
        return out

    def best_of(self, tools: list[str]) -> str | None:
        """Pick the most trustworthy candidate. Unseen tools get the benefit of
        the doubt (confidence 0 ranks below any proven tool but ties break to the
        given order, so an all-unseen list returns the first candidate)."""
        best: tuple[float, int] | None = None
        chosen: str | None = None
        for tool in tools:
            rep = self.reputation(tool)
            key = (rep["confidence"], rep["samples"])
            if best is None or key > best:
                best, chosen = key, tool
        return chosen

    def reset(self) -> None:
        with self._lock:
            self._tools.clear()


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return round(sorted_values[0], 1)
    rank = pct / 100.0 * (len(sorted_values) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return round(sorted_values[lo], 1)
    frac = rank - lo
    return round(sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac, 1)


def _wilson_lower_bound(successes: int, n: int) -> float:
    """Lower bound of the Wilson score interval -- a sample-size-aware success
    rate. 0.0 when there is no evidence."""
    if n <= 0:
        return 0.0
    phat = successes / n
    denom = 1.0 + _Z * _Z / n
    centre = phat + _Z * _Z / (2 * n)
    margin = _Z * math.sqrt((phat * (1 - phat) + _Z * _Z / (4 * n)) / n)
    return max(0.0, (centre - margin) / denom)


def _summarise(name: str, outcomes: list[bool], latencies: list[float]) -> dict[str, Any]:
    n = len(outcomes)
    successes = sum(1 for ok in outcomes if ok)
    # Count the length of the current trailing failure streak.
    recent_failures = 0
    for ok in reversed(outcomes):
        if ok:
            break
        recent_failures += 1
    return {
        "tool": name,
        "samples": n,
        "success_rate": round(successes / n, 4) if n else 0.0,
        "confidence": round(_wilson_lower_bound(successes, n), 4),
        "median_latency_ms": _percentile(latencies, 50),
        "p95_latency_ms": _percentile(latencies, 95),
        "recent_failures": recent_failures,
    }


_instance: ToolReputation | None = None
_instance_lock = threading.Lock()


def get_reputation() -> ToolReputation:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = ToolReputation()
        return _instance


def record(tool: str, ok: bool, *, latency_ms: float = 0.0) -> None:
    """Module-level convenience for the common single-store case."""
    get_reputation().record(tool, ok, latency_ms=latency_ms)
