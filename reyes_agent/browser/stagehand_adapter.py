"""Lazy Stagehand bridge.

Stagehand is a TypeScript library. ZENO does not download it at runtime. A
configured local bridge may expose ``observe``, ``act`` and ``extract`` over
loopback/private HTTPS; otherwise the adapter is honestly NOT_CONFIGURED and
the router falls back to existing Playwright/browser-use paths.
"""
from __future__ import annotations

import os
import urllib.parse
from typing import Any

import requests

from reyes_agent.security.secrets import manager as secrets


class StagehandAdapter:
    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or os.environ.get("ZENO_STAGEHAND_URL", "")).strip().rstrip("/")

    def status(self) -> dict[str, Any]:
        if not self.base_url:
            return {"state": "NOT_CONFIGURED", "configured": False, "available": False,
                    "detail": "ZENO_STAGEHAND_URL is not configured"}
        parsed = urllib.parse.urlparse(self.base_url)
        safe = parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"})
        return {"state": "STANDBY" if safe else "FAILED", "configured": True, "available": safe,
                "detail": "lazy bridge configured" if safe else "Stagehand bridge must be loopback HTTP or HTTPS"}

    def _call(self, operation: str, payload: dict[str, Any], timeout_s: float = 20.0) -> dict[str, Any]:
        state = self.status()
        if not state["available"]:
            return {"ok": False, **state}
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        token = secrets.get("STAGEHAND_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = requests.post(f"{self.base_url}/v1/{operation}", json=payload, headers=headers,
                                     timeout=max(2.0, min(timeout_s, 30.0)))
            body = response.json()
        except (requests.RequestException, ValueError) as exc:
            return {"ok": False, "state": "OFFLINE", "operation": operation, "reason": type(exc).__name__}
        ok = 200 <= response.status_code < 300 and body.get("ok") is not False
        return {"ok": ok, "state": "COMPLETED" if ok else "FAILED", "operation": operation,
                "status_code": response.status_code, "result": body if ok else None,
                "reason": "bridge confirmed operation" if ok else str(body.get("error") or "bridge rejected operation")[:240]}

    def observe(self, instruction: str, *, url: str = "") -> dict[str, Any]:
        return self._call("observe", {"instruction": instruction, "url": url})

    def act(self, instruction: str, *, action: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._call("act", {"instruction": instruction, "action": action or {}})

    def extract(self, instruction: str, *, schema: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._call("extract", {"instruction": instruction, "schema": schema or {}})
