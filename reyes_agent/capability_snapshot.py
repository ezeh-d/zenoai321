"""What ZENO can actually do, read from the REAL registry (JARVIS/ULTRON #89-96, #108).

The brief's core demand: ZENO must know its true capabilities and never fake
one (#91). This is the system-wide front door for that -- it reads the live tool
registry, the capability->tools map, the circuit breaker and the capability-truth
store, and rolls them into an honest answer to "what can you do?", "can you X?",
and the #108 system status. It INVENTS nothing: an area with no registered tools
is reported as not connected, not as "coming soon". Read-only, never raises.

It complements, not duplicates, `capability_truth` (per-capability proof) and
`capability_snapshot` (system-wide roll-up from the registry).
"""

from __future__ import annotations

from typing import Any

# Human labels for the capability areas the router already defines.
_AREA_LABELS = {
    "conversation": "Conversation", "utility": "Utilities", "memory": "Memory",
    "web": "Web research", "browser": "Browser control", "desktop": "Desktop control",
    "files": "Files", "coding": "Coding", "vision": "Screen vision",
    "agents": "Agents", "council": "Council", "security": "Security",
    "communication": "Messaging", "voice": "Voice", "creative": "Creative studio",
    "missions": "Missions", "diagnostics": "Diagnostics", "anime": "Anime/manga",
    "language": "Language", "social": "Social media", "business": "Business",
    "career": "Career", "presentation": "Presentation", "workflow": "Workflows",
}


def tool_inventory() -> dict[str, Any]:
    """Live count + names from the tool registry. Empty on any failure."""
    try:
        from reyes_agent.tools import TOOLS

        return {"registered": len(TOOLS), "names": sorted(TOOLS)}
    except Exception:  # noqa: BLE001
        return {"registered": 0, "names": []}


def by_area() -> list[dict[str, Any]]:
    """Each capability area with how many of its tools are actually registered.
    `connected` = at least one real tool is present (the no-fake test)."""
    try:
        from reyes_agent.routing.capability import CAPABILITIES
        from reyes_agent.tools import TOOLS
    except Exception:  # noqa: BLE001
        return []
    out = []
    for area, tools in CAPABILITIES.items():
        present = [t for t in tools if t in TOOLS]
        out.append({
            "area": area,
            "label": _AREA_LABELS.get(area, area.replace("_", " ").title()),
            "tools_total": len(tools),
            "tools_connected": len(present),
            "connected": len(present) > 0,
        })
    out.sort(key=lambda a: a["label"])
    return out


def can_i(name: str) -> dict[str, Any]:
    """Honest answer to "can you <tool-or-area>?" -- registered? healthy? proven?
    Never claims a capability that is not really wired (#91)."""
    key = str(name or "").strip()
    result: dict[str, Any] = {"query": key, "connected": False, "reason": ""}
    if not key:
        result["reason"] = "no capability named"
        return result
    try:
        from reyes_agent.tools import TOOLS

        area_map = by_area()
        area = next((a for a in area_map if a["area"] == key.casefold()), None)
        if area is not None:
            result["connected"] = area["connected"]
            result["reason"] = (f"{area['tools_connected']}/{area['tools_total']} tools connected"
                                if area["connected"] else "no tools connected in this area")
            return result
        if key in TOOLS:
            result["connected"] = True
            result["reason"] = "tool is registered"
            try:
                from reyes_agent import circuit_breaker

                if circuit_breaker.is_open(key):
                    result["healthy"] = False
                    result["reason"] = "registered but temporarily quarantined (recent failures)"
                else:
                    result["healthy"] = True
            except Exception:  # noqa: BLE001
                pass
            return result
        result["reason"] = "no such tool or capability is connected"
        return result
    except Exception:  # noqa: BLE001
        result["reason"] = "registry unavailable"
        return result


def what_can_i_do() -> dict[str, Any]:
    """The answer to "ZENO, what can you do?" -- grouped, from the real registry."""
    areas = by_area()
    inv = tool_inventory()
    return {
        "tool_count": inv["registered"],
        "connected_areas": [{"area": a["area"], "label": a["label"],
                             "tools": a["tools_connected"]}
                            for a in areas if a["connected"]],
        "not_connected": [a["label"] for a in areas if not a["connected"]],
    }


def system_status() -> dict[str, Any]:
    """A #108-style honest roll-up: registry size, connected areas, quarantined
    tools, proven-active capabilities, and feature flags. Every field is read
    live; nothing is asserted that the registry does not back."""
    status: dict[str, Any] = {"tools": tool_inventory()["registered"]}
    areas = by_area()
    status["areas_connected"] = sum(1 for a in areas if a["connected"])
    status["areas_total"] = len(areas)
    status["areas"] = [{"label": a["label"], "connected": a["connected"],
                        "tools": a["tools_connected"]} for a in areas]
    # Quarantined tools (breaker OPEN) -- honestly degraded right now.
    try:
        from reyes_agent import circuit_breaker

        status["quarantined"] = [s["name"] for s in circuit_breaker.get_breaker().snapshot()
                                 if s["state"] == "OPEN"]
    except Exception:  # noqa: BLE001
        status["quarantined"] = []
    # Proven-active capabilities (capability_truth, no-fake rule).
    try:
        from reyes_agent import capability_truth

        capability_truth.seed_baseline()
        status["proven_active"] = [row["name"] for row in capability_truth.get_truth().dashboard()
                                   if row.get("active")]
    except Exception:  # noqa: BLE001
        status["proven_active"] = []
    # Experimental feature flags that are ON.
    try:
        from reyes_agent import feature_flags

        status["flags_on"] = [f["name"] for f in feature_flags.get_flags().all_flags()
                              if f["enabled"]]
    except Exception:  # noqa: BLE001
        status["flags_on"] = []
    # Gated provider adapters (camera/smart-home/robotics + external services):
    # each reported with its true readiness so ZENO can say "that needs setup"
    # rather than faking it. Off by default (#91, JARVIS/ULTRON #96, #110).
    try:
        from reyes_agent import adapters

        status["adapters"] = adapters.get_registry().dashboard()
    except Exception:  # noqa: BLE001
        status["adapters"] = []
    return status
