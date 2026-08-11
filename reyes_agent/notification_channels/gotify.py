from __future__ import annotations

import os

import requests

from reyes_agent.security.secrets import manager as secrets
from .common import safe_payload, valid_endpoint


_PRIORITY = {"INFO": 3, "SUCCESS": 4, "WARNING": 6, "ERROR": 8, "APPROVAL_REQUIRED": 9}


def status() -> dict:
    url = os.environ.get("ZENO_GOTIFY_URL", "").strip()
    token = secrets.source_of("GOTIFY_TOKEN").found
    if not url:
        return {"state": "NOT_CONFIGURED", "configured": False, "detail": "ZENO_GOTIFY_URL missing"}
    if not token:
        return {"state": "AUTH_REQUIRED", "configured": True, "detail": "GOTIFY_TOKEN missing"}
    valid, reason = valid_endpoint(url)
    return {"state": "STANDBY" if valid else "FAILED", "configured": True,
            "authenticated": token, "detail": "configured; delivery is tested only on a real send" if valid else reason}


def send(title: str, summary: str, severity: str, source: str, task_id: str = "") -> dict:
    state = status()
    if state["state"] != "STANDBY":
        return {"ok": False, **state}
    payload = safe_payload(title, summary, severity, source, task_id)
    url = os.environ["ZENO_GOTIFY_URL"].rstrip("/") + "/message"
    try:
        response = requests.post(url, headers={"X-Gotify-Key": secrets.get("GOTIFY_TOKEN")},
                                 json={"title": payload["title"], "message": payload["summary"],
                                       "priority": _PRIORITY[payload["severity"]]}, timeout=8)
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        ok = 200 <= response.status_code < 300 and bool(body.get("id"))
        return {"ok": ok, "state": "COMPLETED" if ok else "FAILED", "provider": "gotify",
                "status_code": response.status_code,
                "evidence": {"provider_message_id": str(body.get("id") or "")[:80]}}
    except requests.RequestException as exc:
        return {"ok": False, "state": "OFFLINE", "provider": "gotify", "reason": type(exc).__name__}
