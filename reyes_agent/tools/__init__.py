"""The tool registry: the one place new capabilities get plugged in.

Adding a capability means writing one function that takes typed keyword
arguments and returns a plain string, then calling `register()` on it in its
own module. The core loop never changes -- it only ever reads from `TOOLS`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    func: Callable[..., str]
    # Read-only tools run immediately. Anything else must go through the
    # Tier 6 confirmation gate once it exists -- flagged here from day one.
    requires_confirmation: bool = False
    # Measured 2026-07-22: Ollama's local tool-calling on this (CPU-only)
    # machine costs ~7-9s of constrained-decoding overhead PER REGISTERED
    # TOOL, independent of description length -- 10 tools took 88s just to
    # decide whether to call one, 2 tools took 13s. Cloud providers don't
    # have this problem. `light=True` marks the tools still offered when
    # MODEL_PROVIDER=ollama, so local mode stays usable; everything is
    # offered again the moment a real cloud key is added.
    light: bool = False


TOOLS: dict[str, Tool] = {}


def register(
    name: str,
    description: str,
    input_schema: dict[str, Any],
    requires_confirmation: bool = False,
    light: bool = False,
) -> Callable[[Callable[..., str]], Callable[..., str]]:
    def decorator(func: Callable[..., str]) -> Callable[..., str]:
        if name in TOOLS:
            raise ValueError(f"Tool '{name}' is already registered")
        TOOLS[name] = Tool(
            name=name,
            description=description,
            input_schema=input_schema,
            func=func,
            requires_confirmation=requires_confirmation,
            light=light,
        )
        return func

    return decorator


# --- lazy tool groups ---------------------------------------------------
# Measured 2026-08-04: sending all 93 tool schemas costs ~5.4s per turn on
# Gemini vs ~1.5s with 5. Tool COUNT, not prompt text, was the dominant
# source of the user's repeated "it's lagging" reports -- even "say hi"
# was shipping ~14k tokens.
#
# So the main agent carries a CORE set covering everything commonly used
# plus each subsystem's ENTRY point, and the deeper per-subsystem
# operations load on demand via `enable_tools`. Nothing is removed --
# specialists still get their scoped sets as before, and ZENO can pull any
# group in mid-turn when a request actually needs it.
TOOL_GROUPS: dict[str, str] = {
    # missions: create/list stay core; the rest load on demand
    "get_mission": "missions", "update_mission": "missions",
    "set_mission_objective_done": "missions",
    # campaigns: create/status core
    "add_campaign_actions": "campaigns", "preview_campaign": "campaigns",
    "approve_campaign": "campaigns", "run_campaign": "campaigns",
    "control_campaign": "campaigns", "retry_campaign_failures": "campaigns",
    # investing: portfolio_report core
    "set_investment_policy": "investing", "get_investment_policy": "investing",
    "record_holding": "investing", "check_trade_against_policy": "investing",
    "record_trade": "investing", "investment_performance_report": "investing",
    # council: convene core
    "list_council_advisors": "council", "list_council_meetings": "council",
    "record_council_outcome": "council",
    # admin/diagnostics
    "list_plugins": "admin", "trust_plugin": "admin", "revoke_plugin": "admin",
    "voice_diagnostics": "admin", "permission_status": "admin",
    "list_capabilities": "admin", "vault_structure_report": "admin",
    "reindex_vault": "admin", "list_scheduled_checks": "admin",
    "cancel_scheduled_check": "admin", "schedule_check": "admin",
    # work tracker
    "track_work": "work", "list_work": "work", "update_work_status": "work",
    # media/creative
    "create_3d_model": "creative", "create_canvas": "creative",
    "create_database_view": "creative", "generate_image": "creative",
    # comms detail
    "read_email": "comms", "add_calendar_event": "comms",
    "list_calendar_events": "comms", "cancel_calendar_event": "comms",
}
GROUP_NAMES = sorted(set(TOOL_GROUPS.values()))


def group_of(name: str) -> str:
    return TOOL_GROUPS.get(name, "core")


def tool_definitions(light_only: bool = False, groups: set[str] | None = None) -> list[dict[str, Any]]:
    """The provider-agnostic shape sent to the model each turn.

    `light_only=True` (used for the Ollama provider -- see agent.py) trims
    the list to the tools marked `light=True`, since tool COUNT is what's
    expensive for local constrained decoding, not any one tool's size.

    `groups` adds non-core groups on top of core (see TOOL_GROUPS). None
    means core only -- the fast default. Cloud providers turn out to care
    about tool count just as much as Ollama does, measured; the difference
    is only where the threshold bites.
    """
    tools = list(TOOLS.values())
    if light_only:
        tools = [t for t in tools if t.light]
    else:
        enabled = groups or set()
        tools = [t for t in tools if group_of(t.name) == "core" or group_of(t.name) in enabled]
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]


def execute_tool(tool: Tool, tool_input: dict[str, Any]) -> str:
    """Actually run a tool's function, never letting it crash the caller.

    A bad input, a missing file, a permissions error -- all come back as a
    plain-language string so the model can react to it instead of the whole
    turn blowing up. This is the raw executor: it does NOT check the
    confirmation gate. `run_tool()` (below) is the gated entry point
    everything else should call; `confirmation.approve_and_run()` calls
    this directly once a human has actually approved.
    """
    from reyes_agent import audit  # deferred -- audit imports config, not tools, so this is safe

    try:
        started = time.time()
        result = tool.func(**tool_input)
        duration = time.time() - started
        try:
            from reyes_agent.performance_monitor import record_latency

            record_latency("tool", duration)
            if tool.name.startswith("browser_"):
                record_latency("browser", duration)
        except Exception:  # noqa: BLE001
            pass
        audit.log("tool_run", tool=tool.name, input=tool_input, result=result)
        # Durable event record -- this is what makes an execution timeline
        # possible. Result is truncated: the bus is a record of what
        # happened, not a second copy of every file ZENO ever read.
        from reyes_agent import event_bus

        event_bus.publish(
            "tool.completed",
            payload={
                "tool": tool.name,
                "input": tool_input,
                "result": (result or "")[:500],
                "duration_ms": int(duration * 1000),
            },
            source="tools",
        )
        return result
    except TypeError as exc:
        return f"Error: bad input for '{tool.name}': {exc}"
    except Exception as exc:  # noqa: BLE001 -- tool failures must reach the model, not crash the loop
        try:
            from reyes_agent.performance_monitor import record_latency

            duration = time.time() - started
            record_latency("tool", duration)
            if tool.name.startswith("browser_"):
                record_latency("browser", duration)
        except Exception:  # noqa: BLE001
            pass
        audit.log("tool_error", tool=tool.name, input=tool_input, error=str(exc))
        return f"Error running '{tool.name}': {exc}"


def _autonomy_allows(name: str) -> bool:
    """Whether a consequential tool may run without stopping to ask.

    Refactored 2026-08-04 to delegate to the Permission Engine
    (reyes_agent/permissions.py) instead of keeping a second, parallel set
    of rules here. One decision point, one place to read the policy --
    autonomy flags living here while plugin rules lived in the loader was
    exactly the drift the roadmap says to avoid.

    AUTONOMY_MODE remains a kill switch: off forces everything
    consequential back through the confirmation gate regardless of profile.
    """
    from reyes_agent import config, permissions

    # Money movement stays hard-blocked here too, independently of the
    # Permission Engine -- two locks, no single point of failure.
    if name in config.AUTONOMY_NEVER_AUTO_TOOLS:
        return False
    if not config.AUTONOMY_MODE:
        return False
    return permissions.check(name) == permissions.ENABLED


def run_tool(name: str, tool_input: dict[str, Any]) -> str:
    """The gated entry point the agent core calls for every tool request.

    Consequential tools (requires_confirmation=True) are either run
    straight through (autonomy mode -- see `_autonomy_allows`) or queued in
    `confirmation` for a human to approve from the web panel. Read-only
    tools always run immediately.
    """
    tool = TOOLS.get(name)
    if tool is None:
        return f"Error: no tool named '{name}' is registered."

    if tool.requires_confirmation and _autonomy_allows(name):
        from reyes_agent import audit

        # Still audited, so an unattended action is never invisible after
        # the fact even though nobody was asked at the time.
        audit.log("autonomy_auto_approved", tool=name, input=tool_input)
        return execute_tool(tool, tool_input)

    if tool.requires_confirmation:
        from reyes_agent import confirmation

        action = confirmation.request(
            tool_name=name, tool_input=tool_input, description=f"{name}({tool_input})"
        )
        return (
            f"Queued as request #{action.id} -- this action needs the user's "
            "explicit approval before it runs, and has NOT run yet. Tell the "
            "user it's waiting for them in the REYES panel; do not claim it's "
            "done and do not retry it yourself."
        )

    return execute_tool(tool, tool_input)


# Import tool modules for their registration side effects.
from reyes_agent.tools import blender, browser, calendar, campaign_tools, companion_tools, council_tools, email_tools, investing, knowledge_tools, memory, missions, notes, obsidian, profile_tools, projects, rag, subagents, system, utility, vision, work, workflow_tools  # noqa: E402,F401

# heartbeat.py lives at the top level (reyes_agent/heartbeat.py), not
# inside tools/, but registers tools the same way -- imported here so
# schedule_check/list_scheduled_checks/cancel_scheduled_check are
# available regardless of which front door starts first. Its own import
# of agent.py is deferred (see heartbeat.py) to avoid a cycle with this line.
from reyes_agent import heartbeat  # noqa: E402,F401

# Same top-level-module-that-registers-tools pattern as heartbeat.
from reyes_agent import activity_monitor  # noqa: E402,F401


def load_plugins() -> list[str]:
    """Load user plugins from vault/07-System/plugins/*.py.

    A plugin is just a Python module that calls `register()` at import --
    the same contract every built-in tool module already uses, so there is
    no separate plugin API to learn or maintain. Loaded last, so a plugin
    can't shadow a built-in (register() raises on duplicate names, and the
    failure is contained to that plugin).

    Gated by the Plugin Permission Manager (permissions.may_load_plugin):
    a plugin must ship a manifest declaring the capabilities it needs, may
    not request a blocked capability, and must be approved by the user at
    its exact version. An updated plugin needs re-approval, so a version
    bump cannot silently widen its reach.

    Still NOT sandboxed once loaded, and that is stated rather than
    implied: an approved plugin is arbitrary Python running with ZENO's
    permissions. The manifest gate controls WHETHER it loads and makes its
    claimed reach visible; it does not confine it afterwards. Real
    confinement needs process isolation and is not built.
    """
    import importlib.util

    from reyes_agent import audit
    from reyes_agent import config as _config
    from reyes_agent import permissions

    plugin_dir = _config.VAULT_PATH / "07-System" / "plugins"
    loaded: list[str] = []
    try:
        plugin_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return loaded
    for path in sorted(plugin_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        manifest = permissions.load_manifest(path)
        allowed, reason = permissions.may_load_plugin(manifest, path.stem)
        if not allowed:
            audit.log("plugin_refused", plugin=path.stem, reason=reason)
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"zeno_plugin_{path.stem}", path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            loaded.append(path.stem)
            audit.log("plugin_loaded", plugin=path.stem,
                      permissions=manifest.permissions if manifest else [])
        except Exception as exc:  # noqa: BLE001 -- one bad plugin must not stop startup
            audit.log("plugin_load_failed", plugin=path.stem, error=str(exc))
    return loaded


_LOADED_PLUGINS = load_plugins()
