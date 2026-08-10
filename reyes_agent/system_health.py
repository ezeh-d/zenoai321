"""One on-demand truth API for ZENO subsystem health.

No polling thread is created. Expensive backends are described from lazy
adapter state and only activated by their real feature path.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from reyes_agent.memory.privacy import redact


def snapshot() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, operation: Callable[[], tuple[str, str, dict[str, Any] | None]]) -> None:
        started = time.perf_counter()
        try:
            state, detail, metrics = operation()
        except Exception as exc:
            state, detail, metrics = "DEGRADED", f"{type(exc).__name__}: {redact(exc, limit=240)}", None
        checks.append({"system": name, "status": state, "detail": detail,
                       "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                       **({"metrics": metrics} if metrics else {})})

    def core():
        from reyes_agent.kernel import get_kernel
        data = get_kernel().diagnostics()
        workers = data.get("workers", {})
        healthy = bool(workers.get("workers_alive", 0)) and not data.get("shutting_down")
        return ("ONLINE" if healthy else "DEGRADED",
                f"Stage {data.get('stage')}; workers {workers.get('workers_alive', 0)}; queue {workers.get('queue_depth', 0)}.",
                {"stage": data.get("stage"), "queue_depth": workers.get("queue_depth", 0),
                 "thread_workers": workers.get("workers_alive", 0)})

    def voice():
        from reyes_agent import microphone
        data = microphone.runtime_status()
        ready = data.get("status") == "MICROPHONE_READY"
        return ("ONLINE" if ready else "DEGRADED", data.get("detail", data.get("status", "unknown")), data)

    def memory():
        from reyes_agent.memory import get_memory_manager
        data = get_memory_manager().status()
        return "ONLINE", f"Canonical {data['canonical']}; semantic {data['semantic_backend']['state']}.", data

    def wake():
        from reyes_agent.wake import get_wake_engine
        data = get_wake_engine().status()
        backend = data["backend"]["state"]
        state = "ONLINE" if backend == "READY" else "STANDBY"
        return state, f"Single stream; local model {backend}.", data

    def browser():
        from reyes_agent import browser_controller
        data = browser_controller.health()
        return ("ONLINE" if data.get("available") else "STANDBY", data.get("reason", "Lazy browser controller."), data)

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

    for name, operation in (
        ("ZENO CORE", core), ("VOICE", voice), ("MEMORY", memory), ("WAKE WORD", wake),
        ("VISION/COMPUTER", integrations), ("BROWSER", browser), ("AGENTS", agents),
        ("CODING SPECIALIST", coding), ("MCP", mcp), ("LOCAL WINDOWS DEVICE", devices),
    ):
        check(name, operation)

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
