"""Bounded, self-invalidating cache of the parsed screen.

Parsing costs ~0.2-0.9s. Doing it for every step of a multi-step GUI task
would dominate the task's runtime, so a parse is reused briefly -- but a
stale scene is worse than a slow one, because the controller would click
where a button USED to be.

So the cache invalidates on any of: age, a different foreground window, or
an explicit `invalidate()` after an action that changes the GUI.
"""

from __future__ import annotations

import threading
import time

from reyes_agent.vision import parser
from reyes_agent.vision.elements import Scene

TTL_S = 2.5          # long enough to chain observe->act, short enough to stay true

_lock = threading.Lock()
_scene: Scene | None = None
_at = 0.0
_handle = 0
_hits = 0
_misses = 0


def current(*, force: bool = False, handle: int = 0) -> Scene:
    """The current scene, parsed or reused."""
    global _scene, _at, _handle, _hits, _misses
    target = handle or parser.foreground_handle()
    with _lock:
        fresh = (_scene is not None and not force
                 and target == _handle
                 and (time.time() - _at) < TTL_S)
        if fresh:
            _hits += 1
            return _scene
        _misses += 1

    scene = parser.parse(target)
    with _lock:
        _scene = scene
        _at = time.time()
        _handle = target
    return scene


def invalidate() -> None:
    """Call after ANY action that could change the GUI."""
    global _scene, _at
    with _lock:
        _scene = None
        _at = 0.0


def stats() -> dict:
    with _lock:
        return {"cached": _scene is not None, "age_s": round(time.time() - _at, 2) if _at else None,
                "hits": _hits, "misses": _misses, "ttl_s": TTL_S}


def reset() -> None:
    global _scene, _at, _handle, _hits, _misses
    with _lock:
        _scene, _at, _handle, _hits, _misses = None, 0.0, 0, 0, 0
