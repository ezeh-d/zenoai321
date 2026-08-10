"""Explicit MCP discovery; never runs during startup."""

from __future__ import annotations

from typing import Any


def normalize(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    seen: set[str] = set()
    for item in tools[:500]:
        name = str(item.get("name", "")).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        output.append({
            "name": name,
            "description": str(item.get("description", ""))[:1000],
            "input_schema": item.get("input_schema") or {"type": "object"},
            "annotations": item.get("annotations") or {},
        })
    return output
