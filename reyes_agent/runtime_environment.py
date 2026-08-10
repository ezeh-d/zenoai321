"""Explicit runtime environment and production safety checks.

Development helpers may exist in the repository, but they are never silently
activated in production.  This module is read-only and has no import-time
side effects; executable entry points call :func:`require_safe_startup`.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

DEVELOPMENT = "development"
TEST = "test"
STAGING = "staging"
PRODUCTION = "production"
ENVIRONMENTS = {DEVELOPMENT, TEST, STAGING, PRODUCTION}


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def name(environ: Mapping[str, str] | None = None) -> str:
    env = environ or os.environ
    value = str(env.get("ZENO_ENV", DEVELOPMENT)).strip().casefold()
    aliases = {"dev": DEVELOPMENT, "testing": TEST, "stage": STAGING, "prod": PRODUCTION}
    value = aliases.get(value, value)
    return value if value in ENVIRONMENTS else DEVELOPMENT


def report(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = environ or os.environ
    active = name(env)
    errors: list[str] = []
    warnings: list[str] = []
    demo_mode = _truthy(env.get("ZENO_DEMO_MODE"))

    mock_flags = sorted(
        key for key, value in env.items()
        if (key.startswith("ZENO_MOCK_") or key in {
            "ZENO_FAKE_BACKEND", "ZENO_SIMULATED_BACKENDS", "USE_MOCK_PROVIDERS",
        }) and _truthy(value)
    )
    if active == PRODUCTION:
        if demo_mode:
            errors.append("ZENO_DEMO_MODE cannot be enabled in production.")
        if mock_flags:
            errors.append("Mock backend flags are enabled: " + ", ".join(mock_flags))
        if _truthy(env.get("REMOTE_DEV_MODE")):
            errors.append("REMOTE_DEV_MODE cannot be enabled in production.")
        if _truthy(env.get("REMOTE_ACCESS_ENABLED")) and not str(
            env.get("ZENO_PUBLIC_DOMAIN", "")
        ).strip():
            errors.append("Remote access in production requires ZENO_PUBLIC_DOMAIN.")
    elif demo_mode:
        warnings.append("Demo mode is explicit; its state must never be presented as production data.")
    if mock_flags and active != TEST:
        warnings.append("Mock backend flags are active outside the test environment.")

    state = "DEGRADED" if errors else "ONLINE"
    summary = (
        "; ".join(errors) if errors else
        f"{active} environment; demo mode {'on' if demo_mode else 'off'}; "
        f"{len(mock_flags)} mock backend flag(s)."
    )
    return {
        "state": state,
        "environment": active,
        "demo_mode": demo_mode,
        "mock_backend_flags": mock_flags,
        "errors": errors,
        "warnings": warnings,
        "summary": summary,
    }


def require_safe_startup(environ: Mapping[str, str] | None = None) -> None:
    current = report(environ)
    if current["environment"] == PRODUCTION and current["errors"]:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(current["errors"]))
