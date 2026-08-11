"""Execution-placement policy. It does not silently run generated code."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

from reyes_agent.coding_system.workspace import resolve_workspace
from reyes_agent.sandbox.local_restricted_backend import LocalRestrictedBackend


class SandboxManager:
    def select(self, *, untrusted: bool, workspace: str | Path | None = None) -> dict[str, Any]:
        root = resolve_workspace(workspace)
        e2b_enabled = os.environ.get("ZENO_E2B_ENABLED", "").casefold() in {"1", "true", "yes", "on"}
        e2b_ready = e2b_enabled and importlib.util.find_spec("e2b") is not None and bool(os.environ.get("E2B_API_KEY", ""))
        if untrusted and e2b_ready:
            return {"backend": "e2b", "workspace": str(root), "secrets_forwarded": [], "upload_requires_authorization": True}
        return {"backend": "local-controlled", "workspace": str(root), "mode": "read-only" if untrusted else "workspace-write",
                "secrets_forwarded": [], "confirmation_required": bool(untrusted)}

    @staticmethod
    def status() -> dict[str, Any]:
        from reyes_agent.sandbox import aio_backend, e2b_backend
        return {"state": "WORKING", "backends": {
                    "aio": aio_backend.status(), "e2b": e2b_backend.status(),
                    "local_restricted": LocalRestrictedBackend.status()},
                "default": "local-restricted", "implicit_secret_forwarding": False,
                "untrusted_requires_strong_backend": True}

    def execute_python(self, script: str, *, workspace: str | Path | None = None,
                       untrusted: bool = True, timeout_s: float = 20.0) -> dict[str, Any]:
        root = resolve_workspace(workspace)
        from reyes_agent.sandbox import aio_backend, e2b_backend
        if untrusted and not (aio_backend.status()["available"] or e2b_backend.status()["available"]):
            return {"ok": False, "state": "ISOLATION_UNAVAILABLE",
                    "reason": "Untrusted code requires configured AIO Sandbox or E2B; local policy is not an OS boundary.",
                    "backend": None}
        # Remote/container execution is deliberately not guessed from package
        # presence. Until one is configured, only explicitly trusted generated
        # code reaches the local restricted process.
        if untrusted:
            return {"ok": False, "state": "NOT_IMPLEMENTED",
                    "reason": "The configured strong sandbox needs its deployment-specific connector.",
                    "backend": "aio" if aio_backend.status()["available"] else "e2b"}
        return LocalRestrictedBackend().execute_python(script, workspace=str(root), timeout_s=timeout_s).as_dict()
