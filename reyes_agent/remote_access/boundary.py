"""Fail-closed boundary between loopback desktop APIs and remote clients."""

from __future__ import annotations

from collections.abc import Mapping

_REMOTE_HEADERS = (
    "cf-connecting-ip", "true-client-ip", "x-forwarded-for", "x-real-ip",
)
_PUBLIC_REMOTE_PREFIXES = (
    "/phone", "/pair", "/api/v1/", "/api/phone/pair/", "/api/phone/login/",
    "/api/phone/status", "/api/phone/command", "/ws/phone",
)


def is_forwarded_remote(headers: Mapping[str, str]) -> bool:
    normalized = {str(key).casefold(): str(value).strip() for key, value in headers.items()}
    return any(normalized.get(name) for name in _REMOTE_HEADERS)


def remote_path_allowed(path: str) -> bool:
    value = "/" + str(path or "").lstrip("/")
    if value.startswith("/api/phone/admin"):
        return False
    return any(value == prefix.rstrip("/") or value.startswith(prefix)
               for prefix in _PUBLIC_REMOTE_PREFIXES)


def decision(path: str, headers: Mapping[str, str], *, enabled: bool) -> tuple[bool, int, str]:
    """Return ``(allowed, status, reason)`` for an HTTP/WS request."""
    if not is_forwarded_remote(headers):
        return True, 200, "loopback request"
    if not enabled:
        return False, 503, "Remote access is disabled on this ZENO."
    if not remote_path_allowed(path):
        return False, 403, "This desktop-only ZENO endpoint is not exposed remotely."
    return True, 200, "authenticated remote surface"
