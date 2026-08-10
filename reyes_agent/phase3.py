"""Lazy Phase 3 capability catalogue under the existing ZenoKernel.

This is a service *catalogue*, not a new scheduler or worker pool.  Optional
adapters are imported only by ``activate`` after an explicit feature request.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import threading
import time
from typing import Any

from reyes_agent.phase3_flags import INTEGRATIONS, catalogue

ONLINE, STANDBY, DISABLED, DEGRADED = "ONLINE", "STANDBY", "DISABLED", "DEGRADED"

_lock = threading.RLock()
_activated: dict[str, float] = {}
_errors: dict[str, str] = {}


_PACKAGE = {
    "litellm": "litellm", "graphiti": "graphiti_core", "sherpa": "sherpa_onnx",
    "docling": "docling", "e2b": "e2b", "langfuse": "langfuse",
    "phoenix": "phoenix", "pywinauto": "pywinauto",
}
_BINARY = {
    "openhands": "openhands", "scrcpy": "scrcpy", "kde_connect": "kdeconnect-cli",
    "local_llm": "ollama", "whisper_cpp": "whisper-cli", "opa": "opa",
}
_URL_ENV = {
    "screenpipe": "ZENO_SCREENPIPE_URL", "activitywatch": "ZENO_ACTIVITYWATCH_URL",
    "home_assistant": "HOME_ASSISTANT_URL", "n8n": "ZENO_N8N_WEBHOOK_URL",
}


def _available(key: str) -> tuple[bool, str]:
    if key == "home_assistant":
        ok = bool(os.environ.get("HOME_ASSISTANT_URL", "").strip()
                  and os.environ.get("HOME_ASSISTANT_TOKEN", "").strip())
        return ok, "Home Assistant URL and token configured" if ok else "Home Assistant URL/token not configured"
    if key == "n8n":
        ok = bool(os.environ.get("ZENO_N8N_WEBHOOK_URL", "").strip()
                  and os.environ.get("ZENO_N8N_WEBHOOK_TOKEN", "").strip())
        return ok, "n8n webhook and token configured" if ok else "n8n webhook/token not configured"
    package = _PACKAGE.get(key)
    if package:
        ok = importlib.util.find_spec(package) is not None
        return ok, f"Python package {package} {'installed' if ok else 'not installed'}"
    binary = _BINARY.get(key)
    if binary:
        path = shutil.which(binary)
        return bool(path), path or f"{binary} is not installed or not on PATH"
    env_name = _URL_ENV.get(key)
    if env_name:
        configured = bool(os.environ.get(env_name, "").strip())
        return configured, f"{env_name} {'configured' if configured else 'not configured'}"
    if key == "agent_device":
        path = shutil.which("adb")
        return bool(path), path or "ADB is not installed"
    if key == "silero_vad":
        ok = importlib.util.find_spec("torch") is not None
        return ok, "torch available" if ok else "Silero runtime not installed"
    return True, "implemented by an existing ZENO authority"


def status() -> dict[str, Any]:
    rows = []
    enabled_count = 0
    with _lock:
        activated = dict(_activated)
        errors = dict(_errors)
    for spec in INTEGRATIONS:
        available, detail = _available(spec.key)
        if not spec.enabled:
            state = DISABLED
        elif spec.key in errors:
            state, detail = DEGRADED, errors[spec.key]
        elif spec.key in activated or (available and not spec.heavy):
            state = ONLINE
        else:
            state = STANDBY if available else DEGRADED
        enabled_count += int(spec.enabled)
        rows.append({
            "key": spec.key, "label": spec.label, "flag": spec.flag,
            "classification": spec.classification, "strategy": spec.strategy,
            "enabled": spec.enabled, "available": available, "state": state,
            "heavy": spec.heavy, "detail": detail,
            "activated_at": activated.get(spec.key),
        })
    enabled_states = [row["state"] for row in rows if row["enabled"]]
    if any(state == DEGRADED for state in enabled_states):
        overall = DEGRADED
    elif any(state == STANDBY for state in enabled_states):
        overall = STANDBY
    elif any(state == ONLINE for state in enabled_states):
        overall = ONLINE
    else:
        overall = DISABLED
    return {"state": overall, "polling": False, "enabled": enabled_count,
            "total": len(rows), "services": rows}


def activate(key: str) -> dict[str, Any]:
    spec = catalogue().get(key)
    if spec is None:
        raise KeyError(f"Unknown Phase 3 integration '{key}'.")
    if not spec.enabled:
        return {"ok": False, "state": DISABLED, "reason": f"{spec.flag} is off"}
    available, detail = _available(key)
    if not available:
        with _lock:
            _errors[key] = detail
        return {"ok": False, "state": DEGRADED, "reason": detail}
    with _lock:
        _activated.setdefault(key, time.time())
        _errors.pop(key, None)
    try:
        from reyes_agent import event_bus
        event_bus.publish("service.activated", {"service": key}, source="phase3")
    except Exception:
        pass
    return {"ok": True, "state": ONLINE, "service": key, "detail": detail}


def register_with_kernel() -> None:
    """Register every optional long-lived capability without starting it."""
    from reyes_agent.kernel import STAGE_LAZY, get_kernel
    kernel = get_kernel()
    for spec in INTEGRATIONS:
        if not spec.heavy:
            continue
        stop = None
        if spec.key == "scrcpy":
            stop = lambda: __import__("reyes_agent.devices.android", fromlist=["get_bridge"]).get_bridge().stop()
        kernel.register_service(
            f"phase3:{spec.key}", stage=STAGE_LAZY,
            start=lambda key=spec.key: activate(key),
            stop=stop,
        )


_REQUEST_MARKERS = (
    "what was i working", "what did i do", "earlier", "yesterday", "this morning",
    "screen history", "activity history", "read this pdf", "read this document",
    "powerpoint", "spreadsheet", "extract the table", "knowledge graph",
    "show my phone", "android", "untrusted code", "sandbox", "engineering backend",
)


def relevant_request(text: str) -> bool:
    normalized = " ".join(str(text or "").casefold().split())
    return any(marker in normalized for marker in _REQUEST_MARKERS)


def episodic_request(text: str) -> bool:
    normalized = " ".join(str(text or "").casefold().split())
    return any(marker in normalized for marker in (
        "what was i working", "what did i do", "earlier", "yesterday", "this morning",
        "screen history", "activity history", "before opening", "continue what i was doing",
    ))
