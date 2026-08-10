"""One browser session, reused.

ZENO already owns a Playwright session through `browser_runtime`, which
serialises access on a dedicated worker with a real deadline. This module
is a thin accessor over THAT, so a web task never opens a second browser or
races the one already driving the owner's screen.
"""

from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.Lock()
_last_used = 0.0
_tasks = 0


def runtime():
    """The existing browser runtime, or None when it cannot start."""
    try:
        from reyes_agent.browser_runtime import get_global_browser_runtime

        return get_global_browser_runtime()
    except Exception:  # noqa: BLE001 -- browser trouble never breaks the caller
        return None


def run(name: str, action, *, timeout: float = 30.0) -> tuple[bool, Any]:
    """Run one browser action on the shared runtime. (ok, result_or_error).

    Deliberately returns rather than raises: a dead browser is a normal
    outcome for a web task, not an exception for the whole assistant.
    """
    global _last_used, _tasks
    engine = runtime()
    if engine is None:
        return False, "the browser runtime is unavailable"
    with _lock:
        _tasks += 1
        _last_used = time.time()
    try:
        return True, engine.run(name, action, timeout=timeout)
    except TimeoutError:
        return False, f"'{name}' hit its {timeout:.0f}s deadline"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def status() -> dict[str, Any]:
    with _lock:
        return {"shared_runtime": runtime() is not None,
                "tasks_run": _tasks,
                "idle_s": round(time.time() - _last_used, 1) if _last_used else None,
                "note": "One session, owned by browser_runtime. Web tasks never open a second."}
