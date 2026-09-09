"""Universal Live Panel System -- backend registry + decision engine.

ZENO's UI is a web HUD (reyes_agent/static, served by web.py) wrapped by a thin
pywebview shell (see desktop_app.py). This module is the SERVER side of the panel system: it declares the
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
    "hunter_x": _p("hunter_x", "HUNTER X", "◇", kind="hunter_x", support="state"),
    "teaching":      _p("teaching", "Teaching Whiteboard", "▥", kind="teaching",
                        support="live"),
    "activity":      _p("activity", "Activity", "◷", persistent=True,
                        kind="activity"),
    "media":         _p("media", "Media", "♫", persistent=True, kind="media"),
    "system":        _p("system", "System", "▤", persistent=True, kind="system"),
    "agents":        _p("agents", "Agents", "◈", kind="agents"),
    "notifications": _p("notifications", "Notifications", "◉",
                        persistent=True, kind="notifications"),
    "proactive":     _p("proactive", "Proactive", "✦", persistent=True,
                        kind="proactive"),
    "ragebait":      _p("ragebait", "Ragebait Battle", "⚡", kind="ragebait",
                        support="live"),
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
    "hunter_x": "hunter_x",
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
    "teaching_board": "teaching", "write_lesson_to_notepad": "teaching",
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


# --- Panel Request API -------------------------------------------------------
# An agent (master prompt s62-64: "agents request, ZENO/Panel Manager owns the
# environment") asks for a workspace instead of inventing its own window. This
# is deliberately separate from route_tool()/decide() above -- those infer a
# panel from WHICH TOOL ran; this is an EXPLICIT ask with a reason and an
# owner, for panels a tool-name mapping would not otherwise reach (e.g. Kate
# opening the Files panel mid-explanation, not because a file tool ran).
import threading
import time

_ownership_lock = threading.RLock()
_OWNERSHIP: dict[str, dict[str, Any]] = {}  # panel type -> {agent, reason, task_id, opened_at}


def request_panel(agent_id: str, panel_type: str, *, reason: str = "", task_id: str = "") -> dict[str, Any]:
    """Validate and record one agent's request for a workspace, then tell the
    browser side to actually open/focus it via the existing event bus (no new
    IPC channel). ZENO/this module remains the authority: an unregistered
    panel type is refused outright rather than silently doing nothing."""
    agent = str(agent_id or "zeno").strip().casefold() or "zeno"
    panel = str(panel_type or "").strip().casefold()
    definition = PANELS.get(panel)
    if definition is None:
        return {"granted": False, "panel": panel,
                "reason": f"no such panel '{panel_type}'. Registered: {', '.join(sorted(PANELS))}."}
    with _ownership_lock:
        _OWNERSHIP[panel] = {"agent": agent, "reason": str(reason or "")[:200],
                             "task_id": str(task_id or "")[:80], "opened_at": time.time()}
    _publish("panel.requested", {"agent": agent, "panel": panel, "reason": str(reason or "")[:200],
                                 "task_id": str(task_id or "")[:80], "title": definition["title"]})
    return {"granted": True, "panel": panel, "agent": agent, "definition": definition}


def release_panels_for(agent_id: str) -> list[str]:
    """An agent leaving the conversation (master prompt s75) releases what it
    asked for -- and only what it asked for; a panel ZENO or another still-
    active agent also owns is never touched here."""
    agent = str(agent_id or "").strip().casefold()
    if not agent:
        return []
    with _ownership_lock:
        released = [panel for panel, info in _OWNERSHIP.items() if info["agent"] == agent]
        for panel in released:
            del _OWNERSHIP[panel]
    if released:
        _publish("panel.release_for_agent", {"agent": agent, "panels": released})
    return released


def owner_of(panel_type: str) -> str:
    """Which agent currently owns a panel, or "" if unowned/unknown."""
    with _ownership_lock:
        info = _OWNERSHIP.get(str(panel_type or "").strip().casefold())
        return info["agent"] if info else ""


def reset_ownership_for_tests() -> None:
    with _ownership_lock:
        _OWNERSHIP.clear()


def _publish(event_type: str, payload: dict[str, Any]) -> None:
    try:
        from reyes_agent import event_bus

        event_bus.publish(event_type, payload, source="panels")
    except Exception:  # noqa: BLE001 -- a panel request must never break a turn
        pass
