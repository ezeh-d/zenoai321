"""Standalone cloud edge for ZENO Anywhere.

This process contains authentication, trusted-device state and the durable
command queue.  It deliberately imports neither the agent brain nor desktop
automation.  The Windows connector polls it over outbound HTTPS, which means
deploying this service never opens the owner's PC to inbound traffic.

Production run (behind an HTTPS reverse proxy)::

    uvicorn reyes_agent.anywhere_gateway:app --host 0.0.0.0 --port 8080

The SQLite paths must point at persistent encrypted-at-rest storage on the
host.  For horizontally scaled deployment, replace DeviceLink and
OwnerAuthService storage with a transactional shared database first; SQLite
is intentionally single-instance for v1.
"""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from reyes_agent import config
from reyes_agent.auth import get_owner_auth
from reyes_agent.remote_access import (cloud_api, deployment, device_link,
                                       domains, web_push)

GATEWAY_VERSION = "1.0.0"
DEVICE_PROTOCOL_VERSION = "1.0.0"


def create_app(*, enabled: bool | None = None) -> FastAPI:
    """Create the isolated API application.

    ``enabled`` exists for deterministic tests.  Production always derives
    the value from ``REMOTE_ACCESS_ENABLED`` and therefore fails closed.
    """
    remote_enabled = (bool(config.REMOTE_ACCESS_ENABLED)
                      if enabled is None else bool(enabled))
    @asynccontextmanager
    async def lifespan(_application):
        yield
        try:
            web_push.shutdown_if_started()
        except Exception:
            pass

    application = FastAPI(
        title="ZENO Anywhere Gateway",
        version=GATEWAY_VERSION,
        lifespan=lifespan,
        docs_url="/docs" if domains.dev_mode() else None,
        redoc_url=None,
        openapi_url="/openapi.json" if domains.dev_mode() else None,
    )

    origins = domains.allowed_origins()
    if origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization", "X-Zeno-CSRF"],
            max_age=600,
        )

    @application.middleware("http")
    async def security_boundary(request: Request, call_next):
        # Health stays reachable to an external monitor.  Everything else is
        # closed when the deployment flag is absent or false.
        if not remote_enabled and request.url.path not in {"/health", "/ready"}:
            return JSONResponse({"detail": "Remote access is disabled."}, status_code=503)

        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        is_shell = request.url.path.startswith("/app") or request.url.path == "/zeno-config.js"
        response.headers["Permissions-Policy"] = (
            "camera=(self), microphone=(self), geolocation=(self), payment=(), usb=()"
            if is_shell else
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "connect-src 'self'; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'self'; "
            "form-action 'self'" if is_shell else
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
            "form-action 'none'")
        response.headers["Cache-Control"] = "no-store"
        forwarded = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
        if request.url.scheme == "https" or forwarded == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains")
        return response

    @application.get("/health")
    def health() -> dict[str, Any]:
        # No device names, addresses, queue contents or auth metadata on the
        # unauthenticated health endpoint.
        return {
            "service": "zeno-anywhere-gateway",
            "state": "ONLINE" if remote_enabled else "DISABLED",
            "version": GATEWAY_VERSION,
            "protocol_version": DEVICE_PROTOCOL_VERSION,
            "timestamp": time.time(),
        }

    @application.get("/ready")
    def ready() -> JSONResponse:
        provisioned = get_owner_auth().is_provisioned()
        preflight = deployment.preflight()
        code = 200 if remote_enabled and provisioned and preflight["ok"] else 503
        return JSONResponse({
            "ready": code == 200,
            "remote_enabled": remote_enabled,
            "owner_provisioned": provisioned,
            "deployment": preflight,
        }, status_code=code)

    # Optional same-origin owner shell. Netlify uses the same source files,
    # but serving them here gives operators a zero-CORS fallback and makes a
    # cloud host usable even before the static deployment is connected.
    static = Path(__file__).resolve().parent / "static"

    @application.get("/app")
    @application.get("/app/")
    def owner_app() -> FileResponse:
        return FileResponse(static / "app.html", headers={"Cache-Control": "no-store"})

    @application.get("/zeno-config.js")
    def owner_config() -> Response:
        return Response('window.ZENO_CONFIG = {"apiBaseUrl":""};\n',
                        media_type="text/javascript",
                        headers={"Cache-Control": "no-store"})

    @application.get("/app/manifest.webmanifest")
    def manifest() -> FileResponse:
        return FileResponse(static / "app" / "manifest.webmanifest",
                            media_type="application/manifest+json")

    @application.get("/app/sw.js")
    def service_worker() -> FileResponse:
        return FileResponse(static / "app" / "sw.js", media_type="text/javascript",
                            headers={"Cache-Control": "no-store",
                                     "Service-Worker-Allowed": "/app/"})

    @application.get("/app/icon-{size}.png")
    def icon(size: str) -> Response:
        if size not in {"192", "512"}:
            return JSONResponse({"detail": "No such icon."}, status_code=404)
        return FileResponse(static / "app" / f"icon-{size}.png", media_type="image/png")

    cloud_api.register(application)
    return application


app = create_app()


def deployment_diagnostics() -> dict[str, Any]:
    """Local/operator-only checks; never mounted as a public route."""
    return {
        "version": GATEWAY_VERSION,
        "remote_enabled": bool(config.REMOTE_ACCESS_ENABLED),
        "allowed_origins": domains.allowed_origins(),
        "owner_db": os.environ.get("ZENO_OWNER_AUTH_DB", "default local path"),
        "device_db": os.environ.get("ZENO_DEVICE_LINK_DB", "default local path"),
        "owner_provisioned": get_owner_auth().is_provisioned(),
        "queue": device_link.get_link().stats(),
        "deployment": deployment.preflight(),
    }
