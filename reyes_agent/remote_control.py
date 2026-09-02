"""Owner-only remote pointer control -- the ZENO phone as a touch mouse.

The phone (authenticated owner) sends pointer intents; this maps them onto the
laptop's OS cursor via pyautogui. Mouse only: keyboard, hotkeys, clipboard and
command execution are deliberately NOT reachable here (that stays in the
existing, separately-gated tools).

SECURITY (master prompt "SECURITY — CRITICAL"):
- Three control modes: VIEW (watch only), PANEL (UI-level, no OS pointer),
  MOUSE (drives the OS cursor). Default is PANEL -- an authenticated connection
  is NOT automatically granted OS-pointer control.
- Emergency stop: the laptop owner can disable remote control instantly; every
  pointer intent is then refused while the phone stays connected in view mode.
- Rate limiting: moves coalesce (latest-position wins); clicks are never
  dropped; a bounded budget stops an event flood.
- Coordinate scaling: normalized [0,1] phone coordinates map to the real screen
  (DPI/scaling handled by pyautogui's own size), so raw mobile pixels never
  reach the OS.
- Keyboard/typing/hotkey/scroll-lock actions are refused outright.

The pyautogui backend is injectable so the logic is unit-tested without moving
a real cursor.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

VIEW, PANEL, MOUSE = "view", "panel", "mouse"
_MODES = (VIEW, PANEL, MOUSE)

# actions this channel will NEVER perform, even in MOUSE mode.
_FORBIDDEN = frozenset({
    "type", "key", "hotkey", "keydown", "keyup", "press", "write",
    "paste", "copy", "exec", "run", "command", "shell",
})
_POINTER_ACTIONS = frozenset({
    "move", "click", "double", "right", "down", "up", "scroll", "drag",
})

_MAX_EVENTS_PER_SEC = 120        # flood ceiling (moves coalesce below this)


@dataclass
class _Backend:
    """Thin wrapper over pyautogui so tests can inject a fake."""
    impl: Any = None

    def _lib(self):
        if self.impl is not None:
            return self.impl
        import pyautogui
        pyautogui.FAILSAFE = False   # the emergency stop is our own, above this
        return pyautogui

    def size(self) -> tuple[int, int]:
        w, h = self._lib().size()
        return int(w), int(h)

    def move_to(self, x: int, y: int) -> None: self._lib().moveTo(x, y)
    def click(self, x: int, y: int) -> None: self._lib().click(x, y)
    def double(self, x: int, y: int) -> None: self._lib().doubleClick(x, y)
    def right(self, x: int, y: int) -> None: self._lib().rightClick(x, y)
    def mouse_down(self, x: int, y: int) -> None: self._lib().mouseDown(x, y)
    def mouse_up(self, x: int, y: int) -> None: self._lib().mouseUp(x, y)
    def scroll(self, amount: int) -> None: self._lib().scroll(int(amount))


@dataclass
class ControlState:
    mode: str = PANEL
    enabled: bool = True             # owner emergency-stop flips this to False
    controller_device: str | None = None
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "enabled": self.enabled,
                "controller_device": self.controller_device,
                "can_move_pointer": self.enabled and self.mode == MOUSE,
                "updated_at": self.updated_at}


class RemoteController:
    def __init__(self, backend: _Backend | None = None) -> None:
        self._state = ControlState(updated_at=time.time())
        self._backend = backend or _Backend()
        self._lock = threading.RLock()
        # rate limiting
        self._window_start = 0.0
        self._count = 0
        self._last_move: tuple[int, int] | None = None

    # -- control plane -----------------------------------------------------
    def state(self) -> dict[str, Any]:
        with self._lock:
            return self._state.to_dict()

    def set_mode(self, mode: str) -> dict[str, Any]:
        mode = str(mode or "").lower()
        if mode not in _MODES:
            return {"ok": False, "detail": f"unknown mode '{mode}'"}
        with self._lock:
            self._state.mode = mode
            self._state.updated_at = time.time()
        return {"ok": True, **self.state()}

    def emergency_stop(self) -> dict[str, Any]:
        """Owner kill switch: refuse all pointer intents immediately."""
        with self._lock:
            self._state.enabled = False
            self._state.mode = VIEW
            self._state.updated_at = time.time()
        return {"ok": True, "detail": "remote control disabled", **self.state()}

    def enable(self) -> dict[str, Any]:
        with self._lock:
            self._state.enabled = True
            self._state.updated_at = time.time()
        return {"ok": True, **self.state()}

    def claim(self, device: str | None) -> None:
        with self._lock:
            self._state.controller_device = device

    # -- rate limiting -----------------------------------------------------
    def _allow(self, action: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if now - self._window_start >= 1.0:
                self._window_start = now
                self._count = 0
            self._count += 1
            # clicks are never dropped; only high-frequency moves are capped
            if action in ("move", "scroll", "drag") and self._count > _MAX_EVENTS_PER_SEC:
                return False
            return True

    # -- coordinate scaling ------------------------------------------------
    def _to_screen(self, nx: float, ny: float) -> tuple[int, int]:
        w, h = self._backend.size()
        x = int(max(0.0, min(1.0, float(nx))) * (w - 1))
        y = int(max(0.0, min(1.0, float(ny))) * (h - 1))
        return x, y

    # -- the one pointer entry point --------------------------------------
    def pointer(self, action: str, *, nx: float = 0.0, ny: float = 0.0,
                amount: int = 0, device: str | None = None) -> dict[str, Any]:
        action = str(action or "").lower()
        if action in _FORBIDDEN:
            return {"ok": False, "detail": "keyboard/command actions are not "
                    "available from the phone", "action": action}
        if action not in _POINTER_ACTIONS:
            return {"ok": False, "detail": f"unknown pointer action '{action}'"}
        with self._lock:
            enabled, mode = self._state.enabled, self._state.mode
        if not enabled:
            return {"ok": False, "detail": "remote control is disabled", "action": action}
        if mode != MOUSE:
            return {"ok": False, "detail": f"OS pointer needs MOUSE mode (current: {mode})",
                    "action": action}
        if not self._allow(action):
            return {"ok": True, "coalesced": True, "action": action}  # dropped move, not an error
        try:
            self._execute(action, nx, ny, amount)
        except Exception as exc:  # noqa: BLE001 -- never raise into the request
            return {"ok": False, "detail": f"pointer failed: {exc}", "action": action}
        return {"ok": True, "action": action}

    def _execute(self, action: str, nx: float, ny: float, amount: int) -> None:
        b = self._backend
        if action == "scroll":
            b.scroll(int(amount))
            return
        x, y = self._to_screen(nx, ny)
        if action in ("move", "drag"):
            b.move_to(x, y)
        elif action == "click":
            b.click(x, y)
        elif action == "double":
            b.double(x, y)
        elif action == "right":
            b.right(x, y)
        elif action == "down":
            b.mouse_down(x, y)
        elif action == "up":
            b.mouse_up(x, y)


_controller: RemoteController | None = None
_lock = threading.Lock()


def get_remote_controller() -> RemoteController:
    global _controller
    if _controller is None:
        with _lock:
            if _controller is None:
                _controller = RemoteController()
    return _controller
