"""The record of every MCP server ZENO has heard of, and its state.

Persisted as one JSON file the owner can read and edit, next to the skills
vault and for the same reason: a list of what may run on your machine is
not something software should keep to itself.

Registry entries are DATA. A server's own description is written by whoever
published it, so it is stored, shown, and never treated as instructions --
`trust.review()` screens it for exactly that before the owner ever sees it.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from reyes_agent import config
from reyes_agent.tools.marketplace import trust
from reyes_agent.tools.marketplace.trust import (APPROVED, BLOCKED, DISCOVERED, ENABLED,
                                                 Manifest, Review)

_lock = threading.RLock()
_cache: dict[str, dict[str, Any]] | None = None


def _path() -> Path:
    return Path(config.VAULT_PATH) / "07-System" / "mcp" / "servers.json"


def _audit_path() -> Path:
    return _path().parent / "audit.jsonl"


def _load() -> dict[str, dict[str, Any]]:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        path = _path()
        try:
            _cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, ValueError):
            _cache = {}
        return _cache


def _save() -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(_load(), handle, indent=2, default=str)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def audit(event: str, name: str, detail: str = "") -> None:
    try:
        path = _audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": time.time(), "event": event,
                                     "server": name, "detail": detail[:400]}) + "\n")
    except OSError:
        pass


def record(manifest: Manifest, *, registry_source: str = "") -> dict[str, Any]:
    """Note that a server exists. It arrives DISCOVERED and cannot run."""
    with _lock:
        servers = _load()
        existing = servers.get(manifest.name)
        if existing:
            existing["manifest"] = manifest.as_dict()
            existing["seen_at"] = time.time()
            _save()
            return existing
        entry = {
            "name": manifest.name,
            "state": DISCOVERED,
            "manifest": manifest.as_dict(),
            "registry_source": registry_source,
            "review": None,
            "granted": [],
            "approved_by": "",
            "first_seen": time.time(),
            "seen_at": time.time(),
        }
        servers[manifest.name] = entry
        _save()
    audit("discovered", manifest.name, registry_source)
    return entry


def get(name: str) -> dict[str, Any] | None:
    return _load().get(name)


def all_servers(state: str = "") -> list[dict[str, Any]]:
    servers = list(_load().values())
    if state:
        servers = [s for s in servers if s["state"] == state]
    return sorted(servers, key=lambda s: s["name"])


def move(name: str, target: str, *, by: str = "", granted: list[str] | None = None
         ) -> tuple[bool, str]:
    """Change a server's state, refusing anything that is not a legal move."""
    with _lock:
        entry = _load().get(name)
        if entry is None:
            return False, f"no server called {name!r}"
        current = entry["state"]
        if current == target:
            return True, f"{name} is already {target}"
        if not trust.may_move(current, target):
            return False, (f"{name} cannot go from {current} to {target} -- "
                           f"the only moves from {current} are "
                           f"{sorted(trust._TRANSITIONS.get(current, []))}")
        if target == APPROVED and not by:
            return False, ("approval needs a person: nothing reaches APPROVED without "
                           "someone taking responsibility for it")
        if target == ENABLED and not entry.get("approved_by"):
            return False, f"{name} has never been approved by anyone"

        entry["state"] = target
        if target == APPROVED:
            entry["approved_by"] = by
            # Only what the owner explicitly grants, never what was requested.
            entry["granted"] = list(granted or [])
        _save()
    audit(target.lower(), name, by or "")
    return True, f"{name} is now {target}"


def screen(name: str, *, publisher_trusted: bool = False) -> Review | None:
    """Run the trust review and record its verdict. Never installs."""
    with _lock:
        entry = _load().get(name)
        if entry is None:
            return None
        manifest = Manifest(**{k: v for k, v in entry["manifest"].items()
                               if k in Manifest.__dataclass_fields__})
        verdict = trust.review(manifest, publisher_trusted=publisher_trusted)
        entry["review"] = verdict.as_dict()
        if entry["state"] == DISCOVERED:
            entry["state"] = trust.UNTRUSTED
        if entry["state"] == trust.UNTRUSTED and not verdict.refused:
            entry["state"] = trust.REVIEWED
        if verdict.refused:
            entry["state"] = BLOCKED
        _save()
    audit("reviewed", name, verdict.verdict)
    return verdict


def callable_servers() -> list[str]:
    """The only servers whose tools may actually be invoked."""
    return [s["name"] for s in all_servers() if s["state"] in trust.CALLABLE]


def may_call(name: str, capability: str = "") -> tuple[bool, str]:
    """The check before any MCP tool runs."""
    entry = get(name)
    if entry is None:
        return False, f"{name} is not a server ZENO knows"
    if entry["state"] not in trust.CALLABLE:
        return False, (f"{name} is {entry['state']}, not ENABLED -- I will not call a "
                       "server you have not approved and enabled")
    if capability and capability not in entry.get("granted", []):
        return False, (f"{name} was not granted {capability!r}. It asked for "
                       f"{entry['manifest'].get('requested', [])}; you granted "
                       f"{entry.get('granted', [])}.")
    return True, "allowed"


def reset_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def status() -> dict[str, Any]:
    servers = all_servers()
    counts: dict[str, int] = {}
    for server in servers:
        counts[server["state"]] = counts.get(server["state"], 0) + 1
    return {
        "state": "ONLINE",
        "known": len(servers),
        "by_state": counts,
        "callable": callable_servers(),
        "path": str(_path()),
        **trust.describe_states(),
    }
