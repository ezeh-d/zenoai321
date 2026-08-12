"""Cheap current-project terminology; no indexing or polling."""

from __future__ import annotations


def current_terms(limit: int = 20) -> list[str]:
    values: list[str] = []
    try:
        from reyes_agent import project_activity

        snapshot = project_activity.snapshot()
        project = snapshot.get("project") or {}
        for value in (project.get("name"), project.get("active_agent")):
            if value:
                values.append(str(value))
        for item in (project.get("files") or [])[-10:]:
            value = str(item.get("path") if isinstance(item, dict) else item)
            if value:
                values.append(value.rsplit("/", 1)[-1].rsplit("\\", 1)[-1])
    except Exception:
        pass
    return list(dict.fromkeys(values))[:limit]

