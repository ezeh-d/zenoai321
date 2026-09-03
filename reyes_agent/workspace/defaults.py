"""Declarative default panels and command-palette entries."""

from __future__ import annotations

from reyes_agent.workspace.models import CommandDefinition, PanelDefinition
from reyes_agent.workspace.registry import CommandRegistry, PanelRegistry


_PANELS = (
    PanelDefinition("activity", "Live Activity",
                    "module:/static/activity_view.js#createLiveActivityView",
                    priority=90, preferred_position="right"),
    PanelDefinition("agents", "Agent Workspace", "dom:#agents-overlay", priority=80),
    PanelDefinition("browser", "Browser", "builtin:activity", priority=65),
    PanelDefinition("calendar", "Calendar", "builtin:activity", priority=60),
    PanelDefinition("calls", "Calls", "builtin:activity", priority=70),
    PanelDefinition("coding", "Coding Workspace", "dom:#code-overlay", priority=75),
    PanelDefinition("documents", "Documents", "builtin:search", priority=65),
    PanelDefinition("downloads", "Downloads", "builtin:activity", priority=70),
    PanelDefinition("files", "Files", "builtin:search", priority=75),
    PanelDefinition("history", "Execution History", "builtin:history", priority=70),
    PanelDefinition("images", "Images", "builtin:search", priority=60),
    PanelDefinition("media", "Media", "builtin:activity", priority=70),
    PanelDefinition("messages", "Messages", "builtin:activity", priority=75),
    PanelDefinition("news", "News Workspace", "dom:#news-overlay", priority=65),
    PanelDefinition("notifications", "Notifications", "builtin:activity", priority=65),
    PanelDefinition("proactive", "Proactive", "module:/static/proactive_view.js#createProactiveView",
                    priority=72, preferred_position="right"),
    PanelDefinition("search", "Universal Search", "builtin:search", priority=75),
    PanelDefinition("system", "System", "builtin:health", priority=85),
    PanelDefinition("tasks", "Tasks", "builtin:activity", priority=75),
    PanelDefinition("terminal", "Terminal", "builtin:activity", priority=75),
    PanelDefinition("tool-health", "Tool Health", "builtin:health", priority=90),
    PanelDefinition("weather", "Weather", "builtin:activity", priority=55),
)

_COMMANDS = (
    CommandDefinition("open-activity", "Open Live Activity", "show_panel", "activity",
                      "Show current and recent observable work.", ("task", "progress", "work")),
    CommandDefinition("open-agents", "Open Agent Workspace", "show_panel", "agents",
                      "Show the Council and active agents.", ("council", "agent", "stark", "kate")),
    CommandDefinition("open-files", "Open Files", "show_panel", "files",
                      "Open file search and results.", ("find", "document", "cv")),
    CommandDefinition("open-history", "Open Execution History", "show_panel", "history",
                      "Show safe recent actions and results.", ("last task", "what did you do")),
    CommandDefinition("open-news", "Open News", "show_panel", "news",
                      "Open the news workspace.", ("headlines", "stories")),
    CommandDefinition("open-system", "Open System Panel", "show_panel", "system",
                      "Show live system information.", ("ram", "cpu", "performance")),
    CommandDefinition("open-tool-health", "System Health", "show_panel", "tool-health",
                      "Show evidence-based tool health.", ("ready", "connected", "diagnostics")),
    CommandDefinition("search-workspace", "Search ZENO", "search", "search",
                      "Search commands, tools, panels, agents, settings, and recent work.",
                      ("global", "find", "palette")),
)


def register_default_panels(registry: PanelRegistry) -> None:
    for definition in _PANELS:
        registry.register(definition)


def register_default_commands(registry: CommandRegistry) -> None:
    for definition in _COMMANDS:
        registry.register(definition)


def default_panel_registry() -> PanelRegistry:
    registry = PanelRegistry()
    register_default_panels(registry)
    return registry


def default_command_registry() -> CommandRegistry:
    registry = CommandRegistry()
    register_default_commands(registry)
    return registry
