"""The single, low-cost runtime for ZENO proactive checks.

The scheduler only calls :meth:`HeartbeatEngine.tick`; individual finite checks
run through the existing managed worker pool.  No language-model polling or
second scheduler lives here.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from reyes_agent.proactive_models import CheckResult, Importance, ScheduledCheck
from reyes_agent.proactive_store import ProactiveStore
from reyes_agent.scheduler import get_scheduler
from reyes_agent.worker_pool import PRIORITY_BACKGROUND, get_worker_pool


@dataclass(frozen=True)
class CheckContext:
    """Small, trusted context supplied to a registered deterministic check."""

    check: ScheduledCheck
    started_at: float
    event_type: str = ""
    event_facts: Mapping[str, Any] = field(default_factory=dict)


CheckHandler = Callable[[CheckContext], CheckResult]


class HeartbeatEngine:
    """Register, schedule and isolate typed proactive checks.

    Handlers are registered in-process code, not user-supplied instructions.
    The active-check set prevents overlap even if an interval expires before a
    previous worker task has completed.
    """

    def __init__(
        self,
        store: ProactiveStore,
        *,
        worker_pool: Any | None = None,
        scheduler: Any | None = None,
        clock: Callable[[], float] = time.time,
        tick_interval_s: int = 30,
        job_name: str = "heartbeat",
    ) -> None:
        if tick_interval_s < 5:
            raise ValueError("heartbeat tick interval must be at least five seconds")
        self.store = store
        self._worker_pool = worker_pool or get_worker_pool()
        self._scheduler = scheduler or get_scheduler()
        self._clock = clock
        self._tick_interval_s = tick_interval_s
        self._job_name = job_name
        self._handlers: dict[str, CheckHandler] = {}
        self._active: set[str] = set()
        self._lock = threading.RLock()
        self._paused_reason = ""
        self._running = False
        self._skipped_overlap = 0
        self._failures: list[dict[str, str]] = []

    def register(self, check: ScheduledCheck, handler: CheckHandler) -> ScheduledCheck:
        """Register a trusted handler and preserve any persisted run history."""
        if not callable(handler):
            raise TypeError("heartbeat check handler must be callable")
        with self._lock:
            self._handlers[check.id] = handler
        return self.store.upsert_check(check)

    def unregister(self, check_id: str) -> None:
        with self._lock:
            self._handlers.pop(check_id, None)

    def start(self) -> None:
        """Schedule the one shared ticker through ZENO's scheduler."""
        with self._lock:
            if self._running:
                return
            self._running = True
        self._scheduler.schedule(
            self._job_name,
            self.tick,
            delay=0.0,
            interval=self._tick_interval_s,
            priority=PRIORITY_BACKGROUND,
            replace=False,
        )

    def stop(self) -> None:
        with self._lock:
            self._running = False
        self._scheduler.cancel(self._job_name)

    def pause(self, reason: str = "manual") -> None:
        with self._lock:
            self._paused_reason = " ".join(str(reason or "manual").split())[:120]

    def resume(self) -> None:
        with self._lock:
            self._paused_reason = ""

    def tick(self, *, now: float | None = None) -> list[str]:
        """Submit due checks and return their ids without blocking the UI."""
        now = self._clock() if now is None else float(now)
        with self._lock:
            if self._paused_reason:
                return []
        submitted: list[str] = []
        for check in self.store.load_checks():
            if check.next_due_at > now:
                continue
            if not self._reserve(check.id):
                continue
            claimed = self.store.claim_due(check.id, now=now)
            if claimed is None:
                self._release(check.id)
                continue
            handler = self._handler_for(claimed.id)
            if handler is None:
                self._release(claimed.id)
                continue
            try:
                self._worker_pool.submit(
                    self._run_claimed,
                    claimed,
                    handler,
                    now,
                    "",
                    {},
                    name=f"heartbeat:{claimed.id}",
                    priority=claimed.priority or PRIORITY_BACKGROUND,
                    timeout=claimed.timeout_s,
                )
            except BaseException as exc:  # queue rejection is a failed, isolated check
                self.store.record_check_failure(claimed.id, now=now)
                self._record_failure(claimed.id, exc)
                self._release(claimed.id)
                continue
            submitted.append(claimed.id)
        return submitted

    def trigger_event(
        self, event_type: str, facts: Mapping[str, Any] | None = None, *, now: float | None = None
    ) -> list[str]:
        """Run matching registered checks once for a trusted system event."""
        now = self._clock() if now is None else float(now)
        with self._lock:
            if self._paused_reason:
                return []
        submitted: list[str] = []
        for check in self.store.load_checks():
            if event_type not in check.event_types or not self._reserve(check.id):
                continue
            claimed = self.store.claim_event(check.id, now=now)
            handler = self._handler_for(check.id)
            if claimed is None or handler is None:
                self._release(check.id)
                continue
            try:
                self._worker_pool.submit(
                    self._run_claimed, claimed, handler, now, event_type, dict(facts or {}),
                    name=f"heartbeat:{claimed.id}", priority=claimed.priority or PRIORITY_BACKGROUND,
                    timeout=claimed.timeout_s,
                )
            except BaseException as exc:
                self.store.record_check_failure(claimed.id, now=now)
                self._record_failure(claimed.id, exc)
                self._release(claimed.id)
                continue
            submitted.append(claimed.id)
        return submitted

    def _reserve(self, check_id: str) -> bool:
        with self._lock:
            if check_id in self._active:
                self._skipped_overlap += 1
                return False
            self._active.add(check_id)
            return True

    def _release(self, check_id: str) -> None:
        with self._lock:
            self._active.discard(check_id)

    def _handler_for(self, check_id: str) -> CheckHandler | None:
        with self._lock:
            return self._handlers.get(check_id)

    def _run_claimed(
        self,
        check: ScheduledCheck,
        handler: CheckHandler,
        started_at: float,
        event_type: str,
        event_facts: Mapping[str, Any],
    ) -> None:
        try:
            result = handler(CheckContext(check, started_at, event_type, event_facts))
            if not isinstance(result, CheckResult):
                raise TypeError("heartbeat handlers must return CheckResult")
            self.store.record_check_success(check.id, result, now=started_at)
            if result.changed:
                self.store.upsert_notice(
                    result,
                    importance=result.importance_hint or Importance.INBOX,
                )
        except BaseException as exc:  # each check must fail independently
            self.store.record_check_failure(check.id, now=started_at)
            self._record_failure(check.id, exc)
        finally:
            self._release(check.id)

    def _record_failure(self, check_id: str, exc: BaseException) -> None:
        with self._lock:
            self._failures.append({"check_id": check_id, "error": type(exc).__name__})
            del self._failures[:-20]

    def diagnostics(self) -> dict[str, Any]:
        with self._lock:
            return {
                **self.store.diagnostics(),
                "running": self._running,
                "paused": bool(self._paused_reason),
                "paused_reason": self._paused_reason,
                "registered_checks": len(self._handlers),
                "active_checks": sorted(self._active),
                "skipped_overlap": self._skipped_overlap,
                "recent_failures": list(self._failures),
            }
