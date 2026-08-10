"""Did we actually see the window, or just its shell?

THE FAILURE THIS PREVENTS
-------------------------
`parse_uia` returning three elements is indistinguishable, to a caller, from
a window that genuinely contains three things. So a suspended Calculator --
which UIA reports as ONE element -- reads as "a calculator with no buttons",
and the agentic loop concludes the button it needs is not on screen. The
loop is right about what it saw and wrong about the world.

MEASURED, ON THIS MACHINE
-------------------------
Enumerating every visible window and scanning each one:

    elements  interactive  DWM cloaked  window
        70         25           0       Chrome
       156         81           0       Chrome
        33         31           0       Program Manager (desktop)
         1          0           2       Calculator
         1          0           2       Settings
         1          0           2       Microsoft Text Input Application

The correlation is exact, with no exceptions: every collapsed tree was
shell-cloaked, every healthy tree was not. Checking the raw subtree with the
offscreen filter removed still gave 1 -- so this is UIA genuinely reporting
one node, not our filtering.

So the cause is READ, not guessed, and the three causes have different
remedies:

  MINIMIZED  -- nothing is rendered. Restore the window.
  SUSPENDED  -- shell-cloaked UWP; the tree collapses while backgrounded.
                Bring it to the foreground and scan again.
  OPAQUE     -- visible, not cloaked, large, and still nothing to act on:
                a canvas, a game, remote desktop, a custom-drawn surface.
                This is the only case where OCR is worth paying for.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
from dataclasses import dataclass
from typing import Any

GOOD = "GOOD"
MINIMIZED = "MINIMIZED"
SUSPENDED = "SUSPENDED"
OPAQUE = "OPAQUE"
SLOW = "SLOW"

# Enumerating longer than this means the app answered, just far too slowly
# to be treated as a normal read.
SLOW_ENUMERATE_S = 6.0

DWMWA_CLOAKED = 14

# Only judge coverage on a window big enough that emptiness is suspicious.
# A 200x120 confirmation dialog legitimately holds two controls.
MIN_JUDGED_AREA = 300 * 300

# Above this many elements the tree is plainly being published properly.
HEALTHY_ELEMENTS = 5


@dataclass(frozen=True)
class Coverage:
    state: str = GOOD
    reason: str = ""
    remedy: str = ""

    @property
    def trustworthy(self) -> bool:
        return self.state == GOOD

    @property
    def worth_ocr(self) -> bool:
        """OCR only helps when something IS drawn but not published."""
        return self.state == OPAQUE

    def as_dict(self) -> dict[str, Any]:
        return {"state": self.state, "reason": self.reason, "remedy": self.remedy,
                "trustworthy": self.trustworthy}


def window_rect(handle: int) -> tuple[int, int, int, int]:
    try:
        rect = ctypes.wintypes.RECT()
        if ctypes.windll.user32.GetWindowRect(ctypes.wintypes.HWND(handle), ctypes.byref(rect)):
            return (int(rect.left), int(rect.top),
                    int(rect.right - rect.left), int(rect.bottom - rect.top))
    except Exception:  # noqa: BLE001
        pass
    return (0, 0, 0, 0)


def is_minimized(handle: int) -> bool:
    try:
        return bool(ctypes.windll.user32.IsIconic(ctypes.wintypes.HWND(handle)))
    except Exception:  # noqa: BLE001
        return False


def cloak_state(handle: int) -> int:
    """0 = not cloaked. 2 = shell-cloaked, which is how Windows suspends a
    backgrounded UWP app. Returns 0 when it cannot be read."""
    try:
        value = ctypes.c_int(0)
        result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            ctypes.wintypes.HWND(handle), ctypes.c_uint(DWMWA_CLOAKED),
            ctypes.byref(value), ctypes.sizeof(value))
        return int(value.value) if result == 0 else 0
    except Exception:  # noqa: BLE001
        return 0


def assess(handle: int, element_count: int, interactive_count: int,
           *, enumerate_s: float = 0.0, reported_total: int = 0) -> Coverage:
    """Decide whether a scan of `handle` can be believed.

    `enumerate_s` and `reported_total` describe the query itself, and they
    are what separate "this window has nothing on it" from "this window has
    four thousand things on it and answered too slowly to collect them".
    """
    if element_count > HEALTHY_ELEMENTS and interactive_count:
        return Coverage(GOOD, f"{element_count} elements, {interactive_count} actionable")

    # An app that reported thousands of elements is emphatically not opaque,
    # however few of them we managed to keep.
    if reported_total > element_count and enumerate_s >= SLOW_ENUMERATE_S:
        return Coverage(SLOW,
                        f"this window published {reported_total} elements but took "
                        f"{enumerate_s:.1f}s just to list them, so the read was cut "
                        f"short at {element_count}",
                        "bring it to the foreground (Windows throttles background "
                        "apps) and look again")

    if is_minimized(handle):
        return Coverage(MINIMIZED,
                        "the window is minimized, so nothing is rendered to read",
                        "restore the window, then look again")

    cloak = cloak_state(handle)
    if cloak:
        return Coverage(SUSPENDED,
                        f"Windows has suspended this app in the background "
                        f"(DWM cloak state {cloak}); its accessibility tree collapses "
                        "to a single node while suspended",
                        "bring the window to the foreground, then look again")

    _, _, width, height = window_rect(handle)
    if width * height < MIN_JUDGED_AREA:
        # Small window, few controls -- entirely normal.
        return Coverage(GOOD, f"small window ({width}x{height}) with {element_count} elements")

    if interactive_count == 0 and element_count < HEALTHY_ELEMENTS and not reported_total:
        return Coverage(OPAQUE,
                        f"this {width}x{height} window published only {element_count} "
                        "element(s) and nothing actionable -- it is drawing its own "
                        "interface rather than exposing it (canvas, game, remote "
                        "desktop or a custom-drawn app)",
                        "read it with OCR; clicks cannot be grounded to real controls here")

    return Coverage(GOOD, f"{element_count} elements, {interactive_count} actionable")
