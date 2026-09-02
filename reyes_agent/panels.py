"""Universal Live Panel System -- backend registry + decision engine.

ZENO's UI is a web HUD (reyes_agent/static, served by web.py) wrapped by a thin
PyQt shell. This module is the SERVER side of the panel system: it declares the
panel catalogue, maps ZENO's real capabilities/tools onto panels, and decides
which panel a running command should surface. The browser side
(static/panels/*) renders and manages them, driven by the existing unified
event bus (event_bus -> /api/events/stream).

REUSE, NOT DUPLICATION
- Live events: the existing event_bus + /api/events/stream SSE. No new bus.
- Routing signal: `execution.lifecycle` events already carry the selected tool
  name and stage; the decision engine maps tool -> capability -> panel.
- Capability truth: reyes_agent.routing.capability.CAPABILITIES is the source
  for which tools belong to which capability -- we never re-list tools here.

HONESTY (master prompt s59): a panel is only claimed to render REAL state. Where
the web-in-PyQt stack cannot host a capability (e.g. an embedded cross-origin
browser needs Electron/WebContentsView, which ZENO is not), the panel shows the
real state it CAN (automation status + live screenshots) and says so, rather
than faking it.
"""

from __future__ import annotations

from typing import Any

# --- panel catalogue --------------------------------------------------------
# kind: how the browser renders it. status/support are honest about depth.
#   support "live"    -> renders real streaming state now.
#   support "state"   -> renders real point-in-time/available data now.
#   support "planned" -> registered so routing works; renders an honest
#                        "not yet available on this build" shell, never fake.
def _p(pid, title, icon, *, singleton=True, persistent=False, support="live",
       kind="generic", can_split=True, security="normal") -> dict[str, Any]:
    return {"id": pid, "title": title, "icon": icon, "singleton": singleton,
            "persistent": persistent, "support": support, "kind": kind,
            "canSplit": can_split, "security": security}


PANELS: dict[str, dict[str, Any]] = {
    "activity":      _p("activity", "Activity", "◷", persistent=True,
                        kind="activity"),
    "media":         _p("media", "Media", "♫", persistent=True, kind="media"),
    "system":        _p("system", "System", "▤", persistent=True, kind="system"),
    "agents":        _p("agents", "Agents", "◈", kind="agents"),
    "notifications": _p("notifications", "Notifications", "◉",
                        persistent=True, kind="notifications"),
    "files":         _p("files", "Files", "▧", kind="files"),
    "browser":       _p("browser", "Browser", "◐", kind="browser",
                        support="state"),
    "terminal":      _p("terminal", "Terminal", "▸", kind="terminal"),
    "voice":         _p("voice", "Voice", "◉", persistent=True, kind="voice"),
    "network":       _p("network", "Network", "▥", kind="network",
                        support="state"),
    "editor":        _p("editor", "Editor", "▤", kind="editor",
                        support="state"),
    "image":         _p("image", "Image", "▣", kind="image", support="state"),
    "news":          _p("news", "News", "▤", kind="news", support="state"),
    "search":        _p("search", "Search", "◌", kind="search",
                        support="state"),
    "memory":        _p("memory", "Memory", "◇", kind="memory",
                        support="state"),
    "work":          _p("work", "Work", "▤", kind="work", support="state"),
    "social":        _p("social", "Social", "◉", kind="social",
                        support="state"),
    "security":      _p("security", "Security", "◈", kind="security",
                        support="state"),
    # registered for routing completeness; honest "planned" shells for now.
    "pdf":           _p("pdf", "PDF", "▤", kind="pdf", support="planned"),
    "document":      _p("document", "Document", "▤", kind="document",
                        support="planned"),
    "spreadsheet":   _p("spreadsheet", "Spreadsheet", "▦", kind="spreadsheet",
                        support="planned"),
    "map":           _p("map", "Map", "◈", kind="map", support="planned"),
    "analytics":     _p("analytics", "Analytics", "▦", kind="analytics",
                        support="live"),
    "camera":        _p("camera", "Camera", "▣", kind="camera",
                        support="planned", security="sensitive"),
    "video":         _p("video", "Video", "▷", kind="video", support="planned"),
    "settings":      _p("settings", "Settings", "◉", kind="settings",
                        support="state"),
}

# --- capability -> panel (fallback when no finer tool rule matches) ----------
CAPABILITY_PANEL: dict[str, str] = {
    "media": "media",
    "browser": "browser", "web": "browser",
    "files": "files", "files_destructive": "files",
    "study": "files",
    "coding": "editor",
    "desktop": "system",           # app/window/system control
    "diagnostics": "system",
    "agents": "agents", "council": "agents",
    "communication": "activity", "social": "social",
    "memory": "memory",
    "vision": "image",
    "voice": "voice",
    "presentation": "document",
    "career": "work", "paid_work": "work", "client_work": "work",
    "business": "work", "missions": "work",
    "security": "security",
    "sports": "news", "anime": "news",
    "creative": "image", "builder": "editor",
    "workflow": "activity", "extensions": "settings",
}

# --- tool -> panel overrides (finer than capability) ------------------------
# Only tools whose panel differs from their capability's default need listing.
TOOL_PANEL: dict[str, str] = {
    "media_now_playing": "media", "media_command": "media",
    "media_play_song": "media", "media_panel": "media",
    "media_set_app_volume": "media", "media_control": "media",
    "run_command": "terminal", "coding_execute": "terminal",
    "read_file": "editor", "read_document": "editor",
    "write_project_file": "editor",
    "list_dir": "files", "list_project_files": "files", "open_path": "files",
    "move_file": "files", "content_open": "files",
    "take_screenshot": "image", "read_screen_text": "image",
    "screenshot": "image",
    "browser_screenshot": "browser", "browser_open": "browser",
    "browser_vision_click": "browser", "web_search": "browser",
    "live_news": "news", "get_news": "news",
    "system_health": "system", "system_status": "system", "set_volume": "system",
    "convene_council": "agents",
}


def _tool_capability() -> dict[str, str]:
    """Reverse map tool -> capability, from the capability router's own truth."""
    from reyes_agent.routing.capability import CAPABILITIES
    out: dict[str, str] = {}
    for cap, tools in CAPABILITIES.items():
        for tool in tools:
            out.setdefault(tool, cap)
    return out


def route_tool(tool: str) -> str | None:
    """The panel a tool should surface, or None (no visual panel)."""
    if not tool:
        return None
    if tool in TOOL_PANEL:
        return TOOL_PANEL[tool]
    cap = _tool_capability().get(tool)
    if cap and cap in CAPABILITY_PANEL:
        return CAPABILITY_PANEL[cap]
    return None


def decide(*, tool: str | None = None, capability: str | None = None) -> dict[str, Any]:
    """PanelDecisionEngine: given a tool and/or capability, choose a panel.

    Returns {panel, reason, definition} or {panel: None, reason}. Tool wins
    over capability; unknown/conversation-only actions map to no panel.
    """
    panel = route_tool(tool) if tool else None
    reason = f"tool:{tool}" if panel else ""
    if not panel and capability and capability in CAPABILITY_PANEL:
        panel = CAPABILITY_PANEL[capability]
        reason = f"capability:{capability}"
    if not panel:
        return {"panel": None, "reason": reason or "no visual panel for this action"}
    return {"panel": panel, "reason": reason, "definition": PANELS.get(panel)}


def registry() -> dict[str, Any]:
    """Everything the browser needs to build the panel system: the catalogue,
    the capability->panel map, and the tool->panel overrides."""
    return {
        "panels": PANELS,
        "capability_panel": CAPABILITY_PANEL,
        "tool_panel": TOOL_PANEL,
        "version": 1,
    }
