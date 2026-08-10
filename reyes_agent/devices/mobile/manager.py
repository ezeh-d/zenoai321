"""Explicitly paired, lazy mobile-device discovery."""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any


class MobileDeviceManager:
    @staticmethod
    def paired_ids() -> frozenset[str]:
        return frozenset(item.strip() for item in os.environ.get("ZENO_PAIRED_DEVICE_IDS", "").split(",") if item.strip())

    def discover(self) -> dict[str, Any]:
        enabled = os.environ.get("ZENO_AGENT_DEVICE_ENABLED", "").casefold() in {"1", "true", "yes", "on"}
        adb = shutil.which("adb")
        if not enabled:
            return {"state": "DISABLED", "devices": [], "reason": "ZENO_AGENT_DEVICE_ENABLED is off"}
        if not adb:
            return {"state": "DEGRADED", "devices": [], "reason": "ADB is not installed"}
        try:
            result = subprocess.run([adb, "devices", "-l"], shell=False, capture_output=True,
                                    text=True, timeout=4, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as exc:
            return {"state": "DEGRADED", "devices": [], "reason": f"{type(exc).__name__}: {exc}"}
        paired = self.paired_ids()
        devices = []
        for line in result.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                device_id = parts[0]
                devices.append({"id": device_id, "transport": "ADB", "connected": True,
                                "authorized": device_id in paired})
        return {"state": "ONLINE" if devices else "DISCONNECTED", "devices": devices,
                "network_pairing_automatic": False, "public_endpoint": False}
