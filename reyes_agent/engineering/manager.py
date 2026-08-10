"""Select an engineering backend without launching one during startup."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from reyes_agent.coding_system.workspace import resolve_workspace


class EngineeringManager:
    def backends(self) -> list[dict[str, Any]]:
        from reyes_agent.coding_system.interpreter_client import get_interpreter_client
        oi = get_interpreter_client().status()
        return [
            {"name": "zeno", "available": True, "enabled": True, "mode": "existing TOSIN/coding-system tools"},
            {"name": "open_interpreter", "available": oi["installed"], "enabled": oi["enabled"], "mode": "bounded subprocess"},
            {"name": "openhands", "available": bool(shutil.which("openhands")),
             "enabled": os.environ.get("ZENO_OPENHANDS_ENABLED", "").casefold() in {"1", "true", "yes", "on"}, "mode": "external service/CLI"},
            {"name": "claude", "available": bool(shutil.which("claude")), "enabled": False, "mode": "owner-invoked external CLI"},
            {"name": "codex", "available": bool(shutil.which("codex")), "enabled": False, "mode": "owner-invoked external CLI"},
        ]

    def select(self, workspace: str | Path | None = None, *, preferred: str = "") -> dict[str, Any]:
        root = resolve_workspace(workspace)
        choices = self.backends()
        preferred = preferred.strip().casefold()
        selected = next((item for item in choices if item["name"] == preferred and item["available"] and item["enabled"]), None)
        selected = selected or next(item for item in choices if item["name"] == "zeno")
        return {"backend": selected, "workspace": str(root), "branch_or_checkpoint_required": True,
                "verification_required": True, "timeout_required": True, "command_logging_required": True}
