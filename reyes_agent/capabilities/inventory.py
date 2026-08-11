"""What this machine can actually do -- asked once, remembered.

WHY THIS EXISTS
---------------
Two separate problems turned out to be the same problem.

`/api/health` was slow because fifteen checks each re-probed the machine:
`shutil.which` for every optional binary, `find_spec` for every optional
package. Measured here: a `which()` MISS costs **38.9ms**, because Windows
walks every PATH entry against every PATHEXT before concluding nothing is
there -- and misses are the common case, since most optional tools are not
installed. There are 66 such probe calls across 20+ modules.

Separately, a capability engine needs to know exactly the same thing: which
binaries, packages, models and services exist. Asking "can ZENO do X?" is
mostly asking "is the thing X needs installed?".

So this is one cache with two consumers. Availability changes when software
is installed or removed -- not between two health polls a second apart --
so it is cached with a long TTL and an explicit `invalidate()` for the
moments when it genuinely changes.

WHAT IT IS NOT
--------------
It does not decide whether a capability is USABLE. Installed is not
configured, and configured is not authorised. `registry.py` layers those on
top. This answers exactly one question -- "is it present?" -- and answers it
fast.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import threading
import time
from typing import Any, Callable

# Availability changes when the owner installs something. Ten minutes is far
# longer than any burst of polling and far shorter than a working session.
TTL_S = 600.0

_lock = threading.RLock()
_binaries: dict[str, tuple[str | None, float]] = {}
_packages: dict[str, tuple[bool, float]] = {}
_probes: dict[str, tuple[Any, float]] = {}
_hits = 0
_misses = 0


def _fresh(stamp: float) -> bool:
    return (time.time() - stamp) < TTL_S


def which(name: str) -> str | None:
    """Cached `shutil.which`. The single most expensive probe ZENO makes."""
    global _hits, _misses
    key = str(name or "").strip().lower()
    if not key:
        return None
    with _lock:
        cached = _binaries.get(key)
        if cached is not None and _fresh(cached[1]):
            _hits += 1
            return cached[0]
    # Probe OUTSIDE the lock: which() can take 39ms and must not block
    # every other caller while it walks PATH.
    found = shutil.which(key)
    with _lock:
        _binaries[key] = (found, time.time())
        _misses += 1
    return found


def has_binary(name: str) -> bool:
    return which(name) is not None


def has_package(name: str) -> bool:
    """Cached `importlib.util.find_spec`, without importing the package."""
    global _hits, _misses
    key = str(name or "").strip()
    if not key:
        return False
    with _lock:
        cached = _packages.get(key)
        if cached is not None and _fresh(cached[1]):
            _hits += 1
            return cached[0]
    try:
        found = importlib.util.find_spec(key.split(".")[0]) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        found = False
    with _lock:
        _packages[key] = (found, time.time())
        _misses += 1
    return found


def probe(name: str, produce: Callable[[], Any], *, ttl_s: float = TTL_S) -> Any:
    """Cache any expensive availability answer under a name.

    For the compound reports -- `phase3.status()`, `phase5.status()` -- that
    are themselves nothing but dozens of the lookups above. A failure is
    cached too, briefly, so a broken probe cannot be re-run on every poll.
    """
    global _hits, _misses
    key = str(name)
    with _lock:
        cached = _probes.get(key)
        if cached is not None and (time.time() - cached[1]) < ttl_s:
            _hits += 1
            return cached[0]
    try:
        value = produce()
    except Exception as exc:  # noqa: BLE001 -- availability probing must not raise
        value = {"state": "DEGRADED", "error": f"{type(exc).__name__}: {exc}"}
    with _lock:
        _probes[key] = (value, time.time())
        _misses += 1
    return value


def invalidate(what: str = "") -> None:
    """Forget what we knew. Call when software is installed or removed.

    With no argument it forgets everything; with a name it forgets one
    entry, so installing a single tool does not throw away the whole
    inventory.
    """
    with _lock:
        if not what:
            _binaries.clear()
            _packages.clear()
            _probes.clear()
            return
        key = str(what).strip()
        _binaries.pop(key.lower(), None)
        _packages.pop(key, None)
        _probes.pop(key, None)


def warm(binaries: tuple[str, ...] = (), packages: tuple[str, ...] = ()) -> dict[str, Any]:
    """Fill the cache ahead of a burst. Optional; the cache fills lazily."""
    started = time.time()
    for name in binaries:
        which(name)
    for name in packages:
        has_package(name)
    return {"binaries": len(binaries), "packages": len(packages),
            "took_ms": round((time.time() - started) * 1000, 1)}


def stats() -> dict[str, Any]:
    with _lock:
        total = _hits + _misses
        return {
            "binaries_cached": len(_binaries),
            "packages_cached": len(_packages),
            "probes_cached": len(_probes),
            "hits": _hits, "misses": _misses,
            "hit_rate": round(_hits / total, 3) if total else 0.0,
            "ttl_s": TTL_S,
        }


def snapshot() -> dict[str, Any]:
    """Everything currently known, for the dashboard and the engine."""
    with _lock:
        return {
            "binaries": {name: path for name, (path, _at) in sorted(_binaries.items())},
            "packages": {name: found for name, (found, _at) in sorted(_packages.items())},
            "stats": stats(),
            "note": ("Presence only. Installed is not configured, and configured "
                     "is not authorised -- registry.py decides those."),
        }
