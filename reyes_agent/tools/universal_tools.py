"""Read-only owner tools for the Universal Capability Library.

These functions expose inventory and routing decisions.  They intentionally do
not offer a generic ``execute any tool`` entry point: agents continue to see a
small scoped tool list and every execution continues through ``run_tool``.
"""
from __future__ import annotations

import json

from reyes_agent.tools import register


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


@register(
    "universal_tool_catalog",
    "List or search ZENO's complete capability catalog and optional providers, including honest readiness states.",
    {"type": "object", "properties": {
        "state": {"type": "string", "description": "Optional state such as INSTALLED, AVAILABLE, EXPERIMENTAL, NEEDS_LOGIN or NEEDS_DEVICE."},
        "query": {"type": "string", "description": "Optional text search across capabilities and providers."},
        "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 25},
    }},
)
def universal_tool_catalog(state: str = "", query: str = "", limit: int = 25) -> str:
    from reyes_agent.tools import universal_catalog

    return _json(universal_catalog.query(state=state, text=query, limit=limit))


@register(
    "universal_tool_health",
    "Report the normalized adapter contract and health of all executable ZENO tools, or one named tool.",
    {"type": "object", "properties": {
        "tool": {"type": "string", "description": "Optional registered tool name or universal tool id."},
    }},
)
def universal_tool_health(tool: str = "") -> str:
    from reyes_agent.tools import universal_catalog
    from reyes_agent.tools.universal_registry import (
        contract_status,
        get_global_tool_registry,
    )

    registry = get_global_tool_registry()
    if tool.strip():
        adapter = registry.get(tool)
        if adapter is None:
            return _json({"ok": False, "state": "NOT_FOUND", "tool": tool})
        return _json({
            "ok": True,
            "metadata": adapter.metadata().as_dict(),
            "health": adapter.health().as_dict(),
        })
    return _json({
        "ok": True,
        "registry": registry.health(),
        "contract": contract_status(),
        "catalog": universal_catalog.status(),
    })


@register(
    "universal_tool_resolve",
    "Resolve the best healthy, permitted ZENO tool for a capability and optional device without executing it.",
    {"type": "object", "required": ["capability"], "properties": {
        "capability": {"type": "string"},
        "device": {"type": "string", "description": "Optional device such as local-windows, android or web-companion."},
    }},
)
def universal_tool_resolve(capability: str, device: str = "") -> str:
    from reyes_agent.tools.universal_registry import get_global_tool_registry

    result = get_global_tool_registry().resolve_best_tool(
        capability,
        {"capability": capability, "device": device},
    )
    return _json({"ok": result is not None, "resolution": result})
