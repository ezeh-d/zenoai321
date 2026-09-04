"""The tool registry: the one place new capabilities get plugged in.

Adding a capability means writing one function that takes typed keyword
arguments and returns a plain string, then calling `register()` on it in its
own module. The core loop never changes -- it only ever reads from `TOOLS`.
"""

from __future__ import annotations

import json
import threading
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
    # Some read-only tools handle private transcripts/drafts. Their content
    # is returned to the active model turn but must not be duplicated into
    # durable audit, Event Bus, span, or action-history payloads.
    audit_private: bool = False
    # Proactive checks are opt-in and must be read-only/bounded.  This is
    # metadata only; action policy and confirmation remain authoritative.
    proactive_allowed: bool = False

    def metadata(self) -> dict[str, bool]:
        return {
            "requiresConfirmation": self.requires_confirmation,
            "proactiveAllowed": self.proactive_allowed and not self.requires_confirmation,
        }


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
            elif label.casefold() in {"message", "content", "body", "code", "value", "text"} and isinstance(item, str):
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


def _tool_audit_input(tool: Tool, value: dict[str, Any]) -> Any:
    if not tool.audit_private:
        return _audit_safe(value)
    conversation = value.get("conversation")
    return {
        "private_content_redacted": True,
        "fields": sorted(str(key) for key in value),
        "instruction_chars": len(str(value.get("instruction") or "")),
        "conversation_messages": len(conversation) if isinstance(conversation, (list, tuple)) else 0,
        "mode": str(value.get("mode") or "")[:40],
        "feature": str(value.get("feature") or "")[:40],
        "requested_candidates": value.get("count", 0),
    }


def diagnostic_tool_input(name: str, value: dict[str, Any]) -> Any:
    """Return the registry's bounded audit representation for diagnostics.
    Used by the conversation tool-transaction ledger to record a tool call
    without ever storing a secret argument in the clear."""
    tool = TOOLS.get(str(name))
    return _tool_audit_input(tool, value) if tool else _audit_safe(value)


def _tool_audit_result(tool: Tool, value: Any) -> Any:
    if not tool.audit_private:
        return _audit_safe(value)
    return f"[PRIVATE_TOOL_RESULT {len(str(value or ''))} chars]"


def register(
    name: str,
    description: str,
    input_schema: dict[str, Any],
    requires_confirmation: bool = False,
    light: bool = False,
    audit_private: bool = False,
    proactive_allowed: bool = False,
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
            audit_private=audit_private,
            proactive_allowed=proactive_allowed,
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
    # Context-specific local intelligence: activated deterministically in
    # agent.py before provider schemas are built, never carried on ordinary
    # conversation turns.
    "charm_reply": "charm", "charm_analyze": "charm",
    "charm_set_mode": "charm", "charm_status": "charm",
    "charm_feedback": "charm", "charm_coach": "charm",
    "spatial_remember": "spatial", "spatial_move": "spatial",
    "spatial_where_is": "spatial", "spatial_room_state": "spatial",
    "spatial_recent": "spatial", "spatial_events_at": "spatial",
    "spatial_events_when": "spatial", "spatial_recall": "spatial",
    "spatial_memory_status": "spatial",
    # Next-intelligence operations stay lazy so capability breadth does not
    # regress the measured default provider payload. Direct stop/cancel is
    # intercepted before model planning, so it does not need a core schema.
    "interrupt_work": "intelligence", "capability_status": "intelligence",
    "action_history": "intelligence", "undo_last_actions": "intelligence",
    "current_situation": "intelligence", "universal_search": "intelligence",
    "simulate_plan": "intelligence",
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
    "universal_tool_catalog": "admin", "universal_tool_health": "admin",
    "universal_tool_resolve": "admin",
    "reindex_vault": "admin", "list_scheduled_checks": "admin",
    "cancel_scheduled_check": "admin", "schedule_check": "admin",
    # work tracker
    "track_work": "work", "list_work": "work", "update_work_status": "work",
    # Owner-verified job/freelance profile source of truth. External browser
    # actions remain in the existing browser capability and permission gate.
    "career_profile_status": "career", "career_profile_read": "career",
    "career_profile_update": "career", "career_profile_fill_field": "career",
    "career_platform_plan": "career",
    # Complete paid-work lifecycle stays absent from ordinary turns.
    "paid_work_status": "paid_work", "paid_work_scout": "paid_work",
    "paid_work_ingest_opportunity": "paid_work", "paid_work_opportunities": "paid_work",
    "paid_work_profile_variant": "paid_work", "paid_work_portfolio_add": "paid_work",
    "paid_work_portfolio_list": "paid_work",
    "paid_work_prepare_application": "paid_work", "paid_work_record_submission": "paid_work",
    "paid_work_client_review": "paid_work",
    "paid_work_client_message": "paid_work",
    "paid_work_set_pricing": "paid_work", "paid_work_negotiate": "paid_work",
    "paid_work_contract": "paid_work", "paid_work_project": "paid_work",
    "paid_work_record_delivery": "paid_work",
    "paid_work_payment": "paid_work", "paid_work_owner_decision": "paid_work",
    "paid_work_social_event": "paid_work", "paid_work_dry_run": "paid_work",
    "paid_work_focus": "paid_work",
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
    "website_project": "build", "build_add_files": "build", "build_status": "build",
    "cancel_build": "build", "build_environment": "build",
    # Phase 2 specialists and external tool bus stay out of the default
    # provider payload. Their entry points load only for relevant turns.
    "coding_inspect": "coding", "coding_execute": "coding",
    "mcp_status": "mcp", "mcp_discover": "mcp", "mcp_read": "mcp", "mcp_action": "mcp",
    "device_status": "devices", "device_observe": "devices", "device_execute": "devices",
    "phone_device_status": "devices", "phone_action": "devices",
    # Sent to the model EVERY turn unless listed here. The project already
    # measured this: ~5.4s per turn at 93 tools versus ~1.5s at 5. These four
    # are setup and recovery -- reached by name when needed, never mid-
    # conversation -- so they cost latency on every sentence for nothing.
    # siwes_evidence, system_status, set_serious_mode and send_message stay
    # CORE deliberately: a visitor asks for those, and a round spent
    # discovering the tool is a round the visitor watches.
    "prepare_presentation_evidence": "presentation",
    "presentation_recover": "presentation",
    "assistant_mode_status": "presentation",
    "type_message": "comms",
    "code_proof": "presentation", "engineering_challenges": "presentation",
    "learning_portfolio": "presentation", "project_evolution": "presentation",
    "offline_presentation": "presentation", "should_divine_answer": "presentation",
    "visitor_said": "presentation", "visit_topic": "presentation",
    "owner_directive": "presentation", "visit_status": "presentation",
    "rehearse_visit": "presentation",
    "design_tool_check": "creative",
    "plan_message_request": "comms", "messaging_status": "comms",
    # agent_roster and who_is_agent are deliberately CORE. When they were
    # lazy, "who are your agents" was answered "I don't run any agents" --
    # confident, fluent and false, because the model cannot consult a tool it
    # has not been shown. Identity questions must never need a discovery
    # round. The deeper two stay lazy.
    "agent_role_call": "agents", "agent_workers": "agents",
    "phone_mic_networks": "devices", "phone_mic_qr": "devices",
    "phone_mic_set_network": "devices", "phone_mic_current_network": "devices",
    # Evidence-led money/opportunity intelligence.  It stays absent from
    # ordinary turns and performs no market polling on startup.
    "opportunity_plan": "opportunity", "opportunity_assess": "opportunity",
    "opportunity_list": "opportunity", "opportunity_get": "opportunity",
    "opportunity_delete": "opportunity",
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
    "learning_mode", "creator_project", "mastery_mode",
    "foodie_mode", "phase3_status", "system_health",
    "proactive_control",
    # Defense/presentation mode is a one-word demo command ("defense mode") and
    # must reach the model directly -- core, like open_app.
    "defense_mode",
})
GROUP_NAMES = sorted(set(TOOL_GROUPS.values()) | {"extended"})


_FAILED_RESULT_STATES = {
    "error", "failed", "failure", "blocked", "denied", "cancelled",
    "canceled", "timed_out", "timeout", "unavailable", "rejected",
}
# Distinct from generic failure so the conversation ledger can tell a cancel or
# timeout apart from a real error (Codex's conversation-coordinator thread).
_CANCELLED_RESULT_STATES = {"cancelled", "canceled"}
_TIMED_OUT_RESULT_STATES = {"timed_out", "timeout", "timed out"}
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
        if state in _CANCELLED_RESULT_STATES:
            return {"outcome": "cancelled", "verification_state": "cancelled", "state": state}
        if state in _TIMED_OUT_RESULT_STATES:
            return {"outcome": "timed_out", "verification_state": "timed_out", "state": state}
        if parsed.get("ok") is False or parsed.get("success") is False or state in _FAILED_RESULT_STATES:
            from reyes_agent import failures
            info = failures.explain(text_value)
            return {"outcome": "failed", "verification_state": "failed", "state": state,
                    "error_category": info["category"],
                    "retryable": info["retryable"], "recovery": info["recovery"]}
        if state in _WAITING_RESULT_STATES:
            return {"outcome": "waiting", "verification_state": "pending", "state": state}
        verified = parsed.get("verified") is True or str(parsed.get("verification_state", "")).casefold() == "verified"
        has_evidence = bool(parsed.get("evidence") or parsed.get("verification_evidence"))
        verified = verified or (parsed.get("ok") is True and has_evidence)

    lowered = text_value.casefold()
    if lowered.startswith(("cancelled", "canceled")):
        return {"outcome": "cancelled", "verification_state": "cancelled", "state": state}
    if lowered.startswith(("timed out", "timeout")):
        return {"outcome": "timed_out", "verification_state": "timed_out", "state": state}
    if any(lowered.startswith(prefix) for prefix in (
        "error", "failed", "failure", "blocked", "denied", "refused",
        "unavailable", "timed out", "timeout", "browser error", "couldn't",
        "could not", "no element matches", "nothing matches", "vision match failed",
        "telegram did not confirm",
    )):
        from reyes_agent import failures
        info = failures.explain(text_value)
        return {"outcome": "failed", "verification_state": "failed", "state": state,
                "error_category": info["category"],
                "retryable": info["retryable"], "recovery": info["recovery"]}
    if any(lowered.startswith(prefix) for prefix in (
        "queued", "pending", "waiting", "accepted for", "approval required",
        "clarification needed",
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
        from reyes_agent.workspace import current_correlation, get_workspace_service

        safe_input = _tool_audit_input(tool, tool_input)
        outcome = classify_tool_result(error)
        intelligence.update_situation(current_task=tool.name, current_step="failed")
        event_bus.publish("tool.failed", payload={
            "tool": tool.name,
            "input": safe_input,
            "result": _audit_safe(error),
            "duration_ms": int(max(0.0, duration) * 1000),
            "outcome": "failed",
            "verification_state": "failed",
            "error_category": outcome.get("error_category", ""),
            "retryable": bool(outcome.get("retryable")),
        }, source="tools", correlation_id=current_correlation())
        get_workspace_service().observe_tool_execution(
            tool.name, tool_input, outcome, int(max(0.0, duration) * 1000))
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
        with span("tool.execute", attributes={"tool": tool.name, "input": _tool_audit_input(tool, tool_input)}):
            result = tool.func(**tool_input)
        duration = time.time() - started
        try:
            from reyes_agent.performance_monitor import record_latency

            record_latency("tool", duration)
            if tool.name.startswith("browser_"):
                record_latency("browser", duration)
        except Exception:  # noqa: BLE001
            pass
        safe_input = _tool_audit_input(tool, tool_input)
        safe_result = _tool_audit_result(tool, result)
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

        try:
            from reyes_agent.workspace import current_correlation

            correlation_id = current_correlation()
        except Exception:  # noqa: BLE001 -- correlation cannot alter execution
            correlation_id = ""

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
            correlation_id=correlation_id,
        )
        try:
            from reyes_agent.workspace import get_workspace_service

            get_workspace_service().observe_tool_execution(
                tool.name, tool_input, outcome, int(duration * 1000))
        except Exception:  # noqa: BLE001 -- workspace telemetry cannot alter a tool result
            pass
        return result
    except TypeError as exc:
        duration = time.time() - started
        message = f"Error: bad input for '{tool.name}': {exc}"
        audit.log("tool_error", actor="zeno", action=tool.name,
                  policy="permission_engine", outcome="failed",
                  duration_ms=int(duration * 1000), input=_tool_audit_input(tool, tool_input),
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
                  duration_ms=int(duration * 1000), input=_tool_audit_input(tool, tool_input),
                  error=_audit_safe(str(exc)))
        _publish_tool_failure(tool, tool_input,
                              f"Error running '{tool.name}': {exc}", duration)
        try:
            from reyes_agent import intelligence

            intelligence.update_situation(current_task=tool.name, current_step="failed")
        except Exception:  # noqa: BLE001
            pass
        return f"Error running '{tool.name}': {exc}"


def _canonical_tool_input(name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    """Repair a tiny set of safe provider argument aliases.

    Providers are expected to follow the published JSON schema, but an actual
    ZENO Anywhere incident showed four consecutive ``open_app`` calls using
    ``name``, ``app_name``, ``app`` and ``target`` instead of the registered
    ``name_or_path`` field.  Each call therefore returned without launching
    anything.  Accept exactly one string alias and no additional fields; all
    other malformed input still reaches the normal fail-closed executor.
    """
    if name != "open_app" or "name_or_path" in tool_input or len(tool_input) != 1:
        return tool_input
    alias = next(iter(tool_input), "")
    value = tool_input.get(alias)
    if alias in {"name", "app_name", "app", "target"} and isinstance(value, str):
        return {"name_or_path": value}
    return tool_input


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
    tool_input = _canonical_tool_input(name, tool_input)

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

    # Voice identity is request-scoped and server-signed. Private retrieval
    # remains a separate gate from action authorization.
    try:
        from reyes_agent import speaker_identity

        denial = speaker_identity.privacy_denial(name)
        if denial:
            return denial
    except Exception:  # noqa: BLE001 -- identity diagnostics cannot break tools
        pass

    # Confidence remains evidence for diagnostics and clarification. Unknown
    # confidence by itself is no longer a second approval engine: the current
    # authenticated owner command and contextual action policy decide whether
    # this exact call is authorized.
    from reyes_agent.confidence import decide_tool

    confidence = decide_tool(name, requires_confirmation=tool.requires_confirmation)
    from reyes_agent.action_policy import (
        PolicyEffect,
        current_action_context,
        evaluate as evaluate_action,
    )

    capability = permissions.capability_for_tool(name) or ""
    decision = evaluate_action(
        name,
        tool_input,
        requires_confirmation=tool.requires_confirmation,
        permission_state=permission_state,
        capability=capability,
    )

    try:
        from reyes_agent import audit

        audit.log(
            "action_policy_decision",
            actor="zeno",
            action=name,
            policy="smart_autonomy",
            outcome=decision.effect.value.casefold(),
            level=int(decision.level),
            reason=decision.reason,
            fingerprint=decision.fingerprint,
            source=current_action_context().source,
            input=_tool_audit_input(tool, tool_input),
            confidence=confidence.reason,
        )
    except Exception:  # noqa: BLE001 -- audit cannot change the decision
        pass

    if decision.effect is PolicyEffect.DENY:
        return f"Blocked: {decision.reason}. Nothing ran."
    if decision.effect is PolicyEffect.CLARIFY:
        return f"Clarification needed: {decision.reason}. Nothing ran."

    if decision.effect in {
        PolicyEffect.COUNCIL_APPROVAL,
        PolicyEffect.HIGH_IMPACT_CONFIRMATION,
    }:
        from reyes_agent import confirmation

        # Existing paired-phone step-up may satisfy a legacy routine
        # confirmation, but it never bypasses Council or the remote denylist.
        if (
            decision.effect is PolicyEffect.HIGH_IMPACT_CONFIRMATION
            and confirmation.auto_approve_active()
            and confirmation.remote_auto_run_allowed(name)
        ):
            try:
                from reyes_agent import audit

                audit.log(
                    "remote_owner_auto_approved",
                    tool=name,
                    input=_tool_audit_input(tool, tool_input),
                    reason=confirmation.auto_approve_active(),
                    fingerprint=decision.fingerprint,
                )
            except Exception:  # noqa: BLE001
                pass
            return execute_tool(tool, tool_input)

        action = confirmation.request(
            tool_name=name,
            tool_input=tool_input,
            description=(
                f"{decision.effect.value}: {name} — {decision.reason} "
                f"(confidence evidence: {confidence.reason})"
            ),
        )
        label = (
            "Council approval"
            if decision.effect is PolicyEffect.COUNCIL_APPROVAL
            else "high-impact confirmation"
        )
        return (
            f"Queued as request #{action.id} for {label}. It has NOT run yet; "
            "approve or deny that one request in the ZENO panel."
        )

    return execute_tool(tool, tool_input)


# Import tool modules for their registration side effects.
from reyes_agent.tools import android_tools, anime_tools, animation_tools, awareness_tools, creative_market_tools, blender, browser, build, calendar, campaign_tools, career_tools, charm_tools, coding_system, social_tools, companion_tools, control_plane_tools, council_tools, design, devices, email_tools, extension_tools, humor_tools, intelligence_tools, investing, knowledge_tools, language_tools, mcp_tools, media_recognition, memory, missions, notes, obsidian, opportunity_tools, paid_work_tools, agent_identity, evidence_tools, mode_tools, messaging_tools, security_tools, visit_tools, ocr_tools, phase3_tools, phase5_tools, phone_network, profile_tools, projects, rag, skills, subagents, system, t21_tools, universal_tools, utility, vision, website, work, workflow_tools  # noqa: E402,F401

# heartbeat.py lives at the top level (reyes_agent/heartbeat.py), not
# inside tools/, but registers tools the same way -- imported here so
# schedule_check/list_scheduled_checks/cancel_scheduled_check are
# available regardless of which front door starts first. Its own import
# of agent.py is deferred (see heartbeat.py) to avoid a cycle with this line.
from reyes_agent import heartbeat  # noqa: E402,F401

# Same top-level-module-that-registers-tools pattern as heartbeat.
from reyes_agent import activity_monitor  # noqa: E402,F401


_PLUGIN_LOAD_LOCK = threading.Lock()
_PLUGINS_LOADED = False
_LOADED_PLUGINS: list[str] = []


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


def ensure_plugins_loaded() -> list[str]:
    """Load approved plugins once, only after a plugin-capable request.

    Importing the global tool registry is on every startup and provider
    path.  Scanning manifests and launching plugin sandboxes there made a
    supposedly lazy service an import-time side effect.  The admin/extended
    tool entry points call this function explicitly instead.
    """
    global _PLUGINS_LOADED, _LOADED_PLUGINS
    if _PLUGINS_LOADED:
        return list(_LOADED_PLUGINS)
    with _PLUGIN_LOAD_LOCK:
        if not _PLUGINS_LOADED:
            _LOADED_PLUGINS = load_plugins()
            _PLUGINS_LOADED = True
    return list(_LOADED_PLUGINS)
