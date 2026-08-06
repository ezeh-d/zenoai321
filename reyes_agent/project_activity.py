"""Bounded, evidence-backed live activity for project creation.

This module deliberately records observable work (chosen destination, tool,
file write, command/test result, warning or failure).  It does not retain
model prompts, hidden reasoning, or invented percentages.  Durable Event Bus
events are the history; this small in-memory projection only drives the live
view and is capped so a long coding session cannot grow ZENO indefinitely.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from reyes_agent import config

_lock = threading.RLock()
_projects: dict[str, dict[str, Any]] = {}
_MAX_PROJECTS = 24
_MAX_STEPS = 80
_MAX_FILES = 120
_MAX_MESSAGES = 40


def _key(name: str) -> str:
    return " ".join(str(name or "").casefold().split())[:160]


def _emit(action: str, project: dict[str, Any]) -> None:
    """Publish a compact snapshot. Event Bus publishing is bounded/nonblocking.

    The activity endpoint keeps a small current-file preview for a dashboard
    that opens mid-project. The durable event intentionally carries only its
    filename: code content already travels through the existing workspace UI
    event, so duplicating it here would inflate the event database for every
    file write.
    """
    try:
        from reyes_agent import event_bus

        snapshot = _snapshot(project)
        if snapshot.get("preview"):
            snapshot["preview"] = {"file": snapshot["preview"].get("file", "")}
        event_bus.publish("project.activity", {"action": action, "project": snapshot},
                          source="project_activity", correlation_id=project["id"])
    except Exception:  # noqa: BLE001 -- observability can never block a write
        pass


def _snapshot(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": project["id"],
        "name": project["name"],
        "destination": project.get("destination", ""),
        "project_path": project.get("project_path", ""),
        "state": project["state"],
        "active_agent": project.get("active_agent", "ZENO"),
        "steps": [dict(item) for item in project["steps"]],
        "completed_steps": project["completed_steps"],
        "known_steps": len(project["steps"]),
        # A percentage is supplied only when there is an actual, finite plan
        # from the caller. File writes alone intentionally show a count.
        "progress_percent": project.get("progress_percent"),
        "files": list(project["files"]),
        "preview": dict(project["preview"]) if project.get("preview") else None,
        "tools": list(project["tools"]),
        "warnings": list(project["warnings"]),
        "errors": list(project["errors"]),
        "updated_at": project["updated_at"],
    }


def _new_project(name: str) -> dict[str, Any]:
    project = {
        "id": uuid.uuid4().hex[:12], "name": name.strip(), "destination": "", "project_path": "",
        "state": "WAITING", "active_agent": "ZENO", "steps": deque(maxlen=_MAX_STEPS),
        "completed_steps": 0, "progress_percent": None, "files": deque(maxlen=_MAX_FILES),
        "tools": deque(maxlen=_MAX_MESSAGES), "warnings": deque(maxlen=_MAX_MESSAGES),
        "errors": deque(maxlen=_MAX_MESSAGES), "preview": None, "updated_at": time.time(),
    }
    _projects[_key(name)] = project
    while len(_projects) > _MAX_PROJECTS:
        # dict insertion order is enough here; activity is a live cache and
        # Event Bus remains the durable source of history.
        _projects.pop(next(iter(_projects)))
    return project


def _project(name: str) -> dict[str, Any]:
    with _lock:
        return _projects.get(_key(name)) or _new_project(name)


def _user_folder(name: str) -> Path:
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    label = " ".join(name.strip().casefold().replace("_", " ").replace("-", " ").split())
    if label in {"desktop", "my desktop"}:
        return home / "Desktop"
    if label in {"documents", "document", "my documents"}:
        return home / "Documents"
    if label in {"zeno projects", "zeno project", "zeno"}:
        return config.VAULT_PATH / "02-Projects"
    raw = Path(name).expanduser()
    if not raw.is_absolute():
        raise ValueError("Choose Desktop, Documents, ZENO Projects, or provide a full folder path.")
    resolved = raw.resolve()
    if resolved == Path(resolved.anchor):
        raise ValueError("A drive root is not a valid project destination.")
    return resolved


def request_destination(name: str) -> dict[str, Any]:
    """Record that a NEW project cannot begin until Divine chooses a path."""
    with _lock:
        project = _project(name)
        project["state"] = "WAITING"
        project["updated_at"] = time.time()
        project["steps"].append({"label": "Choose save location", "state": "waiting", "at": project["updated_at"]})
        snap = _snapshot(project)
    _emit("destination_required", project)
    return snap


def select_destination(name: str, destination: str) -> dict[str, Any]:
    root = _user_folder(destination)
    with _lock:
        project = _project(name)
        project["destination"] = str(root)
        project["project_path"] = str(root / _slug(name))
        project["state"] = "PLANNING"
        project["updated_at"] = time.time()
        project["steps"].append({"label": "Save location confirmed", "state": "completed",
                                 "detail": project["project_path"], "at": project["updated_at"]})
        project["completed_steps"] += 1
        snap = _snapshot(project)
    _emit("destination_selected", project)
    return snap


def saved_destination(name: str) -> Path | None:
    with _lock:
        project = _projects.get(_key(name))
        value = project.get("destination") if project else ""
    return Path(value) if value else None


def is_known_project_dir(name: str, directory: Path) -> bool:
    """Existing legacy vault projects remain editable without a new prompt."""
    return directory.is_dir()


def begin(name: str, project_dir: Path, *, agent: str = "ZENO", tool: str = "write_project_file") -> dict[str, Any]:
    with _lock:
        project = _project(name)
        project["destination"] = str(project_dir.parent)
        project["project_path"] = str(project_dir)
        project["state"] = "CODING"
        project["active_agent"] = agent or "ZENO"
        if tool and tool not in project["tools"]:
            project["tools"].append(tool)
        project["updated_at"] = time.time()
    _emit("started", project)
    return _snapshot(project)


def file_started(name: str, filename: str, *, tool: str = "write_project_file") -> None:
    with _lock:
        project = _project(name)
        now = time.time()
        project["state"] = "CODING"
        if tool and tool not in project["tools"]:
            project["tools"].append(tool)
        project["steps"].append({"label": f"Writing {filename}", "state": "working", "at": now})
        project["updated_at"] = now
    _emit("step_started", project)


def file_completed(name: str, filename: str, content: str = "") -> dict[str, Any]:
    with _lock:
        project = _project(name)
        now = time.time()
        if filename not in project["files"]:
            project["files"].append(filename)
        # A bounded, actual file excerpt supports code/document preview in
        # the live view. It is not hidden reasoning and does not retain an
        # unbounded copy of the project in process memory.
        project["preview"] = {"file": filename, "content": str(content)[:6000]}
        project["steps"].append({"label": f"Wrote {filename}", "state": "completed", "at": now})
        project["completed_steps"] += 1
        project["updated_at"] = now
        snap = _snapshot(project)
    _emit("file_completed", project)
    return snap


def failed(name: str, message: str) -> None:
    with _lock:
        project = _project(name)
        now = time.time()
        project["state"] = "FAILED"
        project["errors"].append(str(message)[:500])
        project["steps"].append({"label": "Project operation failed", "state": "failed",
                                 "detail": str(message)[:500], "at": now})
        project["updated_at"] = now
    _emit("failed", project)


def note_agent(name: str, agent: str, state: str = "WORKING") -> None:
    with _lock:
        project = _projects.get(_key(name))
        if project is None:
            return
        project["active_agent"] = agent or "ZENO"
        project["state"] = state if state in {"PLANNING", "CREATING", "CODING", "DELEGATING", "TESTING", "FIXING", "WAITING", "COMPLETED", "FAILED"} else project["state"]
        project["updated_at"] = time.time()
    _emit("agent_activity", project)


def status() -> list[dict[str, Any]]:
    with _lock:
        return [_snapshot(project) for project in _projects.values()]


def _slug(name: str) -> str:
    # Kept in sync with tools.projects without importing a tool module here.
    import re

    keep = re.sub(r"[^\w\s-]", "", name).strip()
    return re.sub(r"\s+", "-", keep).lower() or "project"
