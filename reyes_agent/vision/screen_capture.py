"""Screenshots for the vision layer.

Reuses `mss` (already installed) and writes into the existing captures
folder so nothing new appears on the owner's disk in a new place.
"""

from __future__ import annotations

import ctypes
import time
from pathlib import Path

from reyes_agent import config

_DIR = config.VAULT_PATH / "07-System" / "captures"
_MAX_KEPT = 20


def _window_rect(handle: int) -> tuple[int, int, int, int] | None:
    try:
        rect = ctypes.wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(handle, ctypes.byref(rect)):
            return None
        return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
    except Exception:  # noqa: BLE001
        return None


def _prune() -> None:
    try:
        shots = sorted(_DIR.glob("scene-*.png"), key=lambda p: p.stat().st_mtime)
        for stale in shots[:-_MAX_KEPT]:
            stale.unlink(missing_ok=True)
    except OSError:
        pass


def capture(handle: int = 0) -> Path | None:
    """Capture one window (or the whole screen). Returns the path, or None."""
    try:
        import mss
        import mss.tools
    except ImportError:
        return None
    try:
        _DIR.mkdir(parents=True, exist_ok=True)
        target = _DIR / f"scene-{int(time.time() * 1000)}.png"
        with mss.mss() as sct:
            region = _window_rect(handle) if handle else None
            if region and region[2] > 0 and region[3] > 0:
                box = {"left": region[0], "top": region[1],
                       "width": region[2], "height": region[3]}
            else:
                box = sct.monitors[1]
            raw = sct.grab(box)
            mss.tools.to_png(raw.rgb, raw.size, output=str(target))
        _prune()
        return target
    except Exception:  # noqa: BLE001 -- a failed screenshot is not a crash
        return None
