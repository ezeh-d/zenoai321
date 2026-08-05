"""Universal GUI control: drive ANY app by moving the mouse, clicking, and typing.

This is how REYES controls apps that have no API (Slack desktop, Photoshop,
games, anything with a window). It literally uses your mouse and keyboard.

Requires:  pip install pyautogui
Optional (for reading text off the screen):  pip install pytesseract  + install Tesseract

Safety: actions that change things (click, type, press, hotkey) go through the
approver so REYES asks before acting. Read-only actions (position, size, locate,
read_screen) do not prompt. Slam the mouse into a screen corner to abort (pyautogui failsafe).
"""
from __future__ import annotations

from typing import Callable


class GUI:
    def __init__(self, approver: Callable[[str], bool], data_dir: str = "./data"):
        self.approver = approver
        self.data_dir = data_dir

    def _pg(self):
        import pyautogui

        pyautogui.FAILSAFE = True
        return pyautogui

    # ---------- read-only ----------
    def screen_size(self) -> str:
        try:
            w, h = self._pg().size()
            return f"Screen is {w}x{h}."
        except Exception as e:  # noqa: BLE001
            return f"GUI unavailable ({e}). Install: pip install pyautogui"

    def mouse_position(self) -> str:
        try:
            x, y = self._pg().position()
            return f"Mouse at ({x}, {y})."
        except Exception as e:  # noqa: BLE001
            return f"GUI unavailable ({e})."

    def locate(self, image_path: str) -> str:
        """Find an on-screen image (e.g. a button screenshot) and return its center."""
        try:
            pt = self._pg().locateCenterOnScreen(image_path, confidence=0.8)
            return f"Found at ({pt.x}, {pt.y})." if pt else "Image not found on screen."
        except Exception as e:  # noqa: BLE001
            return f"Locate failed ({e}). Needs pip install opencv-python."

    def read_screen(self) -> str:
        """OCR the whole screen into text (optional feature)."""
        try:
            import pytesseract

            shot = self._pg().screenshot()
            text = pytesseract.image_to_string(shot)
            return text.strip()[:4000] or "(no text detected)"
        except Exception as e:  # noqa: BLE001
            return f"Screen OCR unavailable ({e}). Install pytesseract + Tesseract."

    def move(self, x: int, y: int) -> str:
        try:
            self._pg().moveTo(int(x), int(y), duration=0.2)
            return f"Moved to ({x}, {y})."
        except Exception as e:  # noqa: BLE001
            return f"Move failed ({e})."

    # ---------- actions (guarded) ----------
    def click(self, x: int | None = None, y: int | None = None,
              button: str = "left", clicks: int = 1) -> str:
        where = f"({x}, {y})" if x is not None else "current position"
        if not self.approver(f"{button}-click x{clicks} at {where}"):
            return "Cancelled by user."
        try:
            pg = self._pg()
            if x is not None and y is not None:
                pg.click(int(x), int(y), clicks=int(clicks), button=button)
            else:
                pg.click(clicks=int(clicks), button=button)
            return f"Clicked {where}."
        except Exception as e:  # noqa: BLE001
            return f"Click failed ({e})."

    def type_text(self, text: str) -> str:
        if not self.approver(f"Type: {text[:60]!r}"):
            return "Cancelled by user."
        try:
            self._pg().write(text, interval=0.02)
            return "Typed."
        except Exception as e:  # noqa: BLE001
            return f"Type failed ({e})."

    def press(self, key: str) -> str:
        if not self.approver(f"Press key: {key}"):
            return "Cancelled by user."
        try:
            self._pg().press(key)
            return f"Pressed {key}."
        except Exception as e:  # noqa: BLE001
            return f"Press failed ({e})."

    def hotkey(self, combo: str) -> str:
        """combo like 'ctrl+c' or 'ctrl+shift+t'."""
        keys = [k.strip() for k in combo.replace(",", "+").split("+") if k.strip()]
        if not self.approver(f"Hotkey: {'+'.join(keys)}"):
            return "Cancelled by user."
        try:
            self._pg().hotkey(*keys)
            return f"Sent {'+'.join(keys)}."
        except Exception as e:  # noqa: BLE001
            return f"Hotkey failed ({e})."

    def scroll(self, amount: int) -> str:
        try:
            self._pg().scroll(int(amount))
            return f"Scrolled {amount}."
        except Exception as e:  # noqa: BLE001
            return f"Scroll failed ({e})."
