"""Controlled scrcpy binary adapter; no embedded source or shell."""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
from typing import Any

from reyes_agent.devices.mobile.manager import MobileDeviceManager


class ScrcpyBridge:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None

    def open(self, device_id: str) -> dict[str, Any]:
        if os.environ.get("ZENO_SCRCPY_ENABLED", "").casefold() not in {"1", "true", "yes", "on"}:
            return {"ok": False, "reason": "ZENO_SCRCPY_ENABLED is off"}
        if device_id not in MobileDeviceManager.paired_ids():
            return {"ok": False, "reason": "device is not explicitly paired with ZENO"}
        binary = shutil.which("scrcpy")
        if not binary:
            return {"ok": False, "reason": "scrcpy is not installed"}
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return {"ok": True, "pid": self._process.pid, "reused": True}
            self._process = subprocess.Popen([binary, "--serial", device_id], shell=False,
                                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return {"ok": True, "pid": self._process.pid, "reused": False}

    def stop(self) -> None:
        with self._lock:
            process, self._process = self._process, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    def status(self) -> dict[str, Any]:
        with self._lock:
            process = self._process
        return {"enabled": os.environ.get("ZENO_SCRCPY_ENABLED", "").casefold() in {"1", "true", "yes", "on"},
                "available": bool(shutil.which("scrcpy")), "running": bool(process and process.poll() is None),
                "pid": process.pid if process and process.poll() is None else None}


_bridge = ScrcpyBridge()


def get_bridge() -> ScrcpyBridge:
    return _bridge
