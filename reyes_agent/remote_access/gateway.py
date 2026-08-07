"""The one door between a remote device and ZENO.

EVERY remote request lands here, and this module's only real job is to run
the checks and then hand the message to the SAME `run_agent` the desktop
uses. There is deliberately no remote command implementation: a second
router would be a second ZENO that drifts from the first, and the owner
would end up with an assistant that behaves differently depending on which
device they picked up.

    phone -> gateway -> _conversation_turn -> run_agent -> tools/agents
                          (the existing worker pool, the existing brain)

WHAT THE GATEWAY ADDS
---------------------
* device session check (delegated to phone_security -- not reimplemented)
* rate limit
* category policy (SAFE/CONTROL/SENSITIVE/FINANCIAL)
* an audit entry that never contains a token
* connection status

FAILURE ISOLATION
-----------------
Nothing in here may take the desktop down. Every path returns an envelope,
including the unexpected-exception path, and remote access being broken or
switched off leaves local ZENO exactly as it was.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

from reyes_agent.remote_access import policy, protocol

# Bounded audit ring. The durable record goes to the Event Bus; this is the
# recent view the owner and the API can read cheaply.
_MAX_AUDIT = 400
_lock = threading.Lock()
_audit: deque[dict[str, Any]] = deque(maxlen=_MAX_AUDIT)
_last_seen: dict[str, float] = {}
_connected: set[str] = set()


# --- audit ---------------------------------------------------------------

def record(device_id: str, request_id: str, category: str, action: str,
           result: str, detail: str = "") -> None:
    """Audit one remote action.

    Never records tokens, session cookies, credentials or raw biometrics --
    only who, what category, which request, and how it ended.
    """
    entry = {
        "timestamp": protocol.now(),
        "device_id": str(device_id or "")[:64],
        "request_id": str(request_id or "")[:64],
        "category": category,
        "action": str(action or "")[:160],
        "result": result,
        "detail": str(detail or "")[:300],
    }
    with _lock:
        _audit.append(entry)
    try:
        from reyes_agent import event_bus

        event_bus.publish("remote.action", entry, source="remote_access",
                          correlation_id=entry["request_id"])
    except Exception:  # noqa: BLE001 -- audit must never break a request
        pass


def audit_log(limit: int = 50) -> list[dict[str, Any]]:
    with _lock:
        return list(_audit)[-max(1, min(limit, _MAX_AUDIT)):]


# --- connection status ---------------------------------------------------

def mark_seen(device_id: str, *, connected: bool | None = None) -> None:
    with _lock:
        _last_seen[str(device_id)] = time.time()
        if connected is True:
            _connected.add(str(device_id))
        elif connected is False:
            _connected.discard(str(device_id))
        while len(_last_seen) > 200:
            _last_seen.pop(next(iter(_last_seen)), None)


def connection_status() -> dict[str, Any]:
    """What the phone should display about the DESKTOP's reachability.

    ONLINE means this process is running and its brain is reachable. It is
    reported from real state -- a degraded model router or a stopped tunnel
    shows DEGRADED rather than a cheerful green light.
    """
    from reyes_agent import config
    from reyes_agent.remote_access import domains

    state = protocol.ONLINE
    reasons: list[str] = []

    if not bool(getattr(config, "REMOTE_ACCESS_ENABLED", False)):
        state = protocol.OFFLINE
        reasons.append("remote access is disabled in configuration")
    elif not domains.configured():
        state = protocol.DEGRADED
        reasons.append("no public domain configured yet")

    try:
        from reyes_agent import model_router

        healthy = [name for name, ok in model_router.available_providers().items()
                   if ok and model_router.breaker_state(name) != model_router.OPEN]
        if not healthy:
            state = protocol.DEGRADED
            reasons.append("no healthy model provider")
    except Exception:  # noqa: BLE001
        pass

    try:
        from reyes_agent.cloudflare_tunnel import get_cloudflare_tunnel

        tunnel = get_cloudflare_tunnel().status()
    except Exception:  # noqa: BLE001
        tunnel = {"configured": False, "running": False}
    if tunnel.get("configured") and not tunnel.get("running") and state == protocol.ONLINE:
        state = protocol.DEGRADED
        reasons.append("the tunnel is configured but not running")

    with _lock:
        connected = len(_connected)
    return {"state": state, "reasons": reasons, "tunnel": tunnel,
            "connected_devices": connected, "timestamp": protocol.now(),
            "states": list(protocol.CONNECTION_STATES)}


# --- the routed command --------------------------------------------------

def handle(request: protocol.Request, *, scopes: set[str] | None = None,
           identity: str = "", timeout: float | None = None) -> protocol.Response:
    """Run one remote request through every check, then the real ZENO.

    Returns an envelope in ALL cases. A raised exception here would be a
    remote subsystem taking down a desktop request thread, which the brief
    forbids outright.
    """
    identity = identity or request.device_id
    mark_seen(request.device_id)

    if request.type == protocol.PING:
        return protocol.ok(request.request_id, "pong", **connection_status())
    if request.type == protocol.STATUS:
        return protocol.ok(request.request_id, "status", **connection_status())

    rate = policy.check_rate("command", identity)
    if not rate.allowed:
        record(request.device_id, request.request_id, "-", request.message,
               "rate_limited", f"bucket={rate.bucket}")
        return protocol.limited(request.request_id, rate.retry_after, rate.bucket)

    decision = policy.evaluate(request.message, scopes=scopes)
    if not decision.allowed:
        record(request.device_id, request.request_id, decision.category,
               request.message, "denied", decision.reason)
        return protocol.denied(request.request_id, decision.reason, decision.category)

    try:
        reply = _run_through_zeno(request, timeout=timeout)
    except TimeoutError:
        record(request.device_id, request.request_id, decision.category,
               request.message, "timeout")
        return protocol.Response(
            request.request_id, protocol.PENDING,
            "ZENO is still working on that. Watch the socket for the result.")
    except Exception as exc:  # noqa: BLE001 -- a remote failure is never a crash
        record(request.device_id, request.request_id, decision.category,
               request.message, "error", f"{type(exc).__name__}")
        return protocol.failed(request.request_id,
                               f"That could not be completed: {type(exc).__name__}")

    record(request.device_id, request.request_id, decision.category,
           request.message, "success")
    return protocol.ok(request.request_id, reply.get("reply", ""),
                       category=decision.category,
                       tools=[t.get("name") for t in reply.get("tool_calls", [])][:8])


def _run_through_zeno(request: protocol.Request, *, timeout: float | None = None) -> dict[str, Any]:
    """Submit to the EXISTING conversation path -- not a copy of it.

    Uses the same worker pool, the same history lock and the same
    `run_agent` as a typed desktop message, so a phone and the keyboard
    reach one assistant with one memory.
    """
    from reyes_agent import config
    from reyes_agent.web import _conversation_turn
    from reyes_agent.worker_pool import PRIORITY_BRAIN, get_worker_pool

    budget = timeout if timeout is not None else float(config.AI_REQUEST_TIMEOUT_S) + 30
    handle_ = get_worker_pool().submit(
        _conversation_turn, request.message,
        name=f"remote:{request.device_id[:8]}", priority=PRIORITY_BRAIN,
        timeout=budget + 30, with_context=True,
    )
    return handle_.result(budget)


def reset() -> None:
    """Test hook."""
    with _lock:
        _audit.clear()
        _last_seen.clear()
        _connected.clear()
