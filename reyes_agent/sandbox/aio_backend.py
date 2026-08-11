"""Availability contract for agent-infra AIO Sandbox."""
from __future__ import annotations

import os
import shutil


def status() -> dict:
    enabled = os.environ.get("ZENO_AIO_SANDBOX_ENABLED", "").casefold() in {"1", "true", "yes", "on"}
    docker = shutil.which("docker")
    image = os.environ.get("ZENO_AIO_SANDBOX_IMAGE", "").strip()
    configured = enabled and bool(docker and image)
    return {"state": "STANDBY" if configured else "NOT_CONFIGURED", "enabled": enabled,
            "docker": bool(docker), "image_configured": bool(image), "available": configured,
            "secrets_forwarded": [], "mount_policy": "explicit workspace only"}
