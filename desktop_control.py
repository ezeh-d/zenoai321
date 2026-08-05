from __future__ import annotations

import time
from typing import Final

import pyautogui


# =========================================================
# SAFETY SETTINGS
# =========================================================

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.15

DEFAULT_MOVE_DURATION: Final[float] = 0.25
DEFAULT_SCROLL_AMOUNT: Final[int] = 600


# =========================================================
# SCREEN INFORMATION
# =========================================================

def get_screen_size() -> str:
    """
    Return the current primary screen resolution.
    """
    width, height = pyautogui.size()
    return f"Screen size is {width} by {height} pixels."


def get_mouse_position() -> str:
    """
    Return the current mouse pointer coordinates.
    """
    point = pyautogui.position()
    return f"Mouse position is x {point.x}, y {point.y}."


# =========================================================
# POINTER CONTROL
# =========================================================

def move_mouse(x: int, y: int) -> str:
    """
    Move the mouse pointer to an absolute screen coordinate.
    """
    try:
        width, height = pyautogui.size()

        safe_x = max(0, min(int(x), width - 1))
        safe_y = max(0, min(int(y), height - 1))

        pyautogui.moveTo(
            safe_x,
            safe_y,
            duration=DEFAULT_MOVE_DURATION,
        )

        return f"Mouse moved to x {safe_x}, y {safe_y}."

    except Exception as error:
        return (
            "I could not move the mouse. "
            f"{type(error).__name__}: {error}"
        )


def click_mouse(
    x: int | None = None,
    y: int | None = None,
    button: str = "left",
    clicks: int = 1,
) -> str:
    """
    Click at the current pointer location or at supplied coordinates.
    """
    try:
        valid_buttons = {"left", "right", "middle"}

        normalized_button = button.strip().lower()

        if normalized_button not in valid_buttons:
            normalized_button = "left"

        if x is not None and y is not None:
            move_mouse(int(x), int(y))

        pyautogui.click(
            button=normalized_button,
            clicks=max(1, int(clicks)),
            interval=0.12,
        )

        position = pyautogui.position()

        return (
            f"{normalized_button.title()} click completed at "
            f"x {position.x}, y {position.y}."
        )

    except Exception as error:
        return (
            "I could not click the mouse. "
            f"{type(error).__name__}: {error}"
        )


def double_click(
    x: int | None = None,
    y: int | None = None,
) -> str:
    """
    Double-click at the current pointer location or supplied coordinates.
    """
    return click_mouse(
        x=x,
        y=y,
        button="left",
        clicks=2,
    )


def right_click(
    x: int | None = None,
    y: int | None = None,
) -> str:
    """
    Right-click at the current pointer location or supplied coordinates.
    """
    return click_mouse(
        x=x,
        y=y,
        button="right",
        clicks=1,
    )


# =========================================================
# KEYBOARD CONTROL
# =========================================================

def type_text(
    text: str,
    interval: float = 0.03,
) -> str:
    """
    Type text into the currently focused application.
    """
    clean_text = text.strip()

    if not clean_text:
        return "There is no text to type."

    try:
        pyautogui.write(
            clean_text,
            interval=max(0.0, float(interval)),
        )

        return "Text typed successfully."

    except Exception as error:
        return (
            "I could not type the text. "
            f"{type(error).__name__}: {error}"
        )


def press_key(key: str) -> str:
    """
    Press one keyboard key.
    """
    clean_key = key.strip().lower()

    if not clean_key:
        return "Tell me which key to press."

    try:
        pyautogui.press(clean_key)
        return f"Pressed {clean_key}."

    except Exception as error:
        return (
            f"I could not press {clean_key}. "
            f"{type(error).__name__}: {error}"
        )


def hotkey(*keys: str) -> str:
    """
    Press a keyboard shortcut.
    """
    clean_keys = [
        key.strip().lower()
        for key in keys
        if key.strip()
    ]

    if not clean_keys:
        return "No shortcut keys were provided."

    try:
        pyautogui.hotkey(*clean_keys)
        return f"Pressed {' + '.join(clean_keys)}."

    except Exception as error:
        return (
            "I could not perform the keyboard shortcut. "
            f"{type(error).__name__}: {error}"
        )


# =========================================================
# SCROLLING
# =========================================================

def scroll_up(amount: int = DEFAULT_SCROLL_AMOUNT) -> str:
    """
    Scroll upward.
    """
    try:
        pyautogui.scroll(abs(int(amount)))
        return "Scrolled up."

    except Exception as error:
        return (
            "I could not scroll up. "
            f"{type(error).__name__}: {error}"
        )


def scroll_down(amount: int = DEFAULT_SCROLL_AMOUNT) -> str:
    """
    Scroll downward.
    """
    try:
        pyautogui.scroll(-abs(int(amount)))
        return "Scrolled down."

    except Exception as error:
        return (
            "I could not scroll down. "
            f"{type(error).__name__}: {error}"
        )


# =========================================================
# WINDOW SHORTCUTS
# =========================================================

def minimize_window() -> str:
    return hotkey("win", "down")


def maximize_window() -> str:
    return hotkey("win", "up")


def switch_window() -> str:
    return hotkey("alt", "tab")


def close_current_window() -> str:
    return hotkey("alt", "f4")


def show_desktop() -> str:
    return hotkey("win", "d")


def open_task_view() -> str:
    return hotkey("win", "tab")


# =========================================================
# SAFE DELAY
# =========================================================

def wait(seconds: float) -> str:
    """
    Pause briefly before the next command.
    """
    duration = max(0.0, min(float(seconds), 30.0))
    time.sleep(duration)
    return f"Waited {duration:g} seconds."