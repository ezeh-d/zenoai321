"""One bounded failure taxonomy shared by production-facing subsystems."""

from __future__ import annotations

PROVIDER_RATE_LIMIT = "PROVIDER_RATE_LIMIT"
NETWORK_OFFLINE = "NETWORK_OFFLINE"
AUTH_EXPIRED = "AUTH_EXPIRED"
DEVICE_DISCONNECTED = "DEVICE_DISCONNECTED"
MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
TOOL_TIMEOUT = "TOOL_TIMEOUT"
ELEMENT_NOT_FOUND = "ELEMENT_NOT_FOUND"
PERMISSION_DENIED = "PERMISSION_DENIED"
SERVICE_CRASHED = "SERVICE_CRASHED"
INVALID_REQUEST = "INVALID_REQUEST"
UNKNOWN_FAILURE = "UNKNOWN_FAILURE"

ALL = {
    PROVIDER_RATE_LIMIT, NETWORK_OFFLINE, AUTH_EXPIRED, DEVICE_DISCONNECTED,
    MODEL_UNAVAILABLE, TOOL_TIMEOUT, ELEMENT_NOT_FOUND, PERMISSION_DENIED,
    SERVICE_CRASHED, INVALID_REQUEST, UNKNOWN_FAILURE,
}


def classify(message: object, *, status_code: int = 0) -> str:
    value = str(message or "").casefold()
    if status_code == 429 or "rate limit" in value or "too many requests" in value:
        return PROVIDER_RATE_LIMIT
    if status_code in {401, 403} or any(marker in value for marker in (
        "api key", "authentication", "unauthorized", "forbidden", "credential",
        "token expired", "session expired",
    )):
        return AUTH_EXPIRED
    if any(marker in value for marker in ("permission denied", "blocked by policy", "refused")):
        return PERMISSION_DENIED
    if any(marker in value for marker in ("timed out", "timeout", "deadline exceeded")):
        return TOOL_TIMEOUT
    if any(marker in value for marker in (
        "network", "connection", "dns", "name resolution", "offline", "unreachable",
    )):
        return NETWORK_OFFLINE
    if any(marker in value for marker in ("element not found", "no element", "nothing matches")):
        return ELEMENT_NOT_FOUND
    if any(marker in value for marker in ("device disconnected", "no device", "adb unavailable")):
        return DEVICE_DISCONNECTED
    if status_code >= 500 or any(marker in value for marker in ("service crashed", "process exited")):
        return SERVICE_CRASHED
    if any(marker in value for marker in ("model not found", "model unavailable", "provider unavailable")):
        return MODEL_UNAVAILABLE
    if any(marker in value for marker in ("bad input", "invalid request", "required field")):
        return INVALID_REQUEST
    return UNKNOWN_FAILURE
