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


# --- recovery semantics -----------------------------------------------------
# A bare category is only half the story; recovery depends on the class. These
# two sets and the hint table turn a label into a decision the executor, the
# provider retry loop and the model can all act on.
#
#   retryable  -- the SAME call may succeed on a later attempt (backoff helps).
#   transient  -- environmental/temporary, not a bad request from the caller.
RETRYABLE = {
    PROVIDER_RATE_LIMIT, NETWORK_OFFLINE, TOOL_TIMEOUT, SERVICE_CRASHED,
    MODEL_UNAVAILABLE, DEVICE_DISCONNECTED,
}
# Auth is fixable, but never by a blind retry -- it needs a re-auth first.
TRANSIENT = RETRYABLE | {AUTH_EXPIRED}

RECOVERY = {
    PROVIDER_RATE_LIMIT: "Back off and retry; the provider is rate limiting.",
    NETWORK_OFFLINE: "Check the network connection, then retry.",
    AUTH_EXPIRED: "Re-authenticate the provider; the credential expired.",
    DEVICE_DISCONNECTED: "Reconnect the target device, then retry.",
    MODEL_UNAVAILABLE: "Fail over to another model or provider.",
    TOOL_TIMEOUT: "Retry with a longer timeout or a smaller step.",
    ELEMENT_NOT_FOUND: "Re-locate the target (the UI likely changed); do not blind-retry.",
    PERMISSION_DENIED: "Obtain the missing permission; do not retry as-is.",
    SERVICE_CRASHED: "Restart the service, then retry.",
    INVALID_REQUEST: "Fix the arguments; retrying them unchanged will fail again.",
    UNKNOWN_FAILURE: "Inspect the error; no automatic recovery is known.",
}


def is_retryable(category: str) -> bool:
    """True when re-issuing the identical call may succeed later."""
    return category in RETRYABLE


def classify_exception(exc: BaseException | None, *, status_code: int = 0) -> str:
    """Classify from an exception's TYPE first, then fall back to its message.

    Type matching is sturdier than scanning a message string: a ``TimeoutError``
    is a timeout whatever its wording. Where the type is generic (``ValueError``)
    the message can still promote it to a more specific class. Never raises.
    """
    if exc is None:
        return classify("", status_code=status_code)
    # These OSError subclasses carry their meaning in the type itself.
    if isinstance(exc, TimeoutError):
        return TOOL_TIMEOUT
    if isinstance(exc, PermissionError):
        return PERMISSION_DENIED
    if isinstance(exc, ConnectionError):
        return NETWORK_OFFLINE
    by_text = classify(exc, status_code=status_code)
    if by_text != UNKNOWN_FAILURE:
        return by_text
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return INVALID_REQUEST
    # A provider error that flagged itself retryable but named no cause is most
    # usefully treated as a transient service blip rather than a hard unknown.
    if getattr(exc, "retryable", None) is True:
        return SERVICE_CRASHED
    return UNKNOWN_FAILURE


def describe(category: str) -> dict:
    """The recovery semantics of a category, as a plain dict."""
    category = category if category in ALL else UNKNOWN_FAILURE
    return {
        "category": category,
        "retryable": category in RETRYABLE,
        "transient": category in TRANSIENT,
        "recovery": RECOVERY.get(category, RECOVERY[UNKNOWN_FAILURE]),
    }


def explain(message: object = "", *, exc: BaseException | None = None,
            status_code: int = 0) -> dict:
    """One structured error: the category plus its recovery semantics, derived
    from an exception (preferred) or a message string. Never raises."""
    try:
        category = (classify_exception(exc, status_code=status_code)
                    if exc is not None
                    else classify(message, status_code=status_code))
    except Exception:  # noqa: BLE001 -- classification itself must never fail
        category = UNKNOWN_FAILURE
    return describe(category)
