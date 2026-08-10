from __future__ import annotations


def summarize(devices: list[dict]) -> dict:
    online = sum(1 for item in devices if item.get("state") == "ONLINE")
    return {"state": "ONLINE" if online == len(devices) and devices else "DEGRADED",
            "online": online, "total": len(devices), "devices": devices}
