"""Finite authenticated n8n API calls, disabled unless explicitly configured."""
from __future__ import annotations

import os
from typing import Any

import requests


def status() -> dict[str, Any]:
    enabled = os.environ.get("ZENO_N8N_ENABLED", "").casefold() in {"1", "true", "yes", "on"}
    configured = bool(os.environ.get("ZENO_N8N_WEBHOOK_URL", "").strip() and os.environ.get("ZENO_N8N_WEBHOOK_TOKEN", "").strip())
    return {"state": "STANDBY" if enabled and configured else ("DEGRADED" if enabled else "DISABLED"),
            "enabled": enabled, "configured": configured,
            "token": "[CONFIGURED]" if os.environ.get("ZENO_N8N_WEBHOOK_TOKEN") else "[MISSING]"}


def trigger_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    state = status()
    if not state["enabled"] or not state["configured"]:
        return {"ok": False, "reason": "n8n is disabled or unconfigured"}
    url = os.environ["ZENO_N8N_WEBHOOK_URL"].strip()
    if not (url.casefold().startswith("https://") or url.casefold().startswith("http://127.0.0.1")
            or url.casefold().startswith("http://localhost")):
        return {"ok": False, "reason": "n8n webhook must use HTTPS or loopback"}
    try:
        response = requests.post(url,
                                 headers={"Authorization": f"Bearer {os.environ['ZENO_N8N_WEBHOOK_TOKEN']}"},
                                 json=payload, timeout=10)
        response.raise_for_status()
        try:
            result = response.json()
        except ValueError:
            result = response.text[:4000]
        return {"ok": True, "status_code": response.status_code, "result": result}
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
