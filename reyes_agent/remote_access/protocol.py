"""The wire format between the companion and ZENO.

One envelope in, one envelope out, both carrying `request_id` so a phone can
correlate a reply with what it asked and so an audit entry can be traced end
to end. Versioned as `v1` because the mobile companion is built by someone
else and a silent shape change would break their app in the field.

Nothing here touches ZENO internals. The companion sees a message, a status
and typed events -- never a tool name, a file path it did not ask about, or
an internal task object.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

VERSION = "v1"

# --- request types -------------------------------------------------------
COMMAND = "command"          # natural language, routed to the one ZENO brain
STATUS = "status"            # is the desktop there, what is it doing
PING = "ping"

# --- response statuses ---------------------------------------------------
SUCCESS = "success"
ERROR = "error"
DENIED = "denied"            # policy refused it
RATE_LIMITED = "rate_limited"
PENDING = "pending"          # accepted, still running -- watch the socket

# --- connection states ---------------------------------------------------
ONLINE = "ONLINE"
OFFLINE = "OFFLINE"
CONNECTING = "CONNECTING"
RECONNECTING = "RECONNECTING"
DEGRADED = "DEGRADED"
CONNECTION_STATES = (ONLINE, OFFLINE, CONNECTING, RECONNECTING, DEGRADED)

_MAX_MESSAGE = 4000


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


@dataclass
class Request:
    request_id: str
    device_id: str
    type: str
    message: str = ""
    timestamp: str = field(default_factory=now)

    @classmethod
    def parse(cls, payload: Any, *, device_id: str) -> tuple["Request | None", str]:
        """(request, error). Validation happens here, once, for every entry
        point -- HTTP and WebSocket share it so they cannot drift apart."""
        if not isinstance(payload, dict):
            return None, "the request body must be a JSON object"
        kind = str(payload.get("type") or COMMAND).strip().lower()
        if kind not in {COMMAND, STATUS, PING}:
            return None, f"unknown request type '{kind}'"
        message = str(payload.get("message") or "").strip()
        if kind == COMMAND and not message:
            return None, "a command needs a message"
        if len(message) > _MAX_MESSAGE:
            return None, f"message exceeds {_MAX_MESSAGE} characters"
        request_id = str(payload.get("request_id") or "").strip()[:64] or new_request_id()
        return cls(request_id=request_id, device_id=device_id, type=kind, message=message), ""

    def as_dict(self) -> dict[str, Any]:
        return {"request_id": self.request_id, "device_id": self.device_id,
                "type": self.type, "message": self.message, "timestamp": self.timestamp}


@dataclass
class Response:
    request_id: str
    status: str
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=now)

    def as_dict(self) -> dict[str, Any]:
        body = {"request_id": self.request_id, "status": self.status,
                "message": self.message, "timestamp": self.timestamp, "version": VERSION}
        if self.data:
            body["data"] = self.data
        return body

    @property
    def http_status(self) -> int:
        return {SUCCESS: 200, PENDING: 202, DENIED: 403,
                RATE_LIMITED: 429, ERROR: 400}.get(self.status, 200)


def ok(request_id: str, message: str = "", **data: Any) -> Response:
    return Response(request_id, SUCCESS, message, data)


def denied(request_id: str, reason: str, category: str = "") -> Response:
    return Response(request_id, DENIED, reason, {"category": category} if category else {})


def failed(request_id: str, reason: str) -> Response:
    return Response(request_id, ERROR, reason)


def limited(request_id: str, retry_after: float, bucket: str = "") -> Response:
    return Response(request_id, RATE_LIMITED,
                    f"Too many requests. Try again in {retry_after:.0f}s.",
                    {"retry_after": round(retry_after, 1), "bucket": bucket})


# --- event names the socket emits ---------------------------------------
# Kept as a closed set so the companion developer can switch on them.
EVENTS = (
    "connected", "heartbeat", "reply", "task", "agent", "notification",
    "website", "status", "error",
)

# Task states a phone may be shown. Mapped from the internal engines rather
# than exposing them, so an internal rename cannot break the app.
TASK_STATES = ("queued", "thinking", "working", "waiting", "testing",
               "completed", "failed", "cancelled")
WEBSITE_STATES = ("planning", "coding", "building", "fixing", "preview_ready",
                  "completed", "failed")


def task_event(task_id: str, state: str, detail: str = "", percent: int | None = None) -> dict[str, Any]:
    return {"type": "task", "task_id": task_id, "state": state,
            "detail": detail[:300], "percent": percent, "timestamp": now()}


def website_event(project: str, state: str, detail: str = "", url: str = "") -> dict[str, Any]:
    return {"type": "website", "project": project, "state": state,
            "detail": detail[:300], "preview_url": url, "timestamp": now()}


def notification_event(title: str, body: str = "", level: str = "info") -> dict[str, Any]:
    return {"type": "notification", "title": title[:120], "body": body[:400],
            "level": level, "timestamp": now()}
