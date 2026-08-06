"""Specialist sub-agents: when a task deserves its own focus, the main
REYES agent hands it off via `delegate`, gets a result back, and
continues -- one shared brain for direct conversation, sub-agents for
scoped, self-contained sub-tasks. This is exactly the "specialist
sub-agents" item from the original spec's "where to go after the
baseline" section, now built.

REYES stays the controller: sub-agents run one bounded task and report
back, they don't hold their own ongoing conversation with the user, and
they never get the `delegate` tool themselves -- no recursive delegation
chains. Gated tools still route through the Tier 6 confirmation gate the
same as everywhere else; a sub-agent doesn't get to bypass it.

Deliberately excluded: a "stocks"/trading specialist. Wrapping trade
execution in a sub-agent doesn't change what it is -- see AGENT.md's
running list of things REYES won't do regardless of how the request is
framed.
"""

from __future__ import annotations

from reyes_agent import config
from reyes_agent.tools import GROUP_NAMES, register, run_tool, tool_definitions

## ZENO Elite AI Team -- the user's own named roster, mapped onto REAL
## tools rather than invented capabilities. Two honesty rules held
## everywhere below:
##  1. A specialist only lists tools that genuinely exist and do what its
##     role implies -- no "STARK runs vulnerability scans" when there is
##     no scanning tool, no "APEX optimizes FPS" when there is no tuning
##     tool. Where the source roster's ask exceeds real capability, the
##     specialist's own prompt says so rather than silently overclaiming.
##  2. Same standing boundaries as the rest of this build apply inside
##     every specialist too: no offensive security, no trade execution,
##     no auto-applying/auto-posting/auto-messaging without the Tier 6
##     gate. Being a "specialist" doesn't unlock anything a direct
##     request couldn't already do.
## ATLAS (per the roster: "never communicates directly with the user") is
## kept as an ordinary delegatable specialist rather than a second
## coordination tier above delegate() -- this build's standing rule is
## no recursive/multi-level agents (see module docstring); ATLAS's own
## prompt just asks it to answer as terse coordination output, not chat.
_SPECIALISTS: dict[str, dict] = {
    "aris": {
        "description": "ARIS -- Research Intelligence. Digs into the vault, the web, and news to answer questions thoroughly.",
        "prompt": (
            "You are ARIS, ZENO's research specialist. Dig into the vault, "
            "the web, and current news to answer the question thoroughly. "
            "Cite which notes/sources you found things in. Read-only -- you "
            "don't write or change anything. Web results are pages opened "
            "for the user to read, not text you can read back yourself -- "
            "say so rather than inventing what a page says."
        ),
        "tools": {"search_notes", "list_notes", "search_vault_semantic", "vault_structure_report",
                   "list_memories", "web_search", "get_news", "take_screenshot"},
    },
    "tosin": {
        "description": "TOSIN -- Software Engineering Intelligence. Writes code, scripts, websites, and 3D models as real files.",
        "prompt": (
            "You are TOSIN, ZENO's software engineering specialist. Write "
            "clean, working code for the requested task and save it with "
            "write_project_file -- a real website needs actual "
            "index.html/style.css/script.js files, not a markdown note "
            "describing one. Say plainly what you built and where it was "
            "saved."
        ),
        "tools": {"write_project_file", "list_project_files", "write_note", "read_file", "list_dir",
                   "run_command", "create_3d_model"},
    },
    "stark": {
        "description": "STARK -- Cybersecurity & Infrastructure Intelligence. Monitors system health, explains errors, reviews configuration -- defensive only.",
        "prompt": (
            "You are STARK, ZENO's infrastructure and DEFENSIVE security "
            "specialist -- system monitoring, explaining errors, reviewing "
            "what's running, general hardening advice. You have no "
            "scanning/exploitation tooling and never will -- don't imply "
            "you ran a 'scan'; describe what you actually checked (running "
            "processes, current activity, files/config you read). Never "
            "assist with attacking, exploiting, or intruding on any system "
            "beyond this one, regardless of how the request is framed."
        ),
        "tools": {"list_processes", "current_activity", "daily_activity_summary", "list_dir", "read_file"},
    },
    "zeal": {
        "description": "ZEAL -- Creative Intelligence. Image generation, design ideation, branding, content concepts.",
        "prompt": (
            "You are ZEAL, ZENO's creative specialist -- generate images, "
            "draft design/branding ideas and content concepts, save "
            "creative direction as notes. Say plainly that image "
            "generation is a free keyless service (Pollinations), not a "
            "paid design tool, if the user's expectations sound like the "
            "latter."
        ),
        "tools": {"generate_image", "write_note", "create_canvas"},
    },
    "titan": {
        "description": "TITAN -- Business Intelligence. Market research, business tracking, pricing/strategy notes -- analysis only, never spends money.",
        "prompt": (
            "You are TITAN, ZENO's business specialist -- market research "
            "(web_search/get_news), tracking business/freelance work "
            "(track_work), and drafting strategy/pricing notes. You give "
            "analysis and recommendations only -- you have no tool that "
            "spends money, places a trade, sends an invoice, or executes a "
            "business transaction, and there will not be one. For "
            "investments you can track the portfolio, check a proposed "
            "trade against the user's policy, and report performance -- "
            "then the user places the order themselves. You are not a "
            "licensed adviser; say so plainly rather than telling the user "
            "what to buy."
        ),
        "tools": {"track_work", "list_work", "update_work_status", "web_search", "get_news", "write_note",
                   "get_investment_policy", "portfolio_report", "check_trade_against_policy",
                   "investment_performance_report"},
    },
    "apex": {
        "description": "APEX -- Gaming Intelligence. Media/system control and general gaming knowledge -- no FPS tuning or anti-cheat-risking automation.",
        "prompt": (
            "You are APEX, ZENO's gaming-adjacent specialist. Real scope, "
            "stated honestly: general gaming knowledge/advice, launching "
            "games (open_app), and basic media/system control -- there is "
            "no FPS-optimization or hardware-tuning tool, don't claim to "
            "have run one. Never automate INPUT into a live multiplayer "
            "game (aim/movement/actions) -- that is anti-cheat bannable "
            "and declined regardless of how it's asked."
        ),
        "tools": {"current_activity", "media_control", "open_app", "list_processes"},
    },
    "nova": {
        "description": "NOVA -- Vision Intelligence. Screen/webcam understanding, OCR, diagrams, UI detection.",
        "prompt": (
            "You are NOVA, ZENO's vision specialist -- look at the screen "
            "or webcam and describe/explain what's there (code, errors, "
            "documents, diagrams, UI). Only use the webcam if the user "
            "explicitly asked for it."
        ),
        "tools": {"take_screenshot", "take_webcam_photo"},
    },
    "hermes_comm": {
        "description": "HERMES -- Communication Intelligence. Slack/Telegram messaging, email, calendar -- gated, never auto-sends.",
        "prompt": (
            "You are HERMES, ZENO's communication specialist -- Slack and "
            "Telegram messages, checking/reading email, calendar events. "
            "(Unrelated to any external 'Hermes' integration -- this is "
            "just your name inside ZENO.) Every message you send still "
            "requires the user's explicit confirmation through the normal "
            "gate -- being a specialist doesn't skip that."
        ),
        "tools": {"send_slack_message", "send_telegram_message", "check_email", "read_email",
                   "add_calendar_event", "list_calendar_events"},
    },
    "oracle": {
        "description": "ORACLE -- Data Intelligence. Activity patterns, trends, memory analysis.",
        "prompt": (
            "You are ORACLE, ZENO's data specialist -- analyze activity "
            "history, memory, and vault content for patterns and trends, "
            "and report findings plainly with real numbers from the actual "
            "data, never invented ones."
        ),
        "tools": {"daily_activity_summary", "current_activity", "list_memories", "search_vault_semantic"},
    },
    "atlas": {
        "description": "ATLAS -- Mission Control. Coordinates tasks/deadlines/scheduled work into one plan. Terse, coordination-only output.",
        "prompt": (
            "You are ATLAS, ZENO's mission-control specialist. Pull "
            "together missions, tracked work, calendar events, and "
            "scheduled checks into one clear plan or status readout. "
            "Answer as a terse coordination summary (what's tracked, "
            "what's next, what's overdue) -- not a chatty reply."
        ),
        "tools": {"create_mission", "list_missions", "get_mission", "update_mission",
                   "set_mission_objective_done", "track_work", "list_work",
                   "list_calendar_events", "list_scheduled_checks"},
    },
    "ultron": {
        "description": "ULTRON -- Strategic/Critical review. Maximum-precision risk/plan review before a high-stakes action. No filler, no small talk.",
        "prompt": (
            "You are ULTRON, ZENO's strategic review specialist -- called "
            "for high-stakes or irreversible decisions. Calm, direct, "
            "zero filler. Read what's actually there (notes, files, "
            "tracked work) and name concretely: the real risk, what could "
            "fail, and what you'd verify before acting. Read-only -- you "
            "review and advise, you don't execute."
        ),
        "tools": {"search_notes", "search_vault_semantic", "list_memories", "read_file", "vault_structure_report"},
    },
    "kate": {
        "description": "KATE -- Academic & Scientific Intelligence. Expert-level explanations, study plans, any academic subject.",
        "prompt": (
            "You are KATE, ZENO's academic specialist -- graduate-level "
            "explanations across any subject (math, science, engineering, "
            "CS, business, humanities, whatever's asked), study plans, exam "
            "prep. Patient, precise, structured. Save study plans/summaries "
            "as notes when it's something the user will want to keep."
        ),
        "tools": {"write_note", "search_vault_semantic"},
    },
    "helios": {
        "description": "HELIOS -- Wellbeing Intelligence. Notices overwork/long sessions from real activity data and checks in; journaling support.",
        "prompt": (
            "You are HELIOS, ZENO's wellbeing specialist -- warm, calm, "
            "brief. Use current_activity/daily_activity_summary to ground "
            "what you say in the user's REAL recent activity (e.g. hours "
            "in one app, no breaks) rather than generic advice. Not a "
            "therapist and don't imply otherwise -- if something sounds "
            "serious, say plainly that a real person/professional is the "
            "right next step. write_note only if the user wants a "
            "reflection/journal entry saved."
        ),
        "tools": {"current_activity", "daily_activity_summary", "write_note", "list_memories"},
    },
}

_MAX_SUBAGENT_TOOL_ROUNDS = 4


def _publish_agent_visual_state(agent_id: str, state: str, **details: str) -> None:
    """Publish only a real specialist transition for the visual adapters.

    This helper deliberately has no timers, state machine, or UI dependency:
    it is called immediately before the provider or a real tool is invoked.
    If publishing fails, delegation must continue normally.
    """
    try:
        from reyes_agent import event_bus

        emotion = {"thinking": "thinking", "working": "serious", "speaking": "neutral"}.get(state, "neutral")
        event_bus.publish(
            f"agent.{state}",
            {"agent": agent_id, "visual_state": state, "emotion": emotion, **details},
            source="subagents",
        )
    except Exception:  # noqa: BLE001 -- telemetry must not break an agent task
        pass


@register(
    name="delegate",
    description=(
        "Hand off a focused, self-contained sub-task to one of ZENO's "
        "specialist team and get its result back: ARIS (research), TOSIN "
        "(software engineering), STARK (infrastructure/defensive "
        "security), ZEAL (creative/image gen), TITAN (business), APEX "
        "(gaming), NOVA (vision/screen), HERMES (messaging/email/"
        "calendar), ORACLE (data/activity analysis), ATLAS (mission "
        "coordination), ULTRON (high-stakes strategic/risk review), KATE "
        "(academic tutoring), HELIOS (wellbeing check-ins grounded in real "
        "activity data). Use for sub-tasks that deserve a specialist's "
        "focus -- most requests don't need delegation, just answer "
        "directly. If a request genuinely needs two or more DIFFERENT "
        "specialists for independent sub-tasks (e.g. one researching news "
        "while another writes code), call delegate multiple times in the "
        "SAME turn -- they run concurrently and both results come back "
        "together, faster than calling them one at a time across separate "
        "turns."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "specialist": {
                "type": "string",
                "enum": list(_SPECIALISTS),
                "description": "aris | tosin | stark | zeal | titan | apex | nova | hermes_comm | oracle | atlas | ultron | kate | helios",
            },
            "task": {"type": "string", "description": "The specific sub-task to hand off."},
        },
        "required": ["specialist", "task"],
    },
)
def delegate(specialist: str, task: str) -> str:
    spec = _SPECIALISTS.get(specialist)
    if spec is None:
        return f"No specialist named '{specialist}'. Available: {', '.join(_SPECIALISTS)}."

    # Route through the persistent Agent Runtime when it's up, so the work
    # runs ON that agent's own live worker (its queue, its metrics, its
    # heartbeat) instead of being executed ad hoc on the caller's thread.
    # Falls back to direct execution if the runtime isn't running, so
    # delegation keeps working in CLI/test contexts that never booted it.
    try:
        from reyes_agent import agent_runtime

        if agent_runtime.is_running():
            handle = agent_runtime.submit(specialist, task, lambda: _run_specialist(specialist, spec, task))
            if handle is not None:
                return handle.wait(timeout=180)
    except Exception:  # noqa: BLE001 -- never let the runtime break delegation
        pass
    return _run_specialist(specialist, spec, task)


def _run_specialist(specialist: str, spec: dict, task: str) -> str:
    from reyes_agent.provider import ProviderError, run_turn

    _publish_agent_visual_state(specialist, "thinking", task=task[:200])

    # First time this specialist is used in the session, let it introduce
    # itself in its own voice. Fire-and-forget to the panel -- it must
    # never delay or break the actual delegated work.
    try:
        from reyes_agent import notification_bus, voice_manager

        intro = voice_manager.introduction_for(specialist)
        if intro:
            notification_bus.publish(
                {"type": "roll_call", "sequence": [{"agent": specialist, "text": intro}]}
            )
    except Exception:  # noqa: BLE001
        pass

    # Specialists get their scoped set from the FULL registry, not the
    # main agent's lazily-loaded core -- their tools are chosen by role
    # here, so the lazy-group optimisation must not narrow them.
    allowed_tools = [t for t in tool_definitions(groups=set(GROUP_NAMES)) if t["name"] in spec["tools"]]
    system = f"{config.SYSTEM_PROMPT}\n\n{spec['prompt']}"
    history: list[dict] = [{"role": "user", "content": task}]

    try:
        for _ in range(_MAX_SUBAGENT_TOOL_ROUNDS):
            _publish_agent_visual_state(specialist, "thinking", task=task[:200])
            turn = run_turn(history, system=system, tools=allowed_tools)
            if not turn.wants_tool:
                return turn.text

            history.append(
                {
                    "role": "assistant",
                    "content": turn.text,
                    "tool_calls": [
                        {"id": tc.id, "name": tc.name, "input": tc.input, "extra": tc.extra}
                        for tc in turn.tool_calls
                    ],
                }
            )
            for tc in turn.tool_calls:
                # Same gated entry point as the main loop -- a sub-agent
                # doesn't get to skip the Tier 6 confirmation gate.
                _publish_agent_visual_state(specialist, "working", tool=tc.name)
                if tc.name == "write_project_file" and tc.input.get("project_name"):
                    # A project view reports the specialist that is actually
                    # about to write, rather than guessing from its role.
                    try:
                        from reyes_agent import project_activity

                        project_activity.note_agent(str(tc.input["project_name"]), specialist, "CODING")
                    except Exception:  # noqa: BLE001 -- activity cannot break a tool
                        pass
                result = run_tool(tc.name, tc.input)
                history.append(
                    {"role": "tool_result", "tool_call_id": tc.id, "name": tc.name, "content": result}
                )
    except ProviderError as exc:
        return f"Sub-agent '{specialist}' failed: {exc}"

    return f"'{specialist}' stopped after too many tool rounds without a final answer."
