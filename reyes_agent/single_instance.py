"""Windows desktop single-instance guard with best-effort window focus."""
from __future__ import annotations

import ctypes
import hashlib
import os
from pathlib import Path


class SingleInstanceGuard:
    def __init__(self, application_name: str, root: Path) -> None:
        digest = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:16]
        self._name = f"Local\\{application_name}-kernel-{digest}"
        self._handle = None
        self._application_name = application_name
        self._fallback_path = root / ".zeno-instance.lock"
        self._fallback_owned = False

    def acquire(self) -> bool:
        if os.name == "nt":
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.CreateMutexW(None, True, self._name)
            if not handle:
                raise OSError(ctypes.get_last_error(), "CreateMutexW failed")
            if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
                kernel32.CloseHandle(handle)
                self.focus_existing()
                return False
            self._handle = handle
            return True
        try:
            fd = os.open(self._fallback_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            self._fallback_owned = True
            return True
        except FileExistsError:
            return False

    def focus_existing(self) -> None:
        """Best effort: foregrounding is constrained by Windows focus policy."""
        if os.name != "nt":
            return
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        matches: list[int] = []
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        @callback_type
        def visit(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                title = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, title, length + 1)
                if self._application_name.lower() in title.value.lower():
                    matches.append(hwnd)
                    return False
            return True

        user32.EnumWindows(visit, 0)
        if matches:
            user32.ShowWindow(matches[0], 9)  # SW_RESTORE
            user32.SetForegroundWindow(matches[0])

    def release(self) -> None:
        if self._handle is not None:
            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(self._handle)
            self._handle = None
        if self._fallback_owned:
            try:
                self._fallback_path.unlink(missing_ok=True)
            finally:
                self._fallback_owned = False
