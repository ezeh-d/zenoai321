"""One private-network authority: managed Tailscale or optional Headscale."""
from __future__ import annotations

import os
from typing import Any

from . import tailscale


class PrivateNetworkManager:
    def mode(self) -> str:
        requested = os.environ.get("ZENO_PRIVATE_NETWORK_MODE", "TAILSCALE_MANAGED").strip().upper()
        return requested if requested in {"TAILSCALE_MANAGED", "HEADSCALE_SELF_HOSTED"} else "TAILSCALE_MANAGED"

    def status(self) -> dict[str, Any]:
        mode = self.mode()
        data = tailscale.status()
        if mode == "HEADSCALE_SELF_HOSTED":
            url = os.environ.get("ZENO_HEADSCALE_URL", "").strip()
            if not url:
                data.update(state="NOT_CONFIGURED", connected=False,
                            detail="HEADSCALE_SELF_HOSTED selected but ZENO_HEADSCALE_URL is missing")
        data["mode"] = mode
        service_enabled = os.environ.get("ZENO_TAILSCALE_SERVE_ENABLED", "").strip().casefold() in {
            "1", "true", "yes", "on",
        }
        # Transport connectivity is deliberately separate from publishing a
        # ZENO endpoint.  A connected tailnet must never be reported as proof
        # that the desktop service itself is remotely reachable.
        data["zeno_service_exposed"] = service_enabled and bool(data.get("connected"))
        data["service_state"] = (
            "WORKING" if data["zeno_service_exposed"]
            else ("OFFLINE" if service_enabled else "NOT_CONFIGURED")
        )
        data["public_exposure_allowed"] = False
        data["sensitive_services"] = "private peers require an independent ZENO device authorization"
        return data


_MANAGER = PrivateNetworkManager()


def get_manager() -> PrivateNetworkManager:
    return _MANAGER


def status() -> dict[str, Any]:
    return _MANAGER.status()
