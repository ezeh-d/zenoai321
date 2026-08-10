"""Workspace confinement for coding operations."""

from __future__ import annotations

import os
from pathlib import Path

from reyes_agent import config


class WorkspaceError(ValueError):
    pass


def allowed_roots() -> tuple[Path, ...]:
    configured = [item.strip() for item in os.environ.get("ZENO_CODING_WORKSPACES", "").split(os.pathsep) if item.strip()]
    roots = [config.PROJECT_ROOT]
    roots.extend(Path(item).expanduser() for item in configured)
    unique: list[Path] = []
    for root in roots:
        try:
            resolved = root.resolve(strict=False)
        except OSError:
            continue
        if resolved not in unique:
            unique.append(resolved)
    return tuple(unique)


def resolve_workspace(value: str | Path | None) -> Path:
    requested = Path(value).expanduser() if value else config.PROJECT_ROOT
    resolved = requested.resolve(strict=False)
    for root in allowed_roots():
        if resolved == root or root in resolved.parents:
            if not resolved.exists() or not resolved.is_dir():
                raise WorkspaceError(f"Workspace does not exist or is not a folder: {resolved}")
            return resolved
    raise WorkspaceError(f"Workspace is outside ZENO's allowed coding roots: {resolved}")
