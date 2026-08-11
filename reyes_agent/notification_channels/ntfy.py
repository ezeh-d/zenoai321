from __future__ import annotations

import os
import urllib.parse

import requests

from reyes_agent.security.secrets import manager as secrets
from .common import safe_payload, valid_endpoint


_PRIORITY = {"INFO": "default", "SUCCESS": "default", "WARNING": "high",
             "ERROR": "urgent", "APPROVAL_REQUIRED": "urgent"}


def status() -> dict:
    base = os.environ.get("ZENO_NTFY_URL", "").strip()
    topic = os.environ.get("ZENO_NTFY_TOPIC", "").strip()
    if not base or not topic:
        return {"state": "NOT_CONFIGURED", "configured": False, "detail": "ZENO_NTFY_URL/topic missing"}
    valid, reason = valid_endpoint(base)
    return {"state": "STANDBY" if valid else "FAILED", "configured": True,
            "authenticated": secrets.source_of("NTFY_TOKEN").found,
            "detail": "configured; delivery is tested only on a real send" if valid else reason}


def send(title: str, summary: str, severity: str, source: str, task_id: str = "") -> dict:
    state = status()
    if state["state"] != "STANDBY":
        return {"ok": False, **state}
    payload = safe_payload(title, summary, severity, source, task_id)
    base = os.environ["ZENO_NTFY_URL"].rstrip("/")
    topic = urllib.parse.quote(os.environ["ZENO_NTFY_TOPIC"].strip(), safe="-_A-Za-z0-9")
    headers = {"Title": payload["title"], "Priority": _PRIORITY[payload["severity"]],
               "Tags": payload["severity"].casefold(), "Content-Type": "text/plain; charset=utf-8"}
    token = secrets.get("NTFY_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = requests.post(f"{base}/{topic}", data=payload["summary"].encode("utf-8"),
                                 headers=headers, timeout=8)
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        ok = 200 <= response.status_code < 300 and bool(body.get("id") or not body)
        return {"ok": ok, "state": "COMPLETED" if ok else "FAILED",
                "status_code": response.status_code, "provider": "ntfy",
                "evidence": {"provider_message_id": str(body.get("id") or "")[:80]}}
    except requests.RequestException as exc:
        return {"ok": False, "state": "OFFLINE", "provider": "ntfy", "reason": type(exc).__name__}
