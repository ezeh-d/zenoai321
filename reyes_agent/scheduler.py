"""One scheduler for periodic and delayed background jobs.

Periodic services previously each owned a permanent thread and a bespoke
``while True: sleep(...)`` loop.  This scheduler owns one timer thread and
submits finite iterations to the managed worker pool.  Jobs never overlap with
their previous run, which prevents slow network/maintenance cycles from
turning into event storms.
"""

from __future__ import annotations

import heapq
import itertools
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from reyes_agent.worker_pool import (
    PRIORITY_BACKGROUND,
    QueueFullError,
    TaskHandle,
    get_worker_pool,
)


@dataclass(order=True)
class ScheduledJob:
    next_run: float
    sequence: int
    name: str = field(compare=False)
    fn: Callable[[], Any] = field(compare=False)
    interval: float | None = field(compare=False, default=None)
    priority: int = field(compare=False, default=PRIORITY_BACKGROUND)
    timeout: float | None = field(compare=False, default=None)
    retries: int = field(compare=False, default=0)
    handle: TaskHandle[Any] | None = field(compare=False, default=None)
    cancelled: bool = field(compare=False, default=False)
    runs: int = field(compare=False, default=0)
    skipped_overlap: int = field(compare=False, default=0)


class BackgroundScheduler:
    def __init__(self) -> None:
        self._jobs: dict[str, ScheduledJob] = {}
        self._heap: list[ScheduledJob] = []
        self._sequence = itertools.count()
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name="zeno-scheduler", daemon=True
            )
            self._thread.start()

    def schedule(
        self,
        name: str,
        fn: Callable[[], Any],
        *,
        delay: float = 0.0,
        interval: float | None = None,
        priority: int = PRIORITY_BACKGROUND,
        timeout: float | None = None,
        retries: int = 0,
        replace: bool = False,
    ) -> ScheduledJob:
        if interval is not None and interval <= 0:
            raise ValueError("interval must be positive")
        self.start()
        with self._condition:
            existing = self._jobs.get(name)
            if existing is not None and not replace:
                return existing
            if existing is not None:
                existing.cancelled = True
            job = ScheduledJob(
                next_run=time.monotonic() + max(0.0, delay),
                sequence=next(self._sequence),
                name=name,
                fn=fn,
                interval=interval,
                priority=priority,
                timeout=timeout,
                retries=max(0, retries),
            )
            self._jobs[name] = job
            heapq.heappush(self._heap, job)
            self._condition.notify_all()
            return job

    def cancel(self, name: str) -> bool:
        with self._condition:
            job = self._jobs.pop(name, None)
            if job is None:
                return False
            job.cancelled = True
            if job.handle is not None and not job.handle.done:
                job.handle.cancel()
            self._condition.notify_all()
            return True

    def _run(self) -> None:
        pool = get_worker_pool()
        while not self._stop.is_set():
            with self._condition:
                while self._heap and self._heap[0].cancelled:
                    heapq.heappop(self._heap)
                if not self._heap:
                    self._condition.wait(timeout=0.5)
                    continue
                job = self._heap[0]
                wait_for = job.next_run - time.monotonic()
                if wait_for > 0:
                    self._condition.wait(timeout=min(wait_for, 0.5))
                    continue
                heapq.heappop(self._heap)

            if job.cancelled:
                continue

            previous_running = job.handle is not None and not job.handle.done
            if previous_running:
                job.skipped_overlap += 1
            else:
                try:
                    job.handle = pool.submit(
                        job.fn,
                        name=f"scheduled:{job.name}",
                        priority=job.priority,
                        timeout=job.timeout,
                        retries=job.retries,
                    )
                    job.runs += 1
                except QueueFullError:
                    # Backpressure is preferable to spawning another thread.
                    # A periodic job gets another chance shortly.
                    job.next_run = time.monotonic() + 1.0

            with self._condition:
                if job.cancelled:
                    continue
                if job.interval is None:
                    self._jobs.pop(job.name, None)
                    continue
                now = time.monotonic()
                job.next_run = max(job.next_run + job.interval, now + 0.01)
                heapq.heappush(self._heap, job)

    def metrics(self) -> dict[str, Any]:
        with self._condition:
            jobs = list(self._jobs.values())
        now = time.monotonic()
        return {
            "alive": self._thread is not None and self._thread.is_alive(),
            "jobs": len(jobs),
            "scheduled": [
                {
                    "name": job.name,
                    "next_run_s": round(max(0.0, job.next_run - now), 1),
                    "interval_s": job.interval,
                    "running": job.handle is not None and not job.handle.done,
                    "runs": job.runs,
                    "skipped_overlap": job.skipped_overlap,
                }
                for job in jobs
                if not job.cancelled
            ],
        }

    def shutdown(self) -> None:
        self._stop.set()
        with self._condition:
            for job in self._jobs.values():
                job.cancelled = True
                if job.handle is not None and not job.handle.done:
                    job.handle.cancel()
            self._jobs.clear()
            self._heap.clear()
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=2.0)


_global_scheduler: BackgroundScheduler | None = None
_global_lock = threading.Lock()


def get_scheduler() -> BackgroundScheduler:
    global _global_scheduler
    if _global_scheduler is None:
        with _global_lock:
            if _global_scheduler is None:
                _global_scheduler = BackgroundScheduler()
    return _global_scheduler


def shutdown_global_scheduler() -> None:
    global _global_scheduler
    with _global_lock:
        scheduler, _global_scheduler = _global_scheduler, None
    if scheduler is not None:
        scheduler.shutdown()
