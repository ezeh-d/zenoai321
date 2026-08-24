"""Optional pywinauto fast path; existing COM UIA remains the fallback."""
from __future__ import annotations

import importlib.util
import os
from typing import Any

_loaded = False


def status() -> dict[str, Any]:
    installed = importlib.util.find_spec("pywinauto") is not None
    enabled = os.environ.get("ZENO_PYWINAUTO_ENABLED", "").casefold() in {"1", "true", "yes", "on"}
    return {"state": "STANDBY" if enabled and installed else ("DEGRADED" if enabled else "DISABLED"),
            "enabled": enabled, "installed": installed, "loaded": _loaded,
            "priority": ["native API", "UIA/pywinauto", "browser DOM", "CUA", "vision", "coordinates"]}


def windows() -> list[dict[str, Any]]:
    global _loaded
    if not status()["enabled"] or not status()["installed"]:
        return []
    from pywinauto import Desktop
    _loaded = True
    return [{"handle": int(item.handle), "title": item.window_text()[:240]}
            for item in Desktop(backend="uia").windows() if item.window_text()][:200]
