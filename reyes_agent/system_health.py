"""One on-demand truth API for ZENO subsystem health.

No polling thread is created. Expensive backends are described from lazy
adapter state and only activated by their real feature path.

WHY THE CHECKS RUN CONCURRENTLY
-------------------------------
Measured on a live ZENO: fifteen sequential checks took **10.65s**, and
`/api/health` -- which the dashboard polls -- timed out. The time was not
one pathological backend but several honest ones adding up: PHASE 5
SERVICES 2.5s, WAKE WORD 2.3s, MCP 2.3s, ADVANCED SERVICES 1.1s.

The checks are independent of each other, so they are gathered in parallel
and each is bounded: one wedged backend now costs its own timeout instead
of the whole snapshot. A brief cache then keeps a polling dashboard from
re-running all fifteen every second.

`force=True` bypasses the cache when a caller genuinely needs this instant.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from reyes_agent.memory.privacy import redact

# Comfortably longer than a build takes. A 4s TTL on a ~5s build is useless:
# it expires while the build is still running, so consecutive callers never
# hit it -- observed directly, two /api/health calls costing 6.3s then 5.1s.
CACHE_TTL_S = 20.0

# A single check may not hold the snapshot longer than this.
CHECK_TIMEOUT_S = 5.0

# Availability reports -- which binaries and packages exist -- change only
# when the owner installs something, so they outlive a health snapshot by a
# long way. Measured: phase3.status() 253ms and phase5.status() 565ms are
# almost entirely `shutil.which` misses at 39ms each.
_AVAILABILITY_TTL_S = 300.0

_cache_lock = threading.Lock()
_build_lock = threading.Lock()
_cached: dict[str, Any] | None = None
_cached_at = 0.0


def snapshot(*, force: bool = False) -> dict[str, Any]:
    """Current subsystem health. Cached; see CACHE_TTL_S.

    Concurrent callers share one build. Without that, every dashboard poll
    that lands while a build is running starts its OWN fifteen checks, and
    the contention makes each of them slower -- a stampede that gets worse
    the more clients are watching.
    """
    global _cached, _cached_at

    def fresh() -> dict[str, Any] | None:
        with _cache_lock:
            if _cached is not None and (time.time() - _cached_at) < CACHE_TTL_S:
                return dict(_cached, cached=True)
        return None

    if not force:
        hit = fresh()
        if hit is not None:
            return hit

    with _build_lock:
        # Someone may have finished building while this caller waited.
        if not force:
            hit = fresh()
            if hit is not None:
                return hit
        result = _build()
        with _cache_lock:
            _cached, _cached_at = result, time.time()
    return dict(result, cached=False)


def _build() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, operation: Callable[[], tuple[str, str, dict[str, Any] | None]]
              ) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            state, detail, metrics = operation()
        except Exception as exc:
            state, detail, metrics = "DEGRADED", f"{type(exc).__name__}: {redact(exc, limit=240)}", None
        return {"system": name, "status": state, "detail": detail,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                **({"metrics": metrics} if metrics else {})}

    def core():
        from reyes_agent.kernel import get_kernel
        data = get_kernel().diagnostics()
        workers = data.get("workers", {})
        core_services = [item for item in data.get("services", {}).values()
                         if item.get("stage") == 2]
        degraded = [item for item in core_services if item.get("state") == "degraded"]
        pending = [item for item in core_services if item.get("state") in {"registered", "running"}]
        workers_alive = int(workers.get("workers_alive", 0) or 0)
        if not workers_alive or data.get("shutting_down") or degraded:
            state = "DEGRADED"
        elif data.get("stage", 0) < 2 or pending:
            state = "STANDBY"
        else:
            state = "ONLINE"
        return (state,
                f"Stage {data.get('stage')}; workers {workers_alive}; queue {workers.get('queue_depth', 0)}; "
                f"core services {len(core_services) - len(pending) - len(degraded)}/{len(core_services)} ready.",
                {"stage": data.get("stage"), "queue_depth": workers.get("queue_depth", 0),
                 "thread_workers": workers_alive, "core_pending": len(pending),
                 "core_degraded": len(degraded)})

    def voice():
        from reyes_agent import microphone
        data = microphone.runtime_status()
        ready = data.get("status") == "MICROPHONE_READY"
        return ("ONLINE" if ready else "DEGRADED", data.get("detail", data.get("status", "unknown")), data)

    def memory():
        from reyes_agent.memory import get_memory_manager
        data = get_memory_manager().status()
        state = data.get("state", "DEGRADED")
        return state, f"Canonical {data['canonical']} {state}; semantic {data['semantic_backend']['state']}.", data

    def providers():
        from reyes_agent import provider_manager
        data = provider_manager.status()
        raw = data["state"]
        state = "ONLINE" if raw == "ONLINE" else (
            "DEGRADED" if raw in {"FAILED", "RATE_LIMITED"} else "STANDBY"
        )
        return state, (
            f"{data['online_count']}/{data['configured_count']} configured provider(s) "
            "validated online. A key alone is not health evidence."
        ), data

    def environment():
        from reyes_agent.runtime_environment import report
        data = report()
        return data["state"], data["summary"], data

    def identity():
        from reyes_agent.user_profiles import status
        data = status()
        raw = data["state"]
        state = "ONLINE" if raw == "READY" else (
            "STANDBY" if raw == "SETUP_REQUIRED" else "DEGRADED"
        )
        detail = (f"Owner: {data['owner']['display_name']}." if data.get("owner")
                  else "First-run owner setup is required; no sample user was created.")
        return state, detail, data

    def wake():
        from reyes_agent.wake import get_wake_engine
        data = get_wake_engine().status()
        backend = data["backend"]["state"]
        state = "ONLINE" if backend == "READY" else "STANDBY"
        return state, f"Single stream; local model {backend}.", data

    def browser():
        from reyes_agent import browser_controller
        data = browser_controller.health()
        raw = data.get("state", "STANDBY")
        state = raw if raw in {"ONLINE", "DEGRADED", "STANDBY"} else "STANDBY"
        detail = ("Persistent browser context is open." if raw == "ONLINE" else
                  "Playwright is installed and will start on a real browser request."
                  if raw == "STANDBY" else
                  "Browser runtime is unavailable or its last launch failed.")
        return state, detail, data

    def agents():
        from reyes_agent import agent_runtime
        data = agent_runtime.health()
        state = "ONLINE" if data.get("supervisor_alive") else "DEGRADED"
        healthy = data.get("agents_healthy", 0)
        active = data.get("agents_alive", 0)
        return state, f"{healthy}/{data.get('agents_total', 0)} healthy; {active} active on demand.", data

    def mcp():
        from reyes_agent.tools.mcp import get_mcp_manager
        data = get_mcp_manager().status()
        return data["state"], f"{data['healthy']}/{data['enabled']} enabled servers connected.", data

    def coding():
        from reyes_agent.coding_system import get_interpreter_client
        data = get_interpreter_client().status()
        return data["state"], "Open Interpreter is a lazy TOSIN specialist; auto-run is disabled.", data

    def devices():
        from reyes_agent.devices import get_device_manager
        data = get_device_manager().health()
        return data["state"], f"{data['online']}/{data['total']} devices online.", data

    def integrations():
        try:
            from reyes_agent import integrations as phase1
            data = phase1.status()
            bad = [name for name, item in data.items() if item.get("enabled") and not item.get("installed")]
            return ("DEGRADED" if bad else "STANDBY", "Missing enabled adapters: " + ", ".join(bad) if bad else "Phase 1 adapters are lazy.", data)
        except Exception as exc:
            return "DEGRADED", f"Phase 1 integration import failed: {type(exc).__name__}: {exc}", None

    def advanced_services():
        from reyes_agent.capabilities import inventory
        from reyes_agent.phase3 import status

        # 253ms of pure availability probing per call, and it changes only
        # when software is installed. See capabilities/inventory.py.
        data = inventory.probe("phase3.status", status, ttl_s=_AVAILABILITY_TTL_S)
        failed = sum(1 for item in data["services"]
                     if item["state"] == "DEGRADED" and item["enabled"])
        state = data["state"]
        return state, (
            f"{data['enabled']}/{data['total']} enabled; "
            f"{failed} enabled service(s) degraded; no polling."
        ), {"enabled": data["enabled"], "total": data["total"], "degraded": failed,
            "states": {item["key"]: item["state"] for item in data["services"]}}

    def phase5_services():
        from reyes_agent.capabilities import inventory
        from reyes_agent.phase5 import status

        data = inventory.probe("phase5.status", status, ttl_s=_AVAILABILITY_TTL_S)
        working = [item for item in data["integrations"] if item["state"] in {"WORKING", "ONLINE"}]
        return "ONLINE", f"{len(working)}/{data['total']} integrations operational; remaining services are explicitly gated.", {
            "working": len(working), "total": data["total"],
            "states": {item["key"]: item["state"] for item in data["integrations"]},
        }

    operations = (
        ("ZENO CORE", core), ("ENVIRONMENT", environment), ("IDENTITY", identity),
        ("MODEL PROVIDERS", providers), ("VOICE", voice), ("MEMORY", memory), ("WAKE WORD", wake),
        ("VISION/COMPUTER", integrations), ("BROWSER", browser), ("AGENTS", agents),
        ("CODING SPECIALIST", coding), ("MCP", mcp), ("LOCAL WINDOWS DEVICE", devices),
        ("ADVANCED SERVICES", advanced_services), ("PHASE 5 SERVICES", phase5_services),
    )

    # Independent checks, so gather them at once. Results are collected back
    # in declared order -- a dashboard that reorders itself every refresh is
    # unreadable, and the order is part of the report.
    with ThreadPoolExecutor(max_workers=len(operations),
                            thread_name_prefix="zeno-health") as pool:
        futures = [(name, pool.submit(check, name, operation))
                   for name, operation in operations]
        for name, future in futures:
            try:
                checks.append(future.result(timeout=CHECK_TIMEOUT_S))
            except Exception as exc:
                # A check that will not answer is a health finding in itself,
                # not a reason for the whole snapshot to fail.
                checks.append({
                    "system": name, "status": "DEGRADED",
                    "detail": (f"did not answer within {CHECK_TIMEOUT_S:.0f}s "
                               f"({type(exc).__name__})"),
                    "latency_ms": round(CHECK_TIMEOUT_S * 1000, 2)})

    overall = "ONLINE"
    if any(item["status"] in {"FAILED", "ERROR"} for item in checks):
        overall = "DEGRADED"
    elif any(item["status"] == "DEGRADED" for item in checks):
        overall = "DEGRADED"
    try:
        from reyes_agent import performance_monitor
        performance = performance_monitor.snapshot()
    except Exception:
        performance = {}
    try:
        from reyes_agent import intelligence
        active_operations = intelligence.get_runtime_control().active()
    except Exception:
        active_operations = []
    return {"checked_at": time.time(), "overall": overall, "checks": checks,
            "active_operations": active_operations,
            "performance": performance, "polling": False}
