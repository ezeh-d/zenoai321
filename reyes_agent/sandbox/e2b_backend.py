"""Availability contract for the existing optional E2B route."""
from __future__ import annotations

import importlib.util
import os


def status() -> dict:
    enabled = os.environ.get("ZENO_E2B_ENABLED", "").casefold() in {"1", "true", "yes", "on"}
    installed = importlib.util.find_spec("e2b") is not None
    authenticated = bool(os.environ.get("E2B_API_KEY", "").strip())
    ready = enabled and installed and authenticated
    return {"state": "STANDBY" if ready else ("AUTH_REQUIRED" if enabled and installed else "NOT_CONFIGURED"),
            "enabled": enabled, "installed": installed, "authenticated": authenticated,
            "available": ready, "secrets_forwarded": []}
