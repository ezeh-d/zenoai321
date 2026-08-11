"""Bounded, read-only Tailscale CLI adapter."""
from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from .authorization import authorize


def executable() -> str:
    return shutil.which("tailscale") or r"C:\Program Files\Tailscale\tailscale.exe"


def _peer_rows(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    rows = []
    for node in raw.values():
        if not isinstance(node, dict):
            continue
        peer = {
            "id": str(node.get("ID") or node.get("NodeID") or ""),
            "host_name": str(node.get("HostName") or ""),
            "dns_name": str(node.get("DNSName") or "").rstrip("."),
            "os": str(node.get("OS") or ""),
            "online": bool(node.get("Online")),
            "active": bool(node.get("Active")),
            "relay": str(node.get("Relay") or ""),
        }
        peer["authorized"], peer["authorization_reason"] = authorize(peer)
        rows.append(peer)
    return rows


def status(timeout_s: float = 3.0) -> dict[str, Any]:
    path = executable()
    if not shutil.which("tailscale") and not __import__("pathlib").Path(path).exists():
        return {"state": "NOT_CONFIGURED", "installed": False, "connected": False,
                "detail": "Tailscale is not installed", "peers": []}
    try:
        proc = subprocess.run([path, "status", "--json"], capture_output=True, text=True,
                              timeout=max(1.0, min(timeout_s, 10.0)), shell=False,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as exc:
        return {"state": "OFFLINE", "installed": True, "connected": False,
                "detail": type(exc).__name__, "peers": []}
    if proc.returncode != 0:
        return {"state": "OFFLINE", "installed": True, "connected": False,
                "detail": "Tailscale service did not return status", "peers": []}
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return {"state": "DEGRADED", "installed": True, "connected": False,
                "detail": "Tailscale returned invalid JSON", "peers": []}
    backend = str(data.get("BackendState") or "Unknown")
    self_node = data.get("Self") if isinstance(data.get("Self"), dict) else {}
    connected = backend.casefold() == "running" and bool(self_node.get("Online"))
    peers = _peer_rows(data.get("Peer") or {})
    return {
        "state": "ONLINE" if connected else ("AUTH_REQUIRED" if data.get("AuthURL") else "OFFLINE"),
        "installed": True,
        "connected": connected,
        "backend_state": backend,
        "version": str(data.get("Version") or ""),
        "device": {
            "host_name": str(self_node.get("HostName") or ""),
            "dns_name": str(self_node.get("DNSName") or "").rstrip("."),
            "online": bool(self_node.get("Online")),
        },
        "tailnet_configured": bool(data.get("CurrentTailnet")),
        "peer_count": len(peers),
        "authorized_peers": sum(1 for peer in peers if peer["authorized"]),
        "peers": peers,
        "detail": "private transport is connected" if connected else "private transport is not connected",
    }
