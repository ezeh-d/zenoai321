"""Finite official-SDK MCP stdio client."""

from __future__ import annotations

import asyncio
import importlib.util
from typing import Any

from reyes_agent.tools.mcp.registry import MCPServer
from reyes_agent.memory.privacy import redact


def _safe_structure(value: Any, *, depth: int = 0) -> Any:
    """Remove secret-shaped fields and bound data returned to model context."""
    if depth > 6:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        output = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 100:
                output["..."] = "[TRUNCATED]"
                break
            label = str(key)
            if any(marker in label.casefold() for marker in (
                    "password", "passwd", "secret", "token", "api_key", "apikey",
                    "cookie", "credential", "private_key")):
                output[label] = "[REDACTED]"
            else:
                output[label] = _safe_structure(item, depth=depth + 1)
        return output
    if isinstance(value, (list, tuple)):
        return [_safe_structure(item, depth=depth + 1) for item in value[:200]]
    if isinstance(value, str):
        return redact(value, limit=20_000)
    return value


def installed() -> bool:
    try:
        return importlib.util.find_spec("mcp") is not None
    except (ImportError, ValueError):
        return False


def _content(result: Any) -> dict[str, Any]:
    blocks = []
    for item in getattr(result, "content", []) or []:
        if hasattr(item, "text"):
            blocks.append({"type": "text", "text": redact(item.text, limit=20_000)})
        else:
            blocks.append({"type": str(getattr(item, "type", "unknown"))})
    is_error = getattr(result, "is_error", getattr(result, "isError", False))
    structured = getattr(result, "structured_content", getattr(result, "structuredContent", None))
    return {"is_error": bool(is_error), "content": blocks,
            "structured": _safe_structure(structured)}


async def _session(server: MCPServer, environment: dict[str, str], operation: str,
                   tool_name: str = "", arguments: dict[str, Any] | None = None) -> Any:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=server.command, args=server.args, env=environment)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            if operation == "list":
                result = await session.list_tools()
                return [{
                    "name": tool.name,
                    "description": str(tool.description or "")[:1000],
                    "input_schema": getattr(tool, "input_schema", getattr(tool, "inputSchema", None)),
                    "annotations": (tool.annotations.model_dump() if getattr(tool, "annotations", None) else {}),
                } for tool in result.tools]
            return _content(await session.call_tool(tool_name, arguments or {}))


def run(server: MCPServer, environment: dict[str, str], operation: str,
        *, tool_name: str = "", arguments: dict[str, Any] | None = None,
        timeout_s: float = 30.0) -> Any:
    if not installed():
        raise RuntimeError("The official MCP Python SDK is not installed")

    async def bounded() -> Any:
        return await asyncio.wait_for(
            _session(server, environment, operation, tool_name, arguments),
            timeout=max(1.0, min(120.0, float(timeout_s))),
        )

    # MCP calls run on worker threads, so each finite operation owns and
    # closes its loop and stdio child. No hidden permanent event-loop thread.
    return asyncio.run(bounded())
