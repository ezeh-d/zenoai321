"""Authenticated, timeout-bounded Home Assistant REST adapter."""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import requests


class HomeAssistantClient:
    def __init__(self) -> None:
        self.base_url = os.environ.get("HOME_ASSISTANT_URL", "").strip().rstrip("/")
        self.token = os.environ.get("HOME_ASSISTANT_TOKEN", "").strip()

    def status(self) -> dict[str, Any]:
        enabled = os.environ.get("ZENO_HOME_ASSISTANT_ENABLED", "").casefold() in {"1", "true", "yes", "on"}
        configured = bool(self.base_url and self.token and urlparse(self.base_url).scheme in {"http", "https"})
        return {"state": "STANDBY" if enabled and configured else ("DEGRADED" if enabled else "DISABLED"),
                "enabled": enabled, "configured": configured, "token": "[CONFIGURED]" if self.token else "[MISSING]",
                "security_sensitive": ("lock.unlock", "alarm_control_panel.alarm_disarm", "cover.open_cover")}

    def read_states(self) -> dict[str, Any]:
        status = self.status()
        if not status["enabled"] or not status["configured"]:
            return {"ok": False, "reason": "Home Assistant is disabled or unconfigured"}
        try:
            response = requests.get(f"{self.base_url}/api/states", headers={"Authorization": f"Bearer {self.token}"}, timeout=5)
            response.raise_for_status()
            values = response.json()
            return {"ok": True, "states": values[:500] if isinstance(values, list) else values}
        except Exception as exc:
            return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
