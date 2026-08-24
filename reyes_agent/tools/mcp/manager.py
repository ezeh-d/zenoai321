"""Central, allowlisted, lazy MCP manager."""

from __future__ import annotations

import threading
import time
from typing import Any

from reyes_agent.memory.privacy import redact
from reyes_agent.tools.mcp import client, discovery, health, permissions as mcp_permissions
from reyes_agent.tools.mcp.registry import CONNECTED, DEGRADED, FAILED, MCPRegistry


class MCPManager:
    def __init__(self, registry: MCPRegistry | None = None) -> None:
        self.registry = registry or MCPRegistry()
        self._slots = threading.BoundedSemaphore(2)
        self._calls = 0
        self._failures = 0
        self._discovery_retries = 0

    def discover(self, server_name: str) -> list[dict[str, Any]]:
        server = self.registry.get(server_name)
        allowed, reason = mcp_permissions.server_allowed(server)
        if not allowed:
            raise PermissionError(reason)
        if not self._slots.acquire(timeout=1.0):
            raise RuntimeError("MCP concurrency limit reached")
        try:
            # Process creation on Windows can transiently miss its deadline
            # when antivirus or a saturated machine delays the stdio child.
            # Discovery is read-only/idempotent, so it gets exactly one retry;
            # actual tool calls are never replayed because their effects may
            # not be idempotent.
            try:
                tools = client.run(server, self.registry.environment_for(server), "list",
                                   timeout_s=server.startup_timeout_s)
            except TimeoutError:
                self._discovery_retries += 1
                time.sleep(0.05)
                tools = client.run(server, self.registry.environment_for(server), "list",
                                   timeout_s=server.startup_timeout_s)
            server.tools = discovery.normalize(tools)
            server.state = CONNECTED
            server.error = ""
            return server.tools
        except TimeoutError as exc:
            server.state = DEGRADED
            server.error = "startup timeout"
            raise RuntimeError("MCP server startup timed out") from exc
        except Exception as exc:
            server.state = FAILED
            server.error = f"{type(exc).__name__}: {redact(exc, limit=200)}"
            self._failures += 1
            raise
        finally:
            server.last_checked = time.time()
            self._slots.release()

    def call(self, server_name: str, tool_name: str, arguments: dict[str, Any] | None = None,
             *, require_read_only: bool = False, timeout_s: float = 60.0) -> dict[str, Any]:
        server = self.registry.get(server_name)
        allowed, reason = mcp_permissions.server_allowed(server)
        if not allowed:
            return {"ok": False, "blocked": True, "reason": reason}
        if not server.tools:
            try:
                self.discover(server_name)
            except Exception as exc:
                return {"ok": False, "error": f"Discovery failed: {type(exc).__name__}: {redact(exc, limit=240)}"}
        definition = next((item for item in server.tools if item["name"] == tool_name), None)
        if definition is None:
            return {"ok": False, "error": f"MCP server '{server_name}' exposes no tool '{tool_name}'."}
        if require_read_only and not mcp_permissions.read_only_hint(definition):
            return {"ok": False, "blocked": True,
                    "reason": "The server did not declare this tool read-only; use the confirmed MCP action path."}
        if not self._slots.acquire(timeout=1.0):
            return {"ok": False, "error": "MCP concurrency limit reached"}
        self._calls += 1
        started = time.perf_counter()
        try:
            result = client.run(server, self.registry.environment_for(server), "call",
                                tool_name=tool_name, arguments=arguments or {}, timeout_s=timeout_s)
            server.state = DEGRADED if result.get("is_error") else CONNECTED
            return {"ok": not result.get("is_error"), "server": server_name, "tool": tool_name,
                    "result": result, "duration_ms": round((time.perf_counter() - started) * 1000, 1)}
        except Exception as exc:
            self._failures += 1
            server.state = FAILED
            server.error = f"{type(exc).__name__}: {redact(exc, limit=240)}"
            return {"ok": False, "server": server_name, "tool": tool_name,
                    "error": server.error, "duration_ms": round((time.perf_counter() - started) * 1000, 1)}
        finally:
            server.last_checked = time.time()
            self._slots.release()

    def status(self) -> dict[str, Any]:
        registry = self.registry.status()
        return {**health.summarize(registry), "sdk_installed": client.installed(),
                "calls": self._calls, "failures": self._failures,
                "discovery_retries": self._discovery_retries,
                "servers": registry["servers"], "allowlist": registry["allowlist"]}

    def shutdown(self) -> None:
        # Clients are per-call async contexts, so there are no persistent
        # subprocesses to join. This method exists for the Kernel contract.
        return None


_manager: MCPManager | None = None
_lock = threading.Lock()


def get_mcp_manager() -> MCPManager:
    global _manager
    if _manager is None:
        with _lock:
            if _manager is None:
                _manager = MCPManager()
    return _manager
