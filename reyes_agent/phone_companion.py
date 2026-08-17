"""Narrow local interface to the one running ZENO core.

This module contains no model, agent, memory store, microphone listener or
task runtime of its own.  It only composes truthful snapshots from the
existing systems for the authenticated phone surface.
"""
from __future__ import annotations

import threading
from typing import Any

OUTPUT_AUTO, OUTPUT_PHONE, OUTPUT_PC, OUTPUT_BOTH, OUTPUT_HEADSET = (
    "AUTO", "PHONE", "PC", "BOTH", "HEADSET",
)
OUTPUTS = {OUTPUT_AUTO, OUTPUT_PHONE, OUTPUT_PC, OUTPUT_BOTH, OUTPUT_HEADSET}
_output_lock = threading.Lock()
_outputs: dict[str, str] = {}


def pairing_offer(mode: str = "", *, all_routes: bool = True) -> dict[str, Any]:
    """Create one single-use token reachable through Wi-Fi and/or hotspot."""
    from reyes_agent.phone_security import get_phone_security
    from reyes_agent.remote_mic import pairing, routes

    selector = routes.selector()
    wanted = (mode or "AUTO").strip().upper()
    ready = [item for item in selector.routes() if item.health == routes.READY]
    if wanted != routes.AUTO:
        ready = [item for item in ready if item.mode == wanted]
    if not ready:
        found = selector.routes(probe=False)
        return {"ok": False, "reason": (
            "No local Phone Companion route is listening. Keep the laptop on Wi-Fi "
            "or enable Windows Mobile Hotspot, then retry."),
            "routes": [item.as_dict() for item in found]}

    pair = get_phone_security().create_pair()
    offers = []
    for route in ready if all_routes else ready[:1]:
        url = f"{route.origin}/companion?token={pair['token']}"
        offers.append({"mode": route.mode, "label": route.label, "url": url,
                       "origin": route.origin, "ipv4": route.ipv4,
                       "adapter": route.adapter_name, "health": route.health,
                       "qr_png": pairing._qr(url)})
    primary = offers[0]
    return {"ok": True, **primary, "offers": offers,
            "manual_code": pair["manual_code"],
            "expires_at": pair["expires_at"], "port": routes.PORT,
            "secure_context_note": (
                "Microphone and WebAuthn are attempted only when Chrome reports a secure context. "
                "For local HTTP, configure Chrome's exact-origin development exception."),
            "shared_token": "Every QR carries the same short-lived single-use token."}


def route_for_peer(peer_ip: str) -> dict[str, Any] | None:
    from reyes_agent.remote_mic import routes

    route = routes.selector().route_for_peer(peer_ip)
    return route.as_dict() if route else None


def set_audio_output(device_id: str, output: str) -> str:
    value = str(output or OUTPUT_AUTO).strip().upper()
    if value not in OUTPUTS:
        raise ValueError("Audio output must be AUTO, PHONE, PC, BOTH or HEADSET.")
    with _output_lock:
        _outputs[device_id] = value
    return value


def audio_output(device_id: str) -> str:
    with _output_lock:
        return _outputs.get(device_id, OUTPUT_AUTO)


def tasks(limit: int = 20) -> list[dict[str, Any]]:
    """Real active/recent work only; no invented percentages."""
    output: list[dict[str, Any]] = []
    try:
        from reyes_agent import task_engine

        for item in task_engine.active()[:limit]:
            output.append({"id": item.get("task_id", ""),
                           "name": item.get("project_name") or item.get("task_name") or "Task",
                           "state": item.get("state", "RUNNING"),
                           "progress": item.get("progress"), "kind": "task",
                           "cancellable": True})
    except Exception:
        pass
    try:
        from reyes_agent.missions import manager, store

        terminal = set(getattr(manager, "TERMINAL", ()))
        for item in store.list_missions():
            if len(output) >= limit:
                break
            output.append({"id": item.get("mission_id", ""),
                           "name": item.get("goal") or item.get("title") or "Mission",
                           "state": item.get("state", ""), "progress": None,
                           "kind": "mission", "cancellable": item.get("state") not in terminal})
    except Exception:
        pass
    return output[:limit]


def cancel(task_id: str) -> bool:
    try:
        from reyes_agent import task_engine

        if task_engine.cancel(task_id, "Cancelled from the authenticated Phone Companion"):
            return True
    except Exception:
        pass
    try:
        from reyes_agent.missions import manager

        return manager.cancel(task_id, "Cancelled from the authenticated Phone Companion")
    except Exception:
        return False


def health() -> dict[str, Any]:
    from reyes_agent.remote_mic import get_remote_mic_runtime, routes

    route_state = routes.status()
    mic = get_remote_mic_runtime().status()
    return {"state": "ONLINE" if route_state["state"] == "ONLINE" else "DEGRADED",
            "transport": "LOCAL_NETWORK", "network": route_state,
            "microphone": {key: mic.get(key) for key in
                           ("state", "available", "received_frames", "last_error")},
            "cloud_required": False, "domain_required": False}

