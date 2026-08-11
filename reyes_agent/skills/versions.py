"""Never silently destroy a working skill.

A learned skill gets edited: corrected, recomposed, improved after a
failure. Every one of those changes can be wrong, and the evidence that it
was wrong arrives later -- the next time it runs. So the previous version is
archived before any change, and `rollback()` puts it back.

Archives are plain JSON next to the skill, for the same reason the skills
themselves are: automation the owner cannot inspect is automation the owner
cannot refuse.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from reyes_agent.skills import registry
from reyes_agent.skills.models import Skill

# Keep enough history to undo a bad week, not enough to fill a disk.
MAX_VERSIONS = 10


def _dir() -> Path:
    return registry._root() / "versions"          # noqa: SLF001 -- same package


def _path(skill_id: str, version: int) -> Path:
    return _dir() / f"{skill_id}.v{version}.json"


def archive(skill: Skill, *, why: str = "") -> bool:
    """Store the CURRENT state before someone changes it."""
    try:
        directory = _dir()
        directory.mkdir(parents=True, exist_ok=True)
        payload = {**skill.as_dict(), "archived_at": time.time(), "why": why[:300]}
        path = _path(skill.skill_id, skill.version)
        temp = path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except OSError:
        return False
    _prune(skill.skill_id)
    return True


def _prune(skill_id: str) -> None:
    try:
        archives = sorted(_dir().glob(f"{skill_id}.v*.json"),
                          key=lambda p: p.stat().st_mtime)
        for stale in archives[:-MAX_VERSIONS]:
            stale.unlink(missing_ok=True)
    except OSError:
        pass


def history(skill_id: str) -> list[dict[str, Any]]:
    """Every archived version, oldest first."""
    found = []
    try:
        for path in sorted(_dir().glob(f"{skill_id}.v*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            found.append({"version": raw.get("version"), "why": raw.get("why", ""),
                          "archived_at": raw.get("archived_at"),
                          "steps": len(raw.get("steps") or []),
                          "success_rate": (raw.get("history") or {}).get("success_rate")})
    except OSError:
        return []
    return sorted(found, key=lambda r: r.get("version") or 0)


def rollback(skill_id: str, version: int = 0) -> tuple[bool, str]:
    """Restore an archived version. With no version, the most recent one."""
    archives = history(skill_id)
    if not archives:
        return False, "there is no earlier version of that skill"
    target = version or max(r["version"] or 0 for r in archives)

    path = _path(skill_id, target)
    if not path.exists():
        return False, f"no archived v{target}"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, f"could not read v{target}: {type(exc).__name__}"

    current = registry.get(skill_id)
    if current is not None:
        # The thing being rolled back is itself worth keeping.
        archive(current, why=f"before rollback to v{target}")

    restored = Skill.from_dict(raw)
    # A restored skill keeps climbing the version numbers rather than
    # reusing an old one, so history stays a straight line.
    restored.version = (current.version + 1) if current else restored.version
    stored, why = registry.save(restored, event="rolled_back",
                                detail=f"restored the steps from v{target}")
    if not stored:
        return False, why
    return True, (f"'{restored.name}' is back to how it worked in v{target} "
                  f"(now v{restored.version}).")


def status() -> dict[str, Any]:
    try:
        count = len(list(_dir().glob("*.json")))
    except OSError:
        count = 0
    return {"state": "ONLINE", "archived_versions": count,
            "max_per_skill": MAX_VERSIONS, "path": str(_dir()),
            "note": "The previous version is archived before any change, so a bad "
                    "correction or a bad improvement can always be undone."}
