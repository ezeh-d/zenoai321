"""Compatibility launcher for ZENO's real loopback web backend.

The former development bridge bound ``0.0.0.0``, allowed wildcard CORS,
accepted unauthenticated chat commands, and returned a hardcoded ONLINE
status. That server is intentionally retired. Remote access now goes only
through the authenticated Cloudflare/WebAuthn companion routes mounted by
``reyes_agent.web``; the desktop dashboard remains loopback-only.

Prefer: ``python -m reyes_agent.web``
"""

from __future__ import annotations


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    normalized = str(host or "").strip().casefold()
    if normalized not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError(
            "ZENO's desktop API is loopback-only. Use the authenticated Phone "
            "Companion tunnel for remote access."
        )
    from reyes_agent.runtime_environment import require_safe_startup

    require_safe_startup()
    import uvicorn

    from reyes_agent.web import app

    uvicorn.run(app, host="127.0.0.1", port=int(port), log_level="warning")


if __name__ == "__main__":
    serve()
