"""Execution-placement policy. It does not silently run generated code."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

from reyes_agent.coding_system.workspace import resolve_workspace


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
        return {"e2b_enabled": os.environ.get("ZENO_E2B_ENABLED", "").casefold() in {"1", "true", "yes", "on"},
                "e2b_installed": importlib.util.find_spec("e2b") is not None,
                "default": "local-controlled", "implicit_secret_forwarding": False}
