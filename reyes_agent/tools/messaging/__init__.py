"""ZENO's messaging engine: real apps, real verification.

    ZENO -> Intent Router -> Messaging Router -> Platform Adapter
         -> Real Application -> Verify -> Result
"""

from __future__ import annotations

from typing import Any

from reyes_agent.tools.messaging import intent, models, router


def send(platform: str, destination: str, message: str,
         destination_type: str = "", account: str = "",
         send_it: bool = True) -> models.SendResult:
    return router.send(models.SendRequest(
        platform=(platform or "").strip().lower(), destination=destination,
        message=message, destination_type=destination_type, account=account,
        send=send_it))


def status() -> dict[str, Any]:
    return router.status()


__all__ = ["intent", "models", "router", "send", "status"]
