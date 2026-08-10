"""Agent-facing entry points for the MCP bus."""

from __future__ import annotations

import json

from reyes_agent.memory.privacy import redact
from reyes_agent.tools import register
from reyes_agent.tools.mcp import get_mcp_manager


@register(name="mcp_status", description="Show configured allowlisted MCP servers and real health.",
          input_schema={"type": "object", "properties": {}})
def mcp_status() -> str:
    return json.dumps(get_mcp_manager().status(), default=str)


@register(name="mcp_discover", description="Explicitly connect to one allowlisted MCP server and discover its tools.",
          input_schema={"type": "object", "properties": {"server": {"type": "string"}}, "required": ["server"]})
def mcp_discover(server: str) -> str:
    try:
        return json.dumps({"server": server, "tools": get_mcp_manager().discover(server)}, default=str)
    except Exception as exc:
        return json.dumps({"server": server, "ok": False,
                           "error": f"{type(exc).__name__}: {redact(exc, limit=300)}"})


@register(name="mcp_read", description="Call an MCP tool only when its server explicitly marks it read-only.",
          input_schema={"type": "object", "properties": {
              "server": {"type": "string"}, "tool": {"type": "string"},
              "arguments": {"type": "object"}}, "required": ["server", "tool"]})
def mcp_read(server: str, tool: str, arguments: dict | None = None) -> str:
    return json.dumps(get_mcp_manager().call(server, tool, arguments, require_read_only=True), default=str)


@register(name="mcp_action", description="Call a state-changing or unclassified MCP tool through ZENO's confirmation gate.",
          input_schema={"type": "object", "properties": {
              "server": {"type": "string"}, "tool": {"type": "string"},
              "arguments": {"type": "object"}}, "required": ["server", "tool"]},
          requires_confirmation=True)
def mcp_action(server: str, tool: str, arguments: dict | None = None) -> str:
    return json.dumps(get_mcp_manager().call(server, tool, arguments, require_read_only=False), default=str)
