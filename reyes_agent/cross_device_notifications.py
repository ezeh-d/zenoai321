"""Cross-device facade over ZENO's existing notification authority."""
from __future__ import annotations

import os


def status() -> dict:
    return {"state": "ONLINE", "authority": "reyes_agent.notification_bus",
            "phone_bridge_enabled": os.environ.get("ZENO_CROSS_DEVICE_ENABLED", "").casefold() in {"1", "true", "yes", "on"},
            "privacy_mode": os.environ.get("ZENO_NOTIFICATION_PRIVACY", "private").strip().casefold(),
            "unknown_presence_speaks_sensitive_content": False, "polling_added": False}
