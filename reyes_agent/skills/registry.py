"""Where skills live, and the rules for changing them.

One JSON file per skill under the vault, written atomically. JSON rather
than SQLite because a skill is something the owner should be able to open,
read and delete with a text editor -- automation the owner cannot inspect
is automation the owner cannot refuse.

Every state change is appended to an audit log. The constitution forbids a
skill from deleting audit logs; this is the log it is forbidden from
deleting.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from reyes_agent import config
from reyes_agent.skills import constitution
from reyes_agent.skills.models import APPROVED, LEARNED, OBSERVED, RETIRED, Skill

_lock = threading.RLock()
_cache: dict[str, Skill] | None = None


def _root() -> Path:
    return Path(config.VAULT_PATH) / "07-System" / "skills"


def _audit_path() -> Path:
    return _root() / "audit.jsonl"


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Never leave a half-written skill on disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def audit(event: str, skill: Skill, detail: str = "") -> None:
    try:
        path = _audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "at": time.time(), "event": event, "skill_id": skill.skill_id,
                "name": skill.name, "state": skill.state, "version": skill.version,
                "detail": detail[:500]}) + "\n")
    except OSError:
        pass          # an audit failure must not break the operation it records


def _load_all() -> dict[str, Skill]:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        found: dict[str, Skill] = {}
        root = _root()
        if root.is_dir():
            for path in root.glob("*.json"):
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    skill = Skill.from_dict(raw)
                    found[skill.skill_id] = skill
                except (OSError, ValueError, KeyError):
                    continue      # one corrupt file never hides the rest
        _cache = found
        return _cache


def all_skills(state: str = "") -> list[Skill]:
    skills = list(_load_all().values())
    if state:
        skills = [s for s in skills if s.state == state]
    return sorted(skills, key=lambda s: (-s.confidence, s.name))


def get(skill_id: str) -> Skill | None:
    return _load_all().get(skill_id)


def by_name(name: str) -> Skill | None:
    needle = str(name or "").strip().lower()
    for skill in _load_all().values():
        if skill.name.lower() == needle:
            return skill
    return None


def save(skill: Skill, *, event: str = "saved", detail: str = "") -> tuple[bool, str]:
    """Persist a skill. Refused outright if it fails the constitution."""
    verdict = constitution.review(skill)
    if not verdict.allowed:
        audit("refused", skill, verdict.reason)
        return False, verdict.reason

    skill.updated_at = time.time()
    with _lock:
        _write_atomic(_root() / f"{skill.skill_id}.json", skill.as_dict())
        if _cache is not None:
            _cache[skill.skill_id] = skill
    audit(event, skill, detail)
    return True, "saved"


def delete(skill_id: str) -> bool:
    with _lock:
        skill = _load_all().get(skill_id)
        if skill is None:
            return False
        try:
            (_root() / f"{skill_id}.json").unlink()
        except OSError:
            return False
        _load_all().pop(skill_id, None)
    audit("deleted", skill)
    return True


def reset_cache() -> None:
    """Re-read from disk. Used after external edits and by tests."""
    global _cache
    with _lock:
        _cache = None


def stats() -> dict[str, Any]:
    skills = list(_load_all().values())
    return {
        "total": len(skills),
        "observed": sum(1 for s in skills if s.state == OBSERVED),
        "learned": sum(1 for s in skills if s.state == LEARNED),
        "approved": sum(1 for s in skills if s.state == APPROVED),
        "retired": sum(1 for s in skills if s.state == RETIRED),
        "runnable": sum(1 for s in skills if s.runnable),
        "path": str(_root()),
    }
