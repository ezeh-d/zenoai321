"""Bounded reusable background execution for ZENO.

The desktop/server process used to create a daemon thread for each chat,
heartbeat check, campaign and polling service.  This module is the shared
execution boundary for finite work: a small fixed set of workers, a bounded
priority queue, cooperative cancellation, deadlines, retries, progress and
observable metrics.

Python cannot safely kill a thread that is blocked inside a third-party SDK.
Deadlines therefore reject work before it starts and expose a cancellation
token while it is running; network/browser callers must also configure their
own I/O timeouts.  That is deliberate and honest -- pretending a Future
timeout stopped the underlying operation is a common source of leaked work.
"""

from __future__ import annotations

import itertools
import os
import queue
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar


T = TypeVar("T")
_task_local = threading.local()

# Lower number means more urgent.  These are shared across subsystems so voice
# and the live executive turn cannot be starved by indexing/maintenance.
PRIORITY_VOICE = 0
PRIORITY_BRAIN = 10
PRIORITY_MISSION = 20
PRIORITY_AGENT = 30
PRIORITY_BACKGROUND = 50
PRIORITY_MAINTENANCE = 80

PENDING = "pending"
RUNNING = "running"
RETRYING = "retrying"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"
TIMED_OUT = "timed_out"
TERMINAL_STATES = frozenset({COMPLETED, FAILED, CANCELLED, TIMED_OUT})


class WorkerPoolError(RuntimeError):
    """Base error raised by the managed runtime."""


class QueueFullError(WorkerPoolError):
    """The bounded queue has no capacity for more work."""


class TaskCancelled(WorkerPoolError):
    """A task observed its cooperative cancellation token."""


class TaskDeadlineExceeded(TimeoutError, WorkerPoolError):
    """A task missed its configured deadline."""


class TaskHandle(Generic[T]):
    """Thread-safe result, cancellation and progress handle."""

    def __init__(
        self,
        *,
        name: str,
        priority: int,
        timeout: float | None,
        progress: Callable[[dict[str, Any]], None] | None,
    ) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.name = name
        self.priority = int(priority)
        self.submitted_at = time.monotonic()
        self.deadline = self.submitted_at + timeout if timeout and timeout > 0 else None
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.attempts = 0
        self.state = PENDING

        self._result: T | None = None
        self._exception: BaseException | None = None
        self._done = threading.Event()
        self._cancel = threading.Event()
        self._progress = progress
        self._lock = threading.Lock()
        self._last_progress: dict[str, Any] = {}

    @property
    def done(self) -> bool:
        return self._done.is_set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def exception(self) -> BaseException | None:
        return self._exception

    def cancel(self) -> bool:
        """Request cancellation. Running functions must observe the token."""
        if self.done:
            return False
        self._cancel.set()
        return True

    def wait(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout)

    def result(self, timeout: float | None = None) -> T:
        if not self._done.wait(timeout):
            raise TimeoutError(f"Task '{self.name}' did not finish within {timeout}s.")
        if self._exception is not None:
            raise self._exception
        return self._result  # type: ignore[return-value]

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            run_ms = (
                round(((self.finished_at or now) - self.started_at) * 1000, 1)
                if self.started_at else 0.0
            )
            return {
                "id": self.id,
                "name": self.name,
                "priority": self.priority,
                "state": self.state,
                "attempts": self.attempts,
                "queued_ms": round(((self.started_at or now) - self.submitted_at) * 1000, 1),
                "run_ms": run_ms,
                "cancel_requested": self.cancelled,
                "progress": dict(self._last_progress),
            }

    def _set_progress(self, update: dict[str, Any]) -> None:
        with self._lock:
            self._last_progress = dict(update)
        if self._progress is not None:
            try:
                self._progress(dict(update))
            except Exception:  # noqa: BLE001 -- observers cannot break work
                pass

    def _finish(self, state: str, *, result: T | None = None,
                exception: BaseException | None = None) -> None:
        with self._lock:
            if self._done.is_set():
                return
            self.state = state
            self._result = result
            self._exception = exception
            self.finished_at = time.monotonic()
            self._done.set()


class TaskContext:
    """Passed to context-aware jobs for cancellation/progress checks."""

    def __init__(self, handle: TaskHandle[Any]) -> None:
        self.handle = handle

    @property
    def cancelled(self) -> bool:
        return self.handle.cancelled

    @property
    def remaining(self) -> float | None:
        if self.handle.deadline is None:
            return None
        return max(0.0, self.handle.deadline - time.monotonic())

    def check_cancelled(self) -> None:
        if self.handle.cancelled:
            raise TaskCancelled(f"Task '{self.handle.name}' was cancelled.")
        if self.handle.deadline is not None and time.monotonic() >= self.handle.deadline:
            self.handle._cancel.set()
            raise TaskDeadlineExceeded(f"Task '{self.handle.name}' exceeded its deadline.")

    def progress(self, stage: str, **details: Any) -> None:
        self.check_cancelled()
        self.handle._set_progress({"stage": stage, **details, "at": time.time()})

    def wait(self, seconds: float) -> None:
        """Cancellation-aware replacement for retry/backoff sleeps."""
        if self.handle._cancel.wait(max(0.0, seconds)):
            self.check_cancelled()
        self.check_cancelled()


def current_task_context() -> TaskContext | None:
    """Return the managed-task context for this worker thread, if any.

    Nested runtimes use this to pass cancellation from a parent task to a
    dedicated worker without making the GUI or request thread wait blindly.
    """
    return getattr(_task_local, "context", None)


@dataclass(order=True)
class _QueueItem:
    priority: int
    sequence: int
    job: "_Job[Any] | None" = field(compare=False)


@dataclass
class _Job(Generic[T]):
    handle: TaskHandle[T]
    fn: Callable[..., T]
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    retries: int
    retry_backoff: float
    with_context: bool


class ManagedWorkerPool:
    """Fixed workers consuming a bounded priority queue."""

    def __init__(self, max_workers: int | None = None, max_queue: int | None = None,
                 thread_name_prefix: str = "zeno-worker") -> None:
        cpu = os.cpu_count() or 2
        configured_workers = int(os.environ.get("ZENO_WORKERS", "0") or 0)
        configured_queue = int(os.environ.get("ZENO_WORK_QUEUE", "0") or 0)
        self.max_workers = max(1, max_workers or configured_workers or min(6, max(2, cpu)))
        self.max_queue = max(1, max_queue or configured_queue or 128)
        self.thread_name_prefix = thread_name_prefix
        self._queue: queue.PriorityQueue[_QueueItem] = queue.PriorityQueue(self.max_queue)
        self._sequence = itertools.count()
        self._threads: list[threading.Thread] = []
        self._shutdown = threading.Event()
        self._start_lock = threading.Lock()
        self._metrics_lock = threading.Lock()
        self._active: dict[str, TaskHandle[Any]] = {}
        self._recent: deque[TaskHandle[Any]] = deque(maxlen=100)
        self._submitted = 0
        self._completed = 0
        self._failed = 0
        self._cancelled = 0
        self._timed_out = 0
        self._retries = 0
        self._total_duration = 0.0

    def start(self) -> None:
        if self._threads:
            return
        with self._start_lock:
            if self._threads:
                return
            if self._shutdown.is_set():
                raise WorkerPoolError("Worker pool has been shut down.")
            for index in range(self.max_workers):
                thread = threading.Thread(
                    target=self._worker,
                    name=f"{self.thread_name_prefix}-{index + 1}",
                    daemon=True,
                )
                thread.start()
                self._threads.append(thread)

    def submit(
        self,
        fn: Callable[..., T],
        *args: Any,
        name: str | None = None,
        priority: int = PRIORITY_BACKGROUND,
        timeout: float | None = None,
        retries: int = 0,
        retry_backoff: float = 0.25,
        progress: Callable[[dict[str, Any]], None] | None = None,
        with_context: bool = False,
        **kwargs: Any,
    ) -> TaskHandle[T]:
        self.start()
        handle: TaskHandle[T] = TaskHandle(
            name=name or getattr(fn, "__name__", "background-task"),
            priority=priority,
            timeout=timeout,
            progress=progress,
        )
        job = _Job(
            handle=handle,
            fn=fn,
            args=args,
            kwargs=kwargs,
            retries=max(0, int(retries)),
            retry_backoff=max(0.0, float(retry_backoff)),
            with_context=with_context,
        )
        try:
            self._queue.put_nowait(_QueueItem(int(priority), next(self._sequence), job))
        except queue.Full as exc:
            raise QueueFullError(
                f"Worker queue is full ({self.max_queue} pending tasks); '{handle.name}' was rejected."
            ) from exc
        with self._metrics_lock:
            self._submitted += 1
        return handle

    def _worker(self) -> None:
        while not self._shutdown.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if item.job is None:
                    return
                self._execute(item.job)
            finally:
                self._queue.task_done()

    def _execute(self, job: _Job[T]) -> None:
        handle = job.handle
        context = TaskContext(handle)
        if handle.cancelled:
            self._finish(handle, CANCELLED, exception=TaskCancelled(
                f"Task '{handle.name}' was cancelled before it started."
            ))
            return
        if handle.deadline is not None and time.monotonic() >= handle.deadline:
            self._finish(handle, TIMED_OUT, exception=TaskDeadlineExceeded(
                f"Task '{handle.name}' expired in the queue."
            ))
            return

        handle.started_at = time.monotonic()
        handle.state = RUNNING
        with self._metrics_lock:
            self._active[handle.id] = handle

        _task_local.context = context
        try:
            for attempt in range(job.retries + 1):
                handle.attempts = attempt + 1
                try:
                    context.check_cancelled()
                    result = (
                        job.fn(context, *job.args, **job.kwargs)
                        if job.with_context
                        else job.fn(*job.args, **job.kwargs)
                    )
                    context.check_cancelled()
                    self._finish(handle, COMPLETED, result=result)
                    return
                except TaskDeadlineExceeded as exc:
                    self._finish(handle, TIMED_OUT, exception=exc)
                    return
                except TaskCancelled as exc:
                    self._finish(handle, CANCELLED, exception=exc)
                    return
                except BaseException as exc:  # noqa: BLE001 -- task failure is isolated
                    if attempt >= job.retries or handle.cancelled:
                        state = CANCELLED if handle.cancelled else FAILED
                        final_exc: BaseException = (
                            TaskCancelled(f"Task '{handle.name}' was cancelled.")
                            if state == CANCELLED else exc
                        )
                        self._finish(handle, state, exception=final_exc)
                        return
                    handle.state = RETRYING
                    with self._metrics_lock:
                        self._retries += 1
                    try:
                        context.wait(job.retry_backoff * (2 ** attempt))
                    except TaskDeadlineExceeded as deadline_exc:
                        self._finish(handle, TIMED_OUT, exception=deadline_exc)
                        return
                    except TaskCancelled as cancel_exc:
                        self._finish(handle, CANCELLED, exception=cancel_exc)
                        return
                    handle.state = RUNNING
        finally:
            if getattr(_task_local, "context", None) is context:
                del _task_local.context

    def _finish(self, handle: TaskHandle[Any], state: str, *, result: Any = None,
                exception: BaseException | None = None) -> None:
        handle._finish(state, result=result, exception=exception)
        duration = ((handle.finished_at or time.monotonic()) -
                    (handle.started_at or handle.submitted_at))
        with self._metrics_lock:
            self._active.pop(handle.id, None)
            self._recent.append(handle)
            self._total_duration += duration
            if state == COMPLETED:
                self._completed += 1
            elif state == CANCELLED:
                self._cancelled += 1
            elif state == TIMED_OUT:
                self._timed_out += 1
            else:
                self._failed += 1

    def metrics(self) -> dict[str, Any]:
        with self._metrics_lock:
            finished = self._completed + self._failed + self._cancelled + self._timed_out
            # Keep diagnostics useful without leaking exception messages, which
            # may contain provider responses, paths, or credentials.  The
            # bounded deque already limits retained handles; expose only the
            # ten newest unsuccessful task identities and exception classes.
            recent_failures: list[dict[str, Any]] = []
            for handle in reversed(self._recent):
                if handle.state not in {FAILED, TIMED_OUT}:
                    continue
                item = handle.snapshot()
                item["exception_type"] = (
                    type(handle.exception).__name__ if handle.exception is not None else ""
                )
                recent_failures.append(item)
                if len(recent_failures) >= 10:
                    break
            return {
                "workers": self.max_workers,
                "workers_alive": sum(t.is_alive() for t in self._threads),
                "queue_depth": self._queue.qsize(),
                "queue_capacity": self.max_queue,
                "active": len(self._active),
                "active_tasks": [h.snapshot() for h in self._active.values()],
                "submitted": self._submitted,
                "completed": self._completed,
                "failed": self._failed,
                "cancelled": self._cancelled,
                "timed_out": self._timed_out,
                "retries": self._retries,
                "recent_failures": recent_failures,
                "average_duration_ms": round(self._total_duration * 1000 / finished, 1)
                if finished else 0.0,
            }

    def shutdown(self, wait: bool = True, cancel_pending: bool = True) -> None:
        if self._shutdown.is_set():
            return
        self._shutdown.set()
        if cancel_pending:
            while True:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    if item.job is not None:
                        item.job.handle.cancel()
                        self._finish(item.job.handle, CANCELLED, exception=TaskCancelled(
                            f"Task '{item.job.handle.name}' cancelled during shutdown."
                        ))
                finally:
                    self._queue.task_done()
        # Workers use a short queue timeout and observe _shutdown, so sentinels
        # are unnecessary (and cannot deadlock a full bounded queue).
        if wait:
            for thread in self._threads:
                thread.join(timeout=2.0)


_global_pool: ManagedWorkerPool | None = None
_global_lock = threading.Lock()


def get_worker_pool() -> ManagedWorkerPool:
    global _global_pool
    if _global_pool is None:
        with _global_lock:
            if _global_pool is None:
                _global_pool = ManagedWorkerPool()
    return _global_pool


def shutdown_global_pool() -> None:
    global _global_pool
    with _global_lock:
        pool, _global_pool = _global_pool, None
    if pool is not None:
        pool.shutdown(wait=True, cancel_pending=True)
