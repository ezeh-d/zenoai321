"""Single-owner runtime for synchronous Playwright objects.

Playwright's sync API is bound to the OS thread that created it.  ZENO's
general worker pool deliberately reuses *different* workers, so a persistent
browser context must never be passed through that pool directly.  This module
serializes all browser operations through one bounded worker while keeping the
web/GUI threads free.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

from reyes_agent.performance_monitor import measure
from reyes_agent.worker_pool import (
    PRIORITY_MISSION,
    ManagedWorkerPool,
    TaskCancelled,
    TaskContext,
    current_task_context,
)


T = TypeVar("T")


class BrowserRuntime:
    """A small, cancellable queue whose one worker owns Playwright."""

    def __init__(self) -> None:
        self._pool = ManagedWorkerPool(
            max_workers=1, max_queue=16, thread_name_prefix="zeno-browser",
        )

    def run(self, name: str, action: Callable[[], T], *, timeout: float = 50.0) -> T:
        """Run a complete Playwright action on its owning worker.

        Parent task cancellation is checked while waiting.  A synchronous
        Playwright call itself remains cooperative: its navigation/element
        timeout is the hard boundary, after which this worker can accept the
        next action.
        """
        parent = current_task_context()

        def invoke(context: TaskContext) -> T:
            context.progress("browser_action", operation=name)
            with measure("browser_action"):
                context.check_cancelled()
                result = action()
                context.check_cancelled()
                return result

        # Normal browser operations use multi-second timeouts, but honoring a
        # short caller deadline is important for cancellation, tests and a
        # quick UI recovery path.  Keep a tiny floor only to avoid a busy loop.
        timeout = max(0.05, float(timeout))
        handle = self._pool.submit(
            invoke, name=name, priority=PRIORITY_MISSION,
            timeout=timeout, with_context=True,
        )
        deadline = time.monotonic() + timeout
        while not handle.wait(0.05):
            if parent is not None:
                try:
                    parent.check_cancelled()
                except (TaskCancelled, TimeoutError):
                    handle.cancel()
                    raise
            # Worker-pool deadlines are cooperative.  This independent wait
            # boundary ensures a malformed/non-Playwright action cannot make
            # the caller (and therefore a request/UI update) wait forever.
            if time.monotonic() >= deadline:
                handle.cancel()
                raise TimeoutError(f"Browser action '{name}' exceeded {timeout:.1f}s.")
        return handle.result()

    def close_if_idle(self, max_idle_seconds: float = 1800.0) -> bool:
        from reyes_agent import browser_controller as controller

        if not controller.is_open():
            return False
        return self.run(
            "browser_idle_close",
            lambda: controller.close_if_idle(max_idle_seconds), timeout=10.0,
        )

    def shutdown(self) -> None:
        # The sync Playwright context is thread-affine.  Closing it from this
        # caller's thread can hang or leak Chromium, so queue its close on the
        # one worker that owns it before stopping that worker.
        try:
            from reyes_agent import browser_controller as controller

            if controller.is_open():
                close_handle = self._pool.submit(
                    controller.close_browser, name="browser_shutdown_close",
                    priority=PRIORITY_MISSION, timeout=10.0,
                )
                close_handle.result(12.0)
        except Exception:  # shutdown remains best-effort; worker stop follows
            pass
        finally:
            self._pool.shutdown(wait=True, cancel_pending=True)

    def metrics(self) -> dict[str, Any]:
        return self._pool.metrics()


_runtime: BrowserRuntime | None = None
_lock = threading.Lock()


def get_browser_runtime() -> BrowserRuntime:
    global _runtime
    if _runtime is None:
        with _lock:
            if _runtime is None:
                _runtime = BrowserRuntime()
    return _runtime


def shutdown_global_browser_runtime() -> None:
    global _runtime
    with _lock:
        runtime, _runtime = _runtime, None
    if runtime is not None:
        runtime.shutdown()
