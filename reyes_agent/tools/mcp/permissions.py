"""Map MCP declarations/annotations into ZENO's existing permission engine."""

from __future__ import annotations

from typing import Any

from reyes_agent import permissions
from reyes_agent.tools.mcp.registry import MCPServer


def server_allowed(server: MCPServer) -> tuple[bool, str]:
    if not server.enabled:
        return False, "server is disabled or not allowlisted"
    if server.trust_level == "untrusted":
        return False, "server has not been reviewed/trusted"
    for capability in server.permissions:
        state = permissions.state_for(capability)
        if state == permissions.BLOCKED:
            return False, f"capability '{capability}' is blocked"
    return True, "allowed"


def read_only_hint(tool: dict[str, Any]) -> bool:
    annotations = tool.get("annotations") or {}
    return annotations.get("readOnlyHint") is True or annotations.get("read_only_hint") is True
