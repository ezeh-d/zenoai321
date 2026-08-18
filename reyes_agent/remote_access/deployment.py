"""Fail-closed production checks for the single-instance Anywhere gateway."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from reyes_agent.remote_access import domains


def preflight() -> dict[str, Any]:
    production = not domains.dev_mode()
    errors: list[str] = []
    warnings: list[str] = []
    workers_raw = os.environ.get("WEB_CONCURRENCY", "1").strip()
    try:
        workers = int(workers_raw)
    except ValueError:
        workers = 0
    if workers != 1:
        errors.append("SQLite Anywhere gateway requires WEB_CONCURRENCY=1.")

    paths: dict[str, str] = {}
    for variable in ("ZENO_OWNER_AUTH_DB", "ZENO_DEVICE_LINK_DB",
                     "ZENO_MEDIA_STORE_DB", "ZENO_WEB_PUSH_DB"):
        value = os.environ.get(variable, "").strip()
        paths[variable] = value
        if production and not value:
            errors.append(f"{variable} must point to persistent storage.")
            continue
        if value:
            path = Path(value).expanduser()
            if production and not path.is_absolute():
                errors.append(f"{variable} must be an absolute path.")
            if not path.parent.is_dir() or not os.access(path.parent, os.W_OK):
                errors.append(f"{variable} parent is not writable.")

    if production:
        if not domains.public_domain():
            errors.append("ZENO_PUBLIC_DOMAIN is required in production.")
        if not domains.allowed_origins():
            errors.append("At least one exact HTTPS owner origin is required.")
        if not os.environ.get("ZENO_MEDIA_ENCRYPTION_KEY", "").strip():
            warnings.append("Remote voice remains disabled until ZENO_MEDIA_ENCRYPTION_KEY is set.")
        if not os.environ.get("ZENO_WEB_PUSH_PRIVATE_KEY", "").strip():
            warnings.append("Native Web Push remains disabled until VAPID keys are set.")

    return {"ok": not errors, "storage": "sqlite-single-instance",
            "workers": workers, "errors": errors, "warnings": warnings,
            "configured_paths": {key: bool(value) for key, value in paths.items()}}
