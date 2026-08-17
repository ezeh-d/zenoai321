"""Fail-closed boundary between loopback desktop APIs and remote clients."""

from __future__ import annotations

from collections.abc import Mapping
import ipaddress

_REMOTE_HEADERS = (
    "cf-connecting-ip", "true-client-ip", "x-forwarded-for", "x-real-ip",
    # Tailscale Serve terminates HTTPS and identifies the tailnet caller
    # while proxying to ZENO's loopback-only HTTP server.
    "tailscale-user-login", "tailscale-user-name",
)
_PUBLIC_REMOTE_PREFIXES = (
    "/phone", "/pair", "/mic", "/api/v1/", "/api/phone/pair/", "/api/phone/login/",
    "/api/phone/status", "/api/phone/command", "/api/phone/mic/",
    "/api/phone/companion/", "/api/phone/webauthn/", "/api/phone/tasks",
    "/api/phone/devices", "/api/phone/audio/", "/api/phone/session/",
    "/api/phone/health", "/api/phone/tts", "/api/phone/approvals",
    "/ws/phone",
)
_PUBLIC_REMOTE_EXACT = {
    "/", "/chat", "/companion", "/phone-manifest.json", "/phone-sw.js",
    "/favicon.ico",
}
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def is_forwarded_remote(headers: Mapping[str, str]) -> bool:
    normalized = {str(key).casefold(): str(value).strip() for key, value in headers.items()}
    return any(normalized.get(name) for name in _REMOTE_HEADERS)


def is_direct_remote(client_host: str) -> bool:
    """Return true for a real non-loopback socket peer.

    The local phone listener has no reverse proxy, so it carries none of the
    forwarded headers used by Cloudflare/Tailscale.  Treating those requests
    as loopback exposed every desktop route on port 8768.  The socket peer is
    the authority for the direct-LAN case.
    """
    value = str(client_host or "").strip().split("%", 1)[0].casefold()
    if not value or value in _LOOPBACK:
        return False
    try:
        return not ipaddress.ip_address(value).is_loopback
    except ValueError:
        return True


def remote_path_allowed(path: str) -> bool:
    value = "/" + str(path or "").lstrip("/")
    if value.startswith("/api/phone/admin"):
        return False
    if value in _PUBLIC_REMOTE_EXACT:
        return True
    return any(value == prefix.rstrip("/") or value.startswith(prefix)
               for prefix in _PUBLIC_REMOTE_PREFIXES)


def decision(path: str, headers: Mapping[str, str], *, enabled: bool,
             client_host: str = "", local_enabled: bool = False) -> tuple[bool, int, str]:
    """Return ``(allowed, status, reason)`` for an HTTP/WS request."""
    forwarded = is_forwarded_remote(headers)
    direct = is_direct_remote(client_host)
    if not forwarded and not direct:
        return True, 200, "loopback request"
    if forwarded and not enabled:
        return False, 503, "Remote access is disabled on this ZENO."
    if direct and not local_enabled:
        return False, 503, "Local Phone Companion access is disabled on this ZENO."
    if not remote_path_allowed(path):
        return False, 403, "This desktop-only ZENO endpoint is not exposed remotely."
    return True, 200, "authenticated local companion surface" if direct else "authenticated remote surface"
