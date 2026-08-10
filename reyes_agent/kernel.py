"""ZENO's single in-process lifecycle authority.

This module deliberately owns orchestration rather than replacing completed
systems.  The worker pool, scheduler, event bus and specialist runtime retain
their existing implementations; the kernel gives them one startup/shutdown
order, one service registry and one diagnostics surface.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from reyes_agent import config


STAGE_INTERFACE = 1
STAGE_CORE = 2
STAGE_LAZY = 3


@dataclass
class Service:
    name: str
    stage: int
    start: Callable[[], Any]
    stop: Callable[[], Any] | None = None
    state: str = "registered"
    started_at: float = 0.0
    error: str = ""


class ZenoKernel:
    """Coordinates bounded runtime services without introducing new pools."""

    def __init__(self) -> None:
        self.started_at = time.time()
        self._lock = threading.RLock()
        self._stage = 0
        self._accepting_tasks = True
        self._shutting_down = False
        self._services: dict[str, Service] = {}
        self._agents: set[str] = set()

    def register_service(self, name: str, *, stage: int, start: Callable[[], Any],
                         stop: Callable[[], Any] | None = None) -> Service:
        """Register once; duplicate callers reuse the first authoritative service."""
        if stage not in {STAGE_INTERFACE, STAGE_CORE, STAGE_LAZY}:
            raise ValueError("Unknown kernel startup stage.")
        with self._lock:
            existing = self._services.get(name)
            if existing is not None:
                return existing
            service = Service(name=name, stage=stage, start=start, stop=stop)
            self._services[name] = service
            return service

    def register_agents(self, agent_ids: list[str]) -> None:
        with self._lock:
            self._agents.update(agent_ids)

    def start_interface(self) -> None:
        """Stage 1: only inexpensive, local primitives needed for responsiveness."""
        with self._lock:
            if self._stage >= STAGE_INTERFACE:
                return
            # Import only: event persistence stays lazy until the first event.
            from reyes_agent import event_bus  # noqa: F401
            from reyes_agent.scheduler import get_scheduler
            from reyes_agent.worker_pool import get_worker_pool

            get_worker_pool().start()
            get_scheduler().start()
            self._stage = STAGE_INTERFACE

    def start_core(self, *, delay: float = 0.0) -> None:
        """Stage 2: schedule registered core services; never wait for them."""
        self.start_interface()
        with self._lock:
            if self._stage >= STAGE_CORE:
                return
            self._stage = STAGE_CORE
            names = [name for name, service in self._services.items() if service.stage == STAGE_CORE]
        for name in names:
            self._schedule_service(name, delay=delay)

    def start_lazy(self, name: str) -> None:
        """Explicitly activate a Stage 3 service only when a feature needs it."""
        self.start_interface()
        with self._lock:
            service = self._services.get(name)
            if service is None or service.stage != STAGE_LAZY:
                raise KeyError(f"No lazy service named '{name}'.")
        self._schedule_service(name)

    def start_service(self, name: str, *, delay: float = 0.0) -> None:
        """Schedule a registered service without exposing scheduler internals."""
        self.start_interface()
        with self._lock:
            if name not in self._services:
                raise KeyError(f"No kernel service named '{name}'.")
        self._schedule_service(name, delay=delay)

    def _schedule_service(self, name: str, *, delay: float = 0.0) -> None:
        from reyes_agent.scheduler import get_scheduler
        from reyes_agent.worker_pool import PRIORITY_BACKGROUND

        def invoke() -> None:
            with self._lock:
                service = self._services.get(name)
                if service is None or service.state in {"running", "ready"} or self._shutting_down:
                    return
                service.state = "running"
            try:
                service.start()
            except Exception as exc:  # service isolation is part of lifecycle safety
                with self._lock:
                    service.state = "degraded"
                    service.error = f"{type(exc).__name__}: {exc}"
            else:
                with self._lock:
                    service.state = "ready"
                    service.started_at = time.time()

        get_scheduler().schedule(f"kernel:{name}", invoke, delay=max(0.0, delay),
                                 priority=PRIORITY_BACKGROUND, timeout=30, replace=False)

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any):
        """Single admission gate for finite background work."""
        self.start_interface()
        with self._lock:
            if not self._accepting_tasks:
                raise RuntimeError("ZENO is shutting down and is not accepting new tasks.")
        from reyes_agent.worker_pool import get_worker_pool
        return get_worker_pool().submit(fn, *args, **kwargs)

    def diagnostics(self) -> dict[str, Any]:
        result: dict[str, Any] = {"stage": self._stage, "accepting_tasks": self._accepting_tasks,
                                  "shutting_down": self._shutting_down,
                                  "uptime_s": round(time.time() - self.started_at, 1)}
        with self._lock:
            result["services"] = {name: {"stage": service.stage, "state": service.state,
                                           "error": service.error, "started_at": service.started_at}
                                  for name, service in self._services.items()}
            result["registered_agents"] = sorted(self._agents)
        try:
            from reyes_agent.worker_pool import get_worker_pool
            result["workers"] = get_worker_pool().metrics()
        except Exception:
            result["workers"] = {}
        try:
            from reyes_agent.scheduler import get_scheduler
            result["scheduler"] = get_scheduler().metrics()
        except Exception:
            result["scheduler"] = {}
        return result

    def shutdown(self, *, event_flush_timeout: float = 2.0) -> dict[str, Any]:
        """Run the one ordered shutdown path; safe to call more than once."""
        with self._lock:
            if self._shutting_down:
                return {"already_stopping": True}
            self._shutting_down = True
            self._accepting_tasks = False
            services = list(self._services.values())

        # Stop new/periodic work first, then request cancellation of existing work.
        try:
            from reyes_agent.scheduler import shutdown_global_scheduler
            shutdown_global_scheduler()
        except Exception:
            pass
        for service in reversed(services):
            if service.stop is not None:
                try:
                    service.stop()
                except Exception:
                    pass
        try:
            from reyes_agent import session_recovery
            session_recovery.mark_clean_exit()
        except Exception:
            pass
        try:
            from reyes_agent import agent_runtime
            agent_runtime.shutdown()
        except Exception:
            pass
        try:
            from reyes_agent.browser_runtime import shutdown_global_browser_runtime
            shutdown_global_browser_runtime()
        except Exception:
            pass
        try:
            # Preview servers and any build subprocess are children of this
            # process. Stopping them here is what keeps a closed ZENO from
            # leaving a port bound; the FILES it wrote stay on disk, which
            # is the whole point of writing them to the Desktop.
            from reyes_agent import task_engine
            task_engine.shutdown_all()
        except Exception:
            pass
        try:
            # Website Studio build/install jobs are subprocesses of this
            # process. Stopping them here is what prevents a closed ZENO
            # leaving an `npm install` running against a project folder.
            from reyes_agent.executors import jobs
            jobs.shutdown_all()
        except Exception:
            pass
        try:
            from reyes_agent import voice_manager
            voice_manager.shutdown()
        except Exception:
            pass
        try:
            from reyes_agent.wake import get_wake_engine
            get_wake_engine().stop()
        except Exception:
            pass
        try:
            from reyes_agent.tools.mcp import get_mcp_manager
            get_mcp_manager().shutdown()
        except Exception:
            pass
        try:
            from reyes_agent.devices import get_device_manager
            get_device_manager().shutdown()
        except Exception:
            pass
        try:
            from reyes_agent import event_bus
            event_bus.flush(event_flush_timeout)
            event_bus.shutdown()
        except Exception:
            pass
        try:
            from reyes_agent.worker_pool import shutdown_global_pool
            shutdown_global_pool()
        except Exception:
            pass
        return {"stopped": True}


_kernel: ZenoKernel | None = None
_kernel_lock = threading.Lock()


def get_kernel() -> ZenoKernel:
    global _kernel
    if _kernel is None:
        with _kernel_lock:
            if _kernel is None:
                _kernel = ZenoKernel()
    return _kernel
