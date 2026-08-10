"""Validated MCP server registry; nothing is installed automatically."""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from reyes_agent import config

CONNECTED = "CONNECTED"
DISCONNECTED = "DISCONNECTED"
DEGRADED = "DEGRADED"
FAILED = "FAILED"
STATES = {CONNECTED, DISCONNECTED, DEGRADED, FAILED}
_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")
_DANGEROUS_COMMAND = re.compile(r"[|;&><`\r\n]")


@dataclass
class MCPServer:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    trust_level: str = "untrusted"
    categories: list[str] = field(default_factory=list)
    startup_timeout_s: float = 10.0
    enabled: bool = False
    env_names: list[str] = field(default_factory=list)
    state: str = DISCONNECTED
    tools: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    last_checked: float = 0.0

    def public(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("env_names", None)
        data["args"] = [str(arg)[:160] for arg in self.args]
        return data


class RegistryError(ValueError):
    pass


class MCPRegistry:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser() if path else config.VAULT_PATH / "07-System" / "mcp" / "servers.json"
        self.allowlist = {item.strip() for item in os.environ.get("ZENO_MCP_ALLOWLIST", "").split(",") if item.strip()}
        self._servers: dict[str, MCPServer] = {}
        self._lock = threading.RLock()
        self.reload()

    def reload(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {"servers": []}
        rows = raw.get("servers", []) if isinstance(raw, dict) else []
        loaded: dict[str, MCPServer] = {}
        for item in rows:
            try:
                server = self._parse(item)
            except RegistryError:
                continue
            loaded[server.name] = server
        with self._lock:
            self._servers = loaded

    def _parse(self, item: dict[str, Any]) -> MCPServer:
        if not isinstance(item, dict):
            raise RegistryError("server entry must be an object")
        name = str(item.get("name", "")).strip()
        command = str(item.get("command", "")).strip()
        if not _NAME.fullmatch(name):
            raise RegistryError("invalid server name")
        if not command or _DANGEROUS_COMMAND.search(command):
            raise RegistryError("invalid MCP command; shells and metacharacters are not allowed")
        args = [str(arg) for arg in item.get("args", [])]
        if any(_DANGEROUS_COMMAND.search(arg) for arg in args):
            raise RegistryError("MCP arguments may not contain shell metacharacters")
        permissions = [str(value) for value in item.get("permissions", [])]
        from reyes_agent.permissions import CAPABILITIES
        if any(value not in CAPABILITIES for value in permissions):
            raise RegistryError("MCP server declares an unknown permission")
        enabled = bool(item.get("enabled", False)) and name in self.allowlist
        trust = str(item.get("trust_level", "untrusted")).lower()
        if trust not in {"untrusted", "reviewed", "owner_trusted"}:
            trust = "untrusted"
        return MCPServer(
            name=name, command=command, args=args, permissions=permissions,
            trust_level=trust, categories=[str(value) for value in item.get("categories", [])],
            startup_timeout_s=max(1.0, min(60.0, float(item.get("startup_timeout_s", 10)))),
            enabled=enabled, env_names=[str(value) for value in item.get("env_names", [])],
            state=DISCONNECTED,
        )

    def list(self) -> list[MCPServer]:
        with self._lock:
            return list(self._servers.values())

    def get(self, name: str) -> MCPServer:
        with self._lock:
            server = self._servers.get(str(name))
        if server is None:
            raise RegistryError(f"No allowlisted MCP server named '{name}'.")
        if not server.enabled:
            raise RegistryError(f"MCP server '{name}' is disabled or absent from ZENO_MCP_ALLOWLIST.")
        return server

    def environment_for(self, server: MCPServer) -> dict[str, str]:
        # Explicit names only. A server cannot inherit ZENO's complete .env.
        safe = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC"}
        wanted = safe | {name.upper() for name in server.env_names}
        return {key: value for key, value in os.environ.items() if key.upper() in wanted}

    def status(self) -> dict[str, Any]:
        servers = self.list()
        counts = {state: sum(1 for item in servers if item.state == state) for state in STATES}
        return {"configured": len(servers), "enabled": sum(1 for item in servers if item.enabled),
                "allowlist": sorted(self.allowlist), "states": counts,
                "servers": [item.public() for item in servers]}
