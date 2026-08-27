"""Standalone Instagram OAuth callback service.

This is the small, internet-facing piece of the Instagram connection: the
Cloudflare Quick Tunnel (or a stable HTTPS URL later) forwards to it, it
receives Meta's redirect, and it hands the code to
`reyes_agent.social.instagram_login.handle_callback` for the server-side
exchange. It deliberately runs on its own port instead of ZENO's main app, so
exposing the OAuth callback to the internet never exposes ZENO's control
surface.

    python -m reyes_agent.social.instagram_callback_server

It binds to 127.0.0.1 on INSTAGRAM_CALLBACK_PORT (default 8765). cloudflared
connects to it as a local client. No token is ever printed or written to a
log -- only a masked, one-line status.
"""

from __future__ import annotations

import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from reyes_agent import config
from reyes_agent.social import instagram_login

CALLBACK_PATH = "/auth/instagram/callback"


def _page(title: str, body: str) -> bytes:
    return (f"<!doctype html><meta charset='utf-8'>"
            f"<title>{html.escape(title)}</title>"
            f"<div style='font-family:system-ui;max-width:34rem;margin:4rem auto;"
            f"line-height:1.5'><h1>{html.escape(title)}</h1>{body}</div>"
            ).encode("utf-8")


def _render(result: dict) -> tuple[int, bytes]:
    """Turn a handle_callback result into (status_code, html). No token ever."""
    if result.get("ok"):
        user = html.escape(str(result.get("username") or "your account"))
        return 200, _page(
            "ZENO Instagram Connected",
            f"<p><b>Instagram connected: @{user}</b></p>"
            f"<p>Token status: valid. You can close this page and tell ZENO to "
            f"check its Instagram.</p>")
    reason = html.escape(str(result.get("error") or "Unknown error"))
    return 400, _page(
        "Instagram Connection Failed",
        f"<p>{reason}</p><p>Nothing was stored. You can close this page and "
        f"try connecting again.</p>")


class _Handler(BaseHTTPRequestHandler):
    server_version = "ZENO-IG/1.0"

    def do_GET(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return
        params = parse_qs(parsed.query)
        result = instagram_login.handle_callback(
            code=(params.get("code") or [""])[0],
            error=(params.get("error") or [""])[0],
            error_description=(params.get("error_description") or [""])[0],
            state=(params.get("state") or [""])[0])
        status, page = _render(result)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page)

    def log_message(self, *_args) -> None:  # noqa: D401 -- silence default logging
        """Silence the default per-request stderr line; it could echo the URL
        (which carries the code). We print our own masked status instead."""


def serve(port: int | None = None) -> None:
    port = int(port or config.INSTAGRAM_CALLBACK_PORT)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    print(f"ZENO Instagram callback service on http://127.0.0.1:{port}{CALLBACK_PATH}")
    print(f"Redirect URI configured: {config.INSTAGRAM_REDIRECT_URI or '(unset!)'}")
    print("Waiting for Meta's redirect. Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    serve()
