"""Low-overhead performance measurements, latency telemetry and freeze logs."""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import threading
import time
import traceback
from collections import defaultdict, deque
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import psutil

from reyes_agent import config


FREEZE_THRESHOLD_S = 0.2
_MAX_SAMPLES = 240
_MAX_FREEZE_LOG_BYTES = 2 * 1024 * 1024
_LOG_PATH = config.PROJECT_ROOT / "logs" / "performance" / "freezes.jsonl"
_process = psutil.Process()
_process.cpu_percent(interval=None)  # prime psutil's non-blocking counter
_lock = threading.Lock()
_latencies: dict[str, deque[tuple[float, float]]] = defaultdict(lambda: deque(maxlen=_MAX_SAMPLES))
_memory_samples: deque[tuple[float, int]] = deque(maxlen=_MAX_SAMPLES)
_freezes: deque[dict[str, Any]] = deque(maxlen=100)
_frontend_audits: deque[dict[str, Any]] = deque(maxlen=120)
_last_freeze_at: dict[str, float] = {}
_last_host_incident_at = 0.0


def thread_stack_snapshot(*, limit: int = 32) -> dict[str, Any]:
    """Return a bounded, safe snapshot of every live Python thread.

    This is intentionally diagnostic-only. It does not acquire application
    locks or signal threads, so a hung process can be inspected without
    changing the condition being investigated.
    """
    frames = sys._current_frames()
    threads = []
    for thread in threading.enumerate():
        frame = frames.get(thread.ident)
        threads.append({
            "id": thread.ident,
            "name": thread.name,
            "daemon": thread.daemon,
            "stack": traceback.format_stack(frame, limit=limit) if frame else [],
        })
    return {"pid": os.getpid(), "captured_at": time.time(), "threads": threads}


def record_host_heartbeat(sent_at_s: float, *, active_callback: str = "",
                          bridge_activity: dict[str, Any] | None = None) -> float:
    """Record a heartbeat delivered through the real WebView bridge.

    The timestamp is set in the renderer. A late arrival proves that either
    the WebView/WinForms message path or its bridge dispatch was delayed.
    Stack capture is rate-limited and runs on the callback worker, never the
    WinForms message-loop itself.
    """
    global _last_host_incident_at
    delay = max(0.0, time.time() - float(sent_at_s))
    if delay >= 0.5 and time.time() - _last_host_incident_at >= 5.0:
        _last_host_incident_at = time.time()
        record_freeze(delay, subsystem="desktop_webview_bridge", source="host-heartbeat", details={
            "capture_stacks": True,
            "host_pid": os.getpid(),
            "host_thread": threading.get_ident(),
            "active_callback": active_callback,
            "bridge_activity": bridge_activity or {},
        })
    return delay


def record_latency(subsystem: str, seconds: float) -> None:
    if seconds < 0:
        return
    now = time.time()
    with _lock:
        _latencies[subsystem].append((now, seconds))


@contextmanager
def measure(subsystem: str) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        record_latency(subsystem, time.perf_counter() - started)


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * fraction))]


def _latency_snapshot() -> dict[str, Any]:
    with _lock:
        samples = {name: list(values) for name, values in _latencies.items()}
    return {
        name: {
            "count": len(values),
            "avg_ms": round(statistics.fmean(value for _, value in values) * 1000, 1) if values else 0.0,
            "p50_ms": round(_percentile([value for _, value in values], 0.50) * 1000, 1),
            "p95_ms": round(_percentile([value for _, value in values], 0.95) * 1000, 1),
        }
        for name, values in samples.items()
    }


def _memory_trend() -> dict[str, Any]:
    with _lock:
        values = list(_memory_samples)
    if len(values) < 2:
        return {"samples": len(values), "growth_mb_per_hour": 0.0, "warning": False}
    first_t, first_rss = values[0]
    last_t, last_rss = values[-1]
    elapsed = max(0.001, last_t - first_t)
    growth_per_hour = (last_rss - first_rss) / 1024 / 1024 / elapsed * 3600
    return {
        "samples": len(values),
        "growth_mb_per_hour": round(growth_per_hour, 2),
        # A trend is a warning, not a fabricated leak diagnosis. A release
        # soak test provides the evidence needed to classify it as a leak.
        "warning": len(values) >= 12 and growth_per_hour > 100,
    }


def snapshot() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    rss = _process.memory_info().rss
    now = time.time()
    with _lock:
        _memory_samples.append((now, rss))
        recent_freezes = list(_freezes)[-10:]
        recent_frontend_audits = list(_frontend_audits)[-12:]

    workers: dict[str, Any] = {}
    browser_workers: dict[str, Any] = {}
    scheduler: dict[str, Any] = {}
    agents: dict[str, Any] = {}
    events: dict[str, Any] = {}
    browser: dict[str, Any] = {"available": False}
    try:
        from reyes_agent.worker_pool import get_worker_pool

        workers = get_worker_pool().metrics()
    except Exception:  # noqa: BLE001
        pass
    if "reyes_agent.browser_runtime" in sys.modules:
        try:
            from reyes_agent.browser_runtime import get_browser_runtime

            browser_workers = get_browser_runtime().metrics()
        except Exception:  # noqa: BLE001
            pass
    try:
        from reyes_agent.scheduler import get_scheduler

        scheduler = get_scheduler().metrics()
    except Exception:  # noqa: BLE001
        pass
    # Do not import optional subsystems merely to render diagnostics.
    if "reyes_agent.agent_runtime" in sys.modules:
        try:
            from reyes_agent import agent_runtime

            agents = agent_runtime.health()
        except Exception:  # noqa: BLE001
            pass
    if "reyes_agent.event_bus" in sys.modules:
        try:
            from reyes_agent import event_bus

            events = event_bus.runtime_stats()
        except Exception:  # noqa: BLE001
            pass
    if "reyes_agent.browser_controller" in sys.modules:
        try:
            from reyes_agent import browser_controller

            browser = browser_controller.health()
        except Exception:  # noqa: BLE001
            pass

    return {
        "cpu_percent": round(_process.cpu_percent(interval=None), 1),
        "system_cpu_percent": round(psutil.cpu_percent(interval=None), 1),
        "rss_mb": round(rss / 1024 / 1024, 1),
        "system_ram_percent": round(vm.percent, 1),
        "system_ram_used_mb": round(vm.used / 1024 / 1024, 1),
        "threads": _process.num_threads(),
        "gpu": {"available": False, "reason": "no supported local GPU telemetry provider configured"},
        "workers": workers,
        "browser_workers": browser_workers,
        "scheduler": scheduler,
        "agents": agents,
        "events": events,
        "browser": browser,
        "latencies": _latency_snapshot(),
        "memory_trend": _memory_trend(),
        "freeze_count": len(recent_freezes),
        "recent_freezes": recent_freezes,
        "frontend_audits": recent_frontend_audits,
    }


def record_frontend_audit(report: dict[str, Any]) -> None:
    """Keep bounded renderer measurements from an explicit audit session."""
    record = {"timestamp": time.time(), **report}
    with _lock:
        _frontend_audits.append(record)


def record_freeze(
    duration_s: float,
    *,
    subsystem: str,
    source: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Record an observed >200 ms stall with the information we can prove."""
    if duration_s < FREEZE_THRESHOLD_S:
        return None
    now = time.time()
    with _lock:
        # Coalesce duplicate reports from a single stalled interval.
        if now - _last_freeze_at.get(source, 0.0) < 0.5:
            return None
        _last_freeze_at[source] = now

    # Capturing and formatting every Python thread's stack can itself take
    # hundreds of milliseconds with the agent runtime alive.  This function
    # is called by the event-loop watchdog, so doing that work here turned a
    # detected stall into another real stall.  Keep hot-path records cheap;
    # an explicit diagnostic caller may opt into stack capture.
    stacks: dict[str, list[str]] = {}
    main_stack: list[str] = []
    if details and details.get("capture_stacks"):
        frames = sys._current_frames()
        for thread in threading.enumerate():
            frame = frames.get(thread.ident)
            if frame is not None:
                stacks[thread.name] = traceback.format_stack(frame, limit=20)
        main_stack = stacks.get("MainThread", [])
    record = {
        "timestamp": now,
        "timestamp_human": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "duration_ms": round(duration_s * 1000, 1),
        "subsystem": subsystem,
        "source": source,
        "cpu_percent": round(_process.cpu_percent(interval=None), 1),
        "rss_mb": round(_process.memory_info().rss / 1024 / 1024, 1),
        "threads": _process.num_threads(),
        "function": main_stack[-1].strip() if main_stack else "unavailable",
        "call_stack": main_stack,
        "thread_stacks": stacks,
        "details": details or {},
    }
    with _lock:
        _freezes.append(record)
    _write_freeze(record)
    return record


def _write_freeze(record: dict[str, Any]) -> None:
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if _LOG_PATH.exists() and _LOG_PATH.stat().st_size > _MAX_FREEZE_LOG_BYTES:
            rotated = _LOG_PATH.with_name(f"freezes-{int(time.time())}.jsonl")
            _LOG_PATH.replace(rotated)
        with _LOG_PATH.open("a", encoding="utf-8") as log:
            log.write(json.dumps(record, default=str) + "\n")
    except OSError:
        pass


async def event_loop_probe(stop_event: asyncio.Event) -> None:
    """Detect Starlette/uvicorn event-loop stalls without polling the UI."""
    interval = 0.05
    expected = time.perf_counter() + interval
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except TimeoutError:
            pass
        now = time.perf_counter()
        lag = max(0.0, now - expected)
        if lag >= FREEZE_THRESHOLD_S:
            record_freeze(lag, subsystem="server_event_loop", source="event-loop")
        expected = now + interval
