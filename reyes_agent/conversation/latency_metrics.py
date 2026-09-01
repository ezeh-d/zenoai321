"""Latency observability for the conversation pipeline.

Records the real elapsed time of each stage of a turn and reports p50/p95/p99 --
so ZENO is tuned on distributions, not one lucky run, and never on faked
numbers. This measures; it does not promise "<1ms AI". Pure, in-memory,
thread-safe, bounded.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Any

# The stages worth watching, from the brief.
STAGES = (
    "wake", "vad_start", "vad_end", "partial_stt", "final_stt", "intent",
    "tool_start", "first_ui", "llm_ttft", "tts_ttfb", "first_audio", "full_task",
)
_WINDOW = 500


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


class LatencyRecorder:
    def __init__(self, window: int = _WINDOW) -> None:
        self._samples: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=window))
        self._lock = threading.Lock()

    def record(self, stage: str, ms: float) -> None:
        """Record a stage's latency in milliseconds. Silently ignores junk so
        instrumentation never breaks a turn."""
        try:
            value = float(ms)
            if value < 0 or value != value:      # negative or NaN
                return
            with self._lock:
                self._samples[str(stage)].append(value)
        except (TypeError, ValueError):
            return

    def timer(self, stage: str) -> "_Timer":
        return _Timer(self, stage)

    def percentiles(self, stage: str) -> dict[str, Any]:
        with self._lock:
            vals = sorted(self._samples.get(stage, ()))
        if not vals:
            return {"stage": stage, "count": 0}
        return {"stage": stage, "count": len(vals),
                "p50": round(_percentile(vals, 0.50), 1),
                "p95": round(_percentile(vals, 0.95), 1),
                "p99": round(_percentile(vals, 0.99), 1),
                "max": round(vals[-1], 1)}

    def report(self) -> dict[str, Any]:
        with self._lock:
            stages = list(self._samples.keys())
        return {"stages": {s: self.percentiles(s) for s in stages
                           if self._samples.get(s)}}

    def reset(self) -> None:
        with self._lock:
            self._samples.clear()


class _Timer:
    """Context manager: `with recorder.timer('intent'): ...` records the span."""

    def __init__(self, recorder: LatencyRecorder, stage: str) -> None:
        self._recorder = recorder
        self._stage = stage
        self._t0 = 0.0

    def __enter__(self) -> "_Timer":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self._recorder.record(self._stage, (time.perf_counter() - self._t0) * 1000.0)


_recorder: LatencyRecorder | None = None
_lock = threading.Lock()


def get_latency_recorder() -> LatencyRecorder:
    global _recorder
    if _recorder is None:
        with _lock:
            if _recorder is None:
                _recorder = LatencyRecorder()
    return _recorder
