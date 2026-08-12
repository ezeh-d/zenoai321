"""The tool registry: the one place new capabilities get plugged in.

Adding a capability means writing one function that takes typed keyword
arguments and returns a plain string, then calling `register()` on it in its
own module. The core loop never changes -- it only ever reads from `TOOLS`.
"""

from __future__ import annotations

import json
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


def _audit_safe(value: Any, *, depth: int = 0) -> Any:
    """Bound and redact persisted diagnostics without changing tool inputs."""
    if depth > 4:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        out = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 80:
                out["..."] = "[TRUNCATED]"
                break
            label = str(key)
            if any(marker in label.casefold() for marker in ("password", "passwd", "secret", "token", "api_key", "apikey", "cookie", "credential", "private_key")):
                out[label] = "[REDACTED]"
            elif label.casefold() in {"message", "content", "body", "code", "value"} and isinstance(item, str):
                # Consequential-action logs need the operation and target,
                # not a durable second copy of messages, form values, file
                # bodies, or source code. Length is enough for diagnostics.
                out[label] = f"[REDACTED_CONTENT {len(item)} chars]"
            else:
                out[label] = _audit_safe(item, depth=depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_audit_safe(item, depth=depth + 1) for item in value[:80]]
    if isinstance(value, str):
        try:
            from reyes_agent.memory.privacy import redact
            return redact(value, limit=4000)
        except Exception:
            return value[:4000]
    return value


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
    # Next-intelligence operations stay lazy so capability breadth does not
    # regress the measured default provider payload. Direct stop/cancel is
    # intercepted before model planning, so it does not need a core schema.
    "interrupt_work": "intelligence", "capability_status": "intelligence",
    "action_history": "intelligence", "undo_last_actions": "intelligence",
    "current_situation": "intelligence", "universal_search": "intelligence",
    "resolve_time": "intelligence", "simulate_plan": "intelligence",
    "health_center": "intelligence", "remember_relationship": "intelligence",
    "search_relationships": "intelligence", "forget_relationship": "intelligence",
    "save_mission_runtime_state": "intelligence", "load_mission_runtime_state": "intelligence",
    "current_situation_report": "intelligence", "learned_patterns": "intelligence",
    # Creator/Mastery/Foodie are compact explicit-state entry points. Keeping
    # them core avoids a discovery round, while their work remains local and
    # event-driven -- no specialist or background service is started merely
    # because they are registered.
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
    "memory_backend_status": "admin", "memory_migration_preview": "admin",
    "memory_migrate_to_mem0": "admin",
    "list_capabilities": "admin", "vault_structure_report": "admin",
    "reindex_vault": "admin", "list_scheduled_checks": "admin",
    "cancel_scheduled_check": "admin", "schedule_check": "admin",
    # work tracker
    "track_work": "work", "list_work": "work", "update_work_status": "work",
    # media/creative
    "create_3d_model": "creative", "create_canvas": "creative",
    "create_database_view": "creative", "generate_image": "creative",
    # `learning_mode` is intentionally CORE: it is one compact entry point
    # for an explicit owner lesson, while screenshot critique remains lazy.
    "critique_current_design": "creative",
    # comms detail
    "read_email": "comms", "add_calendar_event": "comms",
    "list_calendar_events": "comms", "cancel_calendar_event": "comms",
    # Real-execution builds. `build_project` itself stays CORE -- it is the
    # entry point for every "create/build/save it on my Desktop" request, and
    # a request that has to spend a round discovering the tool is a request
    # that gets answered with an explanation instead. The follow-ups load
    # automatically the moment a build starts (see agent.py).
    "build_add_files": "build", "build_status": "build",
    "cancel_build": "build", "build_environment": "build",
    # Phase 2 specialists and external tool bus stay out of the default
    # provider payload. Their entry points load only for relevant turns.
    "coding_inspect": "coding", "coding_execute": "coding",
    "mcp_status": "mcp", "mcp_discover": "mcp", "mcp_read": "mcp", "mcp_action": "mcp",
    "device_status": "devices", "device_observe": "devices", "device_execute": "devices",
    "code_proof": "presentation", "engineering_challenges": "presentation",
    "learning_portfolio": "presentation", "project_evolution": "presentation",
    "offline_presentation": "presentation", "should_divine_answer": "presentation",
    "visitor_said": "presentation", "visit_topic": "presentation",
    "owner_directive": "presentation", "visit_status": "presentation",
    "rehearse_visit": "presentation",
    "design_tool_check": "creative",
    "plan_message_request": "comms", "messaging_status": "comms",
    "agent_roster": "agents", "who_is_agent": "agents",
    "agent_role_call": "agents", "agent_workers": "agents",
    "phone_mic_networks": "devices", "phone_mic_qr": "devices",
    "phone_mic_set_network": "devices", "phone_mic_current_network": "devices",
    "episodic_search": "phase3", "read_document_structured": "phase3",
    "knowledge_graph_query": "phase3", "knowledge_graph_remember": "phase3",
    "engineering_backends": "phase3", "mobile_device_status": "phase3",
    "sandbox_status": "phase3",
    # Durable Phase 4 skills remain out of ordinary turns. The agent adds
    # this group only for an explicit skill/routine request or a real trigger
    # match against an approved skill.
    "skill_list": "skills", "skill_inspect": "skills", "skill_scan": "skills",
    "skill_approve": "skills", "skill_disable": "skills", "skill_delete": "skills",
    "skill_run": "skills",
    # Phase 5 data/private-network tools are loaded only for matching turns.
    "phase5_status": "phase5", "inspect_dataset": "analytics",
    "query_dataset": "analytics", "private_network_status": "phase5",
    "notification_summary": "phase5",
    # Worker teams. Grouped ONLY to keep call_worker out of ZENO's core
    # payload -- ZENO delegates to a commander, it never calls a commander's
    # worker itself, so a core schema here would be pure per-turn token cost
    # (the exact thing that caused the measured lag) for a tool that would
    # only ever return "not a primary specialist". _run_specialist adds it
    # explicitly to commanders that actually have a team.
    "call_worker": "agent_workers",
}

# The old fallback treated every tool absent from ``TOOL_GROUPS`` as core.
# As ZENO grew that silently expanded the supposedly-small provider payload
# to 94 schemas (44,588 JSON characters, measured 2026-08-11).  Keep only
# the genuine entry points here.  Everything else remains available through
# the existing ``enable_tools('extended')`` on-demand round.
CORE_TOOL_NAMES = frozenset({
    "enable_tools", "delegate", "open_app", "web_search", "build_project",
    "website_project", "learning_mode", "creator_project", "mastery_mode",
    "foodie_mode", "phase3_status", "system_health",
})
GROUP_NAMES = sorted(set(TOOL_GROUPS.values()) | {"extended"})


_FAILED_RESULT_STATES = {
    "error", "failed", "failure", "blocked", "denied", "cancelled",
    "canceled", "timed_out", "timeout", "unavailable", "rejected",
}
_WAITING_RESULT_STATES = {
    "pending", "queued", "waiting", "waiting_for_input",
    "waiting_for_confirmation", "accepted",
}


def classify_tool_result(result: Any) -> dict[str, Any]:
    """Classify observable output without promoting a return to success.

    A subsystem returning normally is not proof that its requested effect
    happened. Only explicit verification evidence produces ``completed``;
    ordinary data is ``returned`` and remains usable by the agent without a
    false success event.
    """
    parsed: Any = result
    text_value = str(result or "").strip()
    if isinstance(result, str) and text_value[:1] in {"{", "["}:
        try:
            parsed = json.loads(text_value)
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = result

    state = ""
    verified = False
    has_evidence = False
    if isinstance(parsed, dict):
        state = str(parsed.get("state") or parsed.get("status") or parsed.get("outcome") or "").strip().casefold()
        if parsed.get("ok") is False or parsed.get("success") is False or state in _FAILED_RESULT_STATES:
            from reyes_agent.failures import classify
            return {"outcome": "failed", "verification_state": "failed", "state": state,
                    "error_category": classify(text_value)}
        if state in _WAITING_RESULT_STATES:
            return {"outcome": "waiting", "verification_state": "pending", "state": state}
        verified = parsed.get("verified") is True or str(parsed.get("verification_state", "")).casefold() == "verified"
        has_evidence = bool(parsed.get("evidence") or parsed.get("verification_evidence"))
        verified = verified or (parsed.get("ok") is True and has_evidence)

    lowered = text_value.casefold()
    if any(lowered.startswith(prefix) for prefix in (
        "error", "failed", "failure", "blocked", "denied", "refused",
        "unavailable", "timed out", "timeout", "browser error", "couldn't",
        "could not", "no element matches", "nothing matches", "vision match failed",
        "telegram did not confirm",
    )):
        from reyes_agent.failures import classify
        return {"outcome": "failed", "verification_state": "failed", "state": state,
                "error_category": classify(text_value)}
    if any(lowered.startswith(prefix) for prefix in (
        "queued", "pending", "waiting", "accepted for", "approval required",
    )):
        return {"outcome": "waiting", "verification_state": "pending", "state": state}
    # Existing file/build/browser executors include a concrete verification
    # marker only after their postcondition check passes.
    if any(marker in lowered for marker in (
        "verified on disk", "build completed and verified", "verification passed",
        "verified evidence", "postcondition verified",
    )):
        verified = True
    return {
        "outcome": "completed" if verified else "returned",
        "verification_state": "verified" if verified else "unverified",
        "state": state,
        "error_category": "",
    }


def _publish_tool_failure(tool: Tool, tool_input: dict[str, Any], error: str,
                          duration: float) -> None:
    try:
        from reyes_agent import event_bus, intelligence

        safe_input = _audit_safe(tool_input)
        intelligence.update_situation(current_task=tool.name, current_step="failed")
        event_bus.publish("tool.failed", payload={
            "tool": tool.name,
            "input": safe_input,
            "result": _audit_safe(error),
            "duration_ms": int(max(0.0, duration) * 1000),
            "outcome": "failed",
            "verification_state": "failed",
        }, source="tools")
    except Exception:  # noqa: BLE001 -- failure reporting cannot mask cause
        pass


def group_of(name: str) -> str:
    if name in CORE_TOOL_NAMES:
        return "core"
    return TOOL_GROUPS.get(name, "extended")


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
        from reyes_agent.observability import span
        with span("tool.execute", attributes={"tool": tool.name, "input": _audit_safe(tool_input)}):
            result = tool.func(**tool_input)
        duration = time.time() - started
        try:
            from reyes_agent.performance_monitor import record_latency

            record_latency("tool", duration)
            if tool.name.startswith("browser_"):
                record_latency("browser", duration)
        except Exception:  # noqa: BLE001
            pass
        safe_input = _audit_safe(tool_input)
        safe_result = _audit_safe(result)
        outcome = classify_tool_result(result)
        audit.log("tool_result", actor="zeno", action=tool.name,
                  policy="permission_engine", outcome=outcome["outcome"],
                  verification_state=outcome["verification_state"],
                  error_category=outcome.get("error_category", ""),
                  duration_ms=int(duration * 1000), input=safe_input, result=safe_result)
        # The next-intelligence layer records an intentionally bounded action
        # history and current observable task.  It never becomes a second
        # executor; this remains the one gated tool path.
        try:
            from reyes_agent import intelligence

            intelligence.record_tool_execution(tool.name, safe_input, str(safe_result))
            intelligence.update_situation(current_task=tool.name,
                                          current_step=outcome["outcome"])
        except Exception:  # noqa: BLE001 -- action history cannot break a tool
            pass
        # Durable event record -- this is what makes an execution timeline
        # possible. Result is truncated: the bus is a record of what
        # happened, not a second copy of every file ZENO ever read.
        from reyes_agent import event_bus

        event_bus.publish(
            f"tool.{outcome['outcome']}",
            payload={
                "tool": tool.name,
                "input": safe_input,
                "result": str(safe_result or "")[:500],
                "duration_ms": int(duration * 1000),
                "outcome": outcome["outcome"],
                "verification_state": outcome["verification_state"],
                "error_category": outcome.get("error_category", ""),
            },
            source="tools",
        )
        return result
    except TypeError as exc:
        duration = time.time() - started
        message = f"Error: bad input for '{tool.name}': {exc}"
        audit.log("tool_error", actor="zeno", action=tool.name,
                  policy="permission_engine", outcome="failed",
                  duration_ms=int(duration * 1000), input=_audit_safe(tool_input),
                  error=_audit_safe(str(exc)))
        _publish_tool_failure(tool, tool_input, message, duration)
        return message
    except Exception as exc:  # noqa: BLE001 -- tool failures must reach the model, not crash the loop
        try:
            from reyes_agent.performance_monitor import record_latency

            duration = time.time() - started
            record_latency("tool", duration)
            if tool.name.startswith("browser_"):
                record_latency("browser", duration)
        except Exception:  # noqa: BLE001
            pass
        audit.log("tool_error", actor="zeno", action=tool.name,
                  policy="permission_engine", outcome="failed",
                  duration_ms=int(duration * 1000), input=_audit_safe(tool_input),
                  error=_audit_safe(str(exc)))
        _publish_tool_failure(tool, tool_input,
                              f"Error running '{tool.name}': {exc}", duration)
        try:
            from reyes_agent import intelligence

            intelligence.update_situation(current_task=tool.name, current_step="failed")
        except Exception:  # noqa: BLE001
            pass
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

    # The model only sees a scoped tool list, but model output is untrusted.
    # Enforce the active specialist/worker profile again at the execution
    # boundary so prompt injection cannot manufacture an out-of-role call.
    from reyes_agent.security.capabilities import authorize_arguments, authorize_tool
    capability_ok, capability_reason, capability_actor = authorize_tool(name)
    if not capability_ok:
        try:
            from reyes_agent import audit, event_bus
            audit.log("capability_denied", actor=capability_actor, action=name,
                      policy="agent_capability_profile", outcome="blocked",
                      reason=capability_reason)
            event_bus.publish("security.capability_denied", {
                "agent": capability_actor, "tool": name, "reason": capability_reason,
            }, source="tools")
        except Exception:  # denial reporting must never permit execution
            pass
        return f"Blocked: {capability_reason}. Nothing ran."
    arguments_ok, arguments_reason, capability_actor = authorize_arguments(tool_input)
    if not arguments_ok:
        try:
            from reyes_agent import audit, event_bus
            audit.log("capability_denied", actor=capability_actor, action=name,
                      policy="agent_capability_profile", outcome="blocked", reason=arguments_reason)
            event_bus.publish("security.capability_denied", {
                "agent": capability_actor, "tool": name, "reason": arguments_reason,
            }, source="tools")
        except Exception:
            pass
        return f"Blocked: {arguments_reason}. Nothing ran."

    # Contextual Phase 3 policy does not replace permissions.py; it is the
    # constitution facade over that same authority and adds immutable critical
    # action denial. Every registered tool reaches this point.
    from reyes_agent.security.policy import CONFIRM as POLICY_CONFIRM
    from reyes_agent.security.policy import DENY as POLICY_DENY
    from reyes_agent.security.policy import decide as policy_decide
    policy = policy_decide(name)
    if policy.effect == POLICY_DENY:
        return f"Blocked: {policy.reason}. Nothing ran."

    # Permission state applies to EVERY declared capability, not only tools
    # which also happened to set requires_confirmation=True. Previously a
    # cautious-profile capability could say CONFIRM while a read-looking
    # tool ran immediately because only the tool flag was consulted here.
    from reyes_agent import permissions

    permission_state = permissions.check(name)
    if permission_state == permissions.BLOCKED:
        capability = permissions.capability_for_tool(name) or name
        return f"Blocked: capability '{capability}' is disabled by ZENO's permission policy. Nothing ran."

    # A tool call whose arguments were cut off at the model's output limit
    # (see provider.py). Nothing ran, and saying so plainly is what lets the
    # model split the work up instead of quietly reporting a build it never
    # performed.
    if "__truncated_arguments__" in tool_input:
        size = tool_input["__truncated_arguments__"]
        return (
            f"Error: your call to '{name}' was cut off after {size} characters, so its "
            "arguments were incomplete and NOTHING RAN. Split the work into smaller "
            "calls -- for build_project, send the main files first with finish=false, "
            "then call build_add_files with the task_id for the rest."
        )

    # Voice identity is request-scoped and server-signed. It can protect
    # private retrieval, but never becomes authority for a consequential
    # action: desktop confirmation remains a separate factor.
    try:
        from reyes_agent import speaker_identity

        denial = speaker_identity.privacy_denial(name)
        if denial:
            return denial
        voice_requires_confirmation = speaker_identity.requires_strong_confirmation(name)
    except Exception:  # noqa: BLE001 -- identity diagnostics cannot break tools
        voice_requires_confirmation = False

    # Confidence is evidence-backed: model providers do not currently emit a
    # calibrated intent score, so a high-risk tool has *unknown* confidence
    # rather than a fabricated positive number.  That unknown state is a
    # reason not to auto-approve consequential actions, even on a trusted
    # local installation. Low-risk/read-only tools still run without friction.
    from reyes_agent.confidence import decide_tool

    confidence = decide_tool(name, requires_confirmation=tool.requires_confirmation)
    must_confirm = (tool.requires_confirmation or policy.effect == POLICY_CONFIRM
                    or confidence.requires_confirmation
                    or voice_requires_confirmation or permission_state == permissions.CONFIRM)

    if (must_confirm and _autonomy_allows(name) and not confidence.requires_confirmation
            and not voice_requires_confirmation):
        from reyes_agent import audit

        # Still audited, so an unattended action is never invisible after
        # the fact even though nobody was asked at the time.
        audit.log("autonomy_auto_approved", tool=name, input=tool_input)
        return execute_tool(tool, tool_input)

    if must_confirm:
        from reyes_agent import confirmation

        action = confirmation.request(
            tool_name=name, tool_input=tool_input,
            description=(f"{name}({tool_input}) — confidence: {confidence.reason}"
                         + (" — voice identity is not enough; complete desktop confirmation."
                            if voice_requires_confirmation else "")),
        )
        return (
            f"Queued as request #{action.id} -- this action needs the user's "
            "explicit approval before it runs, and has NOT run yet. Tell the "
            "user it's waiting for them in the REYES panel; do not claim it's "
            "done and do not retry it yourself."
        )

    return execute_tool(tool, tool_input)


# Import tool modules for their registration side effects.
from reyes_agent.tools import awareness_tools, blender, browser, build, calendar, campaign_tools, coding_system, companion_tools, council_tools, design, devices, email_tools, intelligence_tools, investing, knowledge_tools, mcp_tools, media_recognition, memory, missions, notes, obsidian, agent_identity, evidence_tools, mode_tools, messaging_tools, visit_tools, ocr_tools, phase3_tools, phase5_tools, phone_network, profile_tools, projects, rag, skills, subagents, system, utility, vision, website, work, workflow_tools  # noqa: E402,F401

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
        # Executed inside the capability sandbox (plugin_sandbox.py) rather
        # than imported normally, so the manifest is ENFORCED at run time
        # instead of merely inspected at load time. A plugin declaring
        # filesystem_read can no longer quietly shell out or open a socket.
        from reyes_agent import plugin_sandbox

        granted = set(manifest.permissions) if manifest else set()
        ok, message = plugin_sandbox.execute_plugin(path, path.stem, granted)
        if ok:
            loaded.append(path.stem)
            audit.log("plugin_loaded", plugin=path.stem, permissions=sorted(granted))
        else:
            audit.log("plugin_load_failed", plugin=path.stem, error=message)
    return loaded


_LOADED_PLUGINS = load_plugins()
