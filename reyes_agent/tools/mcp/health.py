"""MCP health aggregation without polling."""

from __future__ import annotations


def summarize(registry_status: dict) -> dict:
    enabled = int(registry_status.get("enabled", 0))
    states = registry_status.get("states", {})
    healthy = int(states.get("CONNECTED", 0))
    failed = int(states.get("FAILED", 0))
    state = "STANDBY" if not enabled else ("FAILED" if failed == enabled else ("DEGRADED" if failed else "ONLINE"))
    return {"state": state, "healthy": healthy, "enabled": enabled,
            "configured": int(registry_status.get("configured", 0)), "failed": failed}
