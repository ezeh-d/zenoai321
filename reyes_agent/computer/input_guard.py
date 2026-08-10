"""Do not take the mouse out of the owner's hand.

THE GAP THIS CLOSES
-------------------
`pyautogui` drives the REAL cursor and the REAL keyboard. An agentic run
therefore competes with the person sitting at the machine: ZENO moves the
pointer mid-sentence, or types into whatever window the owner just clicked
into. Phase 1 shipped with no guard on that at all.

THREE RULES
-----------
1. If the owner has touched the mouse or keyboard in the last few seconds,
   ZENO does not seize input. It says so and waits.
2. Whatever the run does, the cursor goes back where it was. The owner
   should not have to find their pointer afterwards.
3. There is always a way out: pyautogui's corner failsafe stays ON, and
   the owner can revoke control mid-run.

Idle time is read the same way `activity_monitor` reads it -- the Windows
last-input timer -- so this needs no new sensor.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

# The owner counts as "at the keyboard" for this long after their last input.
# Short enough not to be obstructive, long enough to catch active typing.
BUSY_WINDOW_S = 4.0

_lock = threading.Lock()
_held_by = ""
_held_since = 0.0
_revoked = threading.Event()


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def owner_idle_seconds() -> float:
    """Seconds since the owner last touched mouse or keyboard.

    Returns 0.0 when it cannot be read -- treating "unknown" as "the owner
    is active" is the safe direction to fail.
    """
    try:
        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        ticks = ctypes.windll.kernel32.GetTickCount()
        return max(0.0, (ticks - info.dwTime) / 1000.0)
    except Exception:  # noqa: BLE001
        return 0.0


def owner_is_active() -> bool:
    return owner_idle_seconds() < BUSY_WINDOW_S


def cursor_position() -> tuple[int, int] | None:
    try:
        point = ctypes.wintypes.POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
            return (int(point.x), int(point.y))
    except Exception:  # noqa: BLE001
        pass
    return None


def restore_cursor(position: tuple[int, int] | None) -> bool:
    if not position:
        return False
    try:
        return bool(ctypes.windll.user32.SetCursorPos(int(position[0]), int(position[1])))
    except Exception:  # noqa: BLE001
        return False


def revoke(reason: str = "owner revoked control") -> None:
    """Stop the current run from sending any further input."""
    _revoked.set()
    try:
        from reyes_agent import event_bus

        event_bus.publish("computer.control_revoked", {"reason": reason}, source="input_guard")
    except Exception:  # noqa: BLE001
        pass


def revoked() -> bool:
    return _revoked.is_set()


@dataclass
class Grant:
    allowed: bool
    reason: str
    idle_s: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "reason": self.reason,
                "owner_idle_s": round(self.idle_s, 1)}


def may_take_control(*, override: bool = False) -> Grant:
    """Is it acceptable to move the pointer right now?"""
    idle = owner_idle_seconds()
    if _revoked.is_set():
        return Grant(False, "control was revoked; start a new run to continue", idle)
    if override:
        return Grant(True, "override: the owner explicitly asked for this now", idle)
    if idle < BUSY_WINDOW_S:
        return Grant(False,
                     f"you were using the mouse/keyboard {idle:.1f}s ago -- I will not "
                     "take the pointer while you are working. Say go ahead and I will.",
                     idle)
    return Grant(True, f"idle for {idle:.1f}s", idle)


@contextmanager
def control(name: str = "agentic", *, override: bool = False):
    """Hold input control for the duration of a run.

    Yields a `Grant`. When it is not allowed, NOTHING should be sent -- the
    caller must check. The cursor is restored on the way out either way.
    """
    global _held_by, _held_since
    grant = may_take_control(override=override)
    origin = cursor_position() if grant.allowed else None
    if grant.allowed:
        with _lock:
            _held_by, _held_since = name, time.time()
        try:
            import pyautogui

            pyautogui.FAILSAFE = True      # corner escape stays available
        except Exception:  # noqa: BLE001
            pass
    try:
        yield grant
    finally:
        if grant.allowed:
            restore_cursor(origin)
            with _lock:
                _held_by, _held_since = "", 0.0


@contextmanager
def cursor_home():
    """Put the pointer back where the owner left it, whatever happens inside.

    Unlike `control()` this gates nothing -- it is the courtesy half, used to
    wrap a whole run so the owner does not have to hunt for their cursor.
    """
    origin = cursor_position()
    try:
        yield origin
    finally:
        restore_cursor(origin)


def status() -> dict[str, Any]:
    with _lock:
        holder, since = _held_by, _held_since
    idle = owner_idle_seconds()
    return {
        "held_by": holder or None,
        "held_for_s": round(time.time() - since, 1) if since else None,
        "owner_idle_s": round(idle, 1),
        "owner_active": idle < BUSY_WINDOW_S,
        "revoked": _revoked.is_set(),
        "busy_window_s": BUSY_WINDOW_S,
        "failsafe": "pyautogui corner failsafe is enabled during a run",
    }


def reset() -> None:
    """Test hook / start of a new run."""
    global _held_by, _held_since
    _revoked.clear()
    with _lock:
        _held_by, _held_since = "", 0.0
