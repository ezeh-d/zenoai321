from __future__ import annotations

import os

from . import gotify, ntfy


def provider_name() -> str:
    value = os.environ.get("ZENO_PUSH_PROVIDER", "").strip().casefold()
    return value if value in {"ntfy", "gotify"} else ""


def status() -> dict:
    selected = provider_name()
    if not selected:
        return {"state": "DISABLED", "provider": None, "detail": "ZENO_PUSH_PROVIDER is not set",
                "multiple_active": False}
    backend = ntfy if selected == "ntfy" else gotify
    result = backend.status()
    result.update(provider=selected, multiple_active=False)
    return result


def dispatch(title: str, summary: str, severity: str = "INFO", source: str = "zeno",
             task_id: str = "") -> dict:
    selected = provider_name()
    if not selected:
        return {"ok": False, "state": "DISABLED", "provider": None}
    backend = ntfy if selected == "ntfy" else gotify
    return backend.send(title, summary, severity, source, task_id)
