"""The shared agent core -- one turn in, tools resolved, final reply out.

A typed turn, a spoken turn (Tier 3), and a heartbeat-initiated turn
(Tier 5) all call `run_agent()`. This is the "one shared brain" the whole
harness is organized around; nothing about voice or proactivity should ever
need its own copy of this loop.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from reyes_agent import config
from reyes_agent.provider import ProviderError, run_turn
from reyes_agent.tools import TOOLS, run_tool, tool_definitions
from reyes_agent.tools.memory import system_prompt_block

# A tool round is one "model asks for a tool -> we run it -> feed result
# back" cycle. Capped so a confused model can't loop forever burning calls.
MAX_TOOL_ROUNDS = 8

# Third argument is the tool_call id -- lets a caller (the SSE stream, the
# activity ticker) correlate a specific call with its own result even when
# several are in flight at once (see the parallel-delegate branch below).
OnText = Callable[[str], None]
OnToolCall = Callable[[str, dict, str], None]
OnToolResult = Callable[[str, str, str], None]
OnStage = Callable[[str], None]


def run_agent(
    history: list[dict],
    on_text: OnText | None = None,
    on_tool_call: OnToolCall | None = None,
    on_tool_result: OnToolResult | None = None,
    on_stage: OnStage | None = None,
    cancel_check: Callable[[], None] | None = None,
    turn_id: str = "",
    spoken: bool = False,
) -> None:
    """Run the agent to completion for the latest turn already in `history`.

    Mutates `history` in place, appending assistant tool-call turns, tool
    results, and the final reply as they happen. Raises ProviderError on
    failure; the caller decides whether to keep or roll back the partial
    turn (see cli.py -- it reverts to a pre-turn snapshot).

    This loop IS the Task Execution Engine's pipeline (Intent Analysis ->
    Planning -> Agent Selection -> Parallel Execution -> Verification ->
    Unified Response) -- one model call already does intent analysis and
    planning together in a single reasoning pass (that's how these models
    work; splitting it into separate round-trip calls would only add
    latency for no quality gain, and this build has already fought hard to
    keep latency down -- see AGENT.md). `on_stage` names each checkpoint of
    that same pipeline as it happens, rather than adding new ones:
    "planning" each time the model reasons about what to do next,
    "delegating"/"acting" when it selects agents or tools, "verifying" when
    results are fed back for the model to react to, "responding" once it
    settles on a final answer.

    `turn_id` ties this turn to the conversation state machine
    (conversation_state.py) and its latency timeline (latency.py). Both are
    best-effort observers: if either is unavailable the turn runs exactly as
    before. Passing "" means the caller is not tracking this turn, which is
    normal for CLI and background/heartbeat turns.
    """
    # Ollama on this CPU-only machine can't do tool-calling well at any
    # size: 10 tools cost ~88s of constrained-decoding overhead just to
    # decide whether to call one, 3 tools still produced hallucinated,
    # malformed tool-call JSON as plain text (measured 2026-07-22). Zero
    # tools -> ~22s and a clean reply. So Ollama gets NO tools -- pure
    # conversation only -- until a cloud key (Claude/xAI) is added, at
    # which point the full registry is available immediately with no code
    # change. This is a real capability gap on local mode, not a
    # cosmetic one: "search my notes" / "open an app" / anything tool-shaped
    # won't work under Ollama. See reyes_agent/tools/__init__.py.
    # Core tools only to start. Measured 2026-08-04: all 93 schemas cost
    # ~5.4s/turn vs ~1.5s with a handful -- tool COUNT dominates latency on
    # cloud providers too, not just Ollama. ZENO widens this mid-turn by
    # calling `enable_tools`, handled below.
    enabled_groups: set[str] = set()

    # CAPABILITY ROUTING. Core alone is 105 schemas, and the measurement above
    # is exactly why that hurts: "what time is it" was taking ~10s, most of it
    # the model reading a catalogue it would never use. The router picks the
    # handful this request could plausibly need, deterministically and in
    # microseconds -- no extra model call, because trading one latency source
    # for another is not a fix.
    #
    # It NARROWS, it never blocks: `enable_tools` still widens mid-turn, so a
    # misroute costs one round rather than a capability.
    # The latest user turn, needed HERE by capability routing and again
    # below by the cognition router. It used to be defined only below, and
    # the routing block referenced an unbound `message` -- so every turn
    # raised NameError, `except Exception` swallowed it, and the router
    # never actually ran. One definition, used by both.
    latest = next((m.get("content", "") for m in reversed(history)
                   if m.get("role") == "user" and isinstance(m.get("content"), str)), "")

    # UNIVERSAL LANGUAGE INTELLIGENCE. Everything downstream -- capability
    # routing, cognition, the intent parser, every agent -- reasons from
    # English, so the conversion happens once, here, rather than each of them
    # learning to read Pidgin.
    #
    # Confident English leaves the engine in ~3ms having done only a Unicode
    # scan, so the fast path this file fought for is untouched. `latest` is
    # replaced only when the engine actually changed something AND is
    # confident; a low-confidence guess is left alone rather than rewriting
    # the owner's words into something they did not say.
    _language = None
    if latest:
        try:
            from reyes_agent import language as _language_engine

            _language = _language_engine.understand_text(latest)
            if (not _language.fast_path and _language.english
                    and _language.english != latest
                    and _language.confidence >= 0.5):
                history[-1] = dict(history[-1])
                history[-1]["content"] = _language.english
                history[-1]["original_text"] = latest
                history[-1]["source_language"] = _language.language
                latest = _language.english
        except Exception:  # noqa: BLE001 -- language must never break a turn
            _language = None

    _route = None
    tools = [] if config.MODEL_PROVIDER == "ollama" else tool_definitions(groups=enabled_groups)
    if tools and latest:
        try:
            from reyes_agent.routing import capability as _capability

            _route = _capability.tools_for(latest)
            _allowed = set(_route.tools)
            _narrowed = [t for t in tools if t["name"] in _allowed]
            # Never hand back an empty toolset on a turn that had some: an
            # empty list is a different request shape to some providers.
            if _narrowed:
                tools = _narrowed
        except Exception:  # noqa: BLE001 -- routing must never break a turn
            _route = None

    # --- Intelligence Router ------------------------------------------------
    # One local, sub-millisecond decision about how hard this turn should
    # think (reyes_agent/cognition.py). It sets the tool-round budget and the
    # provider preference; it never answers and never blocks. A FAST turn is
    # not a dumber turn -- it is the same brain with a shorter leash, which is
    # what keeps "hey" from costing eight tool rounds.
    decision = None
    try:
        from reyes_agent import cognition, task_engine

        if latest:
            decision = cognition.route(latest, has_active_task=task_engine.latest_open() is not None)
    except Exception:  # noqa: BLE001 -- routing is an optimisation, never a gate
        decision = None

    max_rounds = decision.max_tool_rounds if decision else MAX_TOOL_ROUNDS
    task_kind = decision.model_kind if decision else "general"

    # A pure conversation cannot call a tool.  Sending schemas anyway was
    # the largest measured contributor to first-token latency, and by
    # 2026-08-11 the accidental "core" payload had reached 94 tools.  The
    # cognition decision is local and deterministic; action/memory/research
    # turns retain the compact core and can widen it on demand.
    fast_chat = bool(decision is not None and decision.path == "FAST" and decision.modes == ("CHAT",))
    if fast_chat or not latest:
        tools = []

    # Load the compact advanced group only for a request that can use it.
    # This is a local keyword gate, not another model call, and avoids the
    # historical all-tools payload regression on ordinary conversation.
    try:
        from reyes_agent.phase3 import relevant_request
        if relevant_request(latest):
            enabled_groups.add("phase3")
            if config.MODEL_PROVIDER != "ollama":
                tools = tool_definitions(groups=enabled_groups)
    except Exception:
        pass

    # Phase 5 schemas stay out of ordinary turns. This keyword gate is local
    # and sub-millisecond; it starts no service and adds only the relevant
    # read-only tools when the owner's request can use them.
    normalized_latest = latest.casefold()
    if any(marker in normalized_latest for marker in (
        "analyse this csv", "analyze this csv", "analyse this data", "analyze this data",
        "parquet", "dataset", "monthly totals", "data quality", "duckdb",
    )):
        enabled_groups.add("analytics")
    if any(marker in normalized_latest for marker in (
        "phase 5 status", "tailscale", "private network", "push notification",
        "agent vault", "sandbox status",
        "what did i miss", "notifications",
    )):
        enabled_groups.add("phase5")
    if enabled_groups & {"analytics", "phase5"} and config.MODEL_PROVIDER != "ollama":
        tools = tool_definitions(groups=enabled_groups)

    # Opportunity research is a dormant local engine.  Expose its compact
    # tool group only for an actual income/market request; it performs no
    # automatic web calls and never joins the startup path.
    if any(marker in normalized_latest for marker in (
        "make money", "online income", "income opportunity", "business opportunity",
        "freelance", "micro-saas", "micro saas", "product idea", "find clients",
        "market demand", "competitor research", "pricing research", "profitable niche",
    )):
        enabled_groups.add("opportunity")
        if config.MODEL_PROVIDER != "ollama":
            tools = tool_definitions(groups=enabled_groups)

    # Skills stay lazy. An explicit skill/routine request or a real trigger
    # match exposes only the small durable-skill control group. The match is
    # context for the existing planner, never an automatic execution bypass.
    matched_skill_context = ""
    try:
        from reyes_agent.skills import manager as skill_manager

        skill_words = ("skill", "routine", "reusable workflow", "learn my workflow",
                       "learned workflow", "automation recipe")
        matched_skill = skill_manager.find_for(latest) if latest else None
        if matched_skill or any(word in latest.casefold() for word in skill_words):
            enabled_groups.add("skills")
            if matched_skill:
                # The system prompt is assembled after memory retrieval below.
                # Appending here used to raise UnboundLocalError and the broad
                # best-effort exception silently discarded approved skill
                # context on precisely the turns that needed it.
                matched_skill_context = (
                    "\n\nA real owner-approved persisted skill matches this request: "
                    f"{matched_skill.name} ({matched_skill.skill_id}). Use skill_run "
                    "if the user's request is to execute it; never imitate its result."
                )
            if config.MODEL_PROVIDER != "ollama":
                tools = tool_definitions(groups=enabled_groups)
    except Exception:
        pass

    # --- observers ---------------------------------------------------------
    # Both are strictly best-effort: a broken diagnostic must never cost the
    # user a reply, so every call goes through these two helpers.
    def _mark(name: str) -> None:
        if not turn_id:
            return
        try:
            from reyes_agent import latency

            latency.mark(turn_id, name)
        except Exception:  # noqa: BLE001
            pass

    def _state(name: str, detail: str = "") -> None:
        if not turn_id:
            return
        try:
            from reyes_agent import conversation_state

            conversation_state.enter(name, source="agent", turn_id=turn_id, detail=detail)
        except Exception:  # noqa: BLE001
            pass

    _mark("intent_ready")
    thinking_state = "DEEP_THINKING" if decision and decision.path == "DEEP" else "THINKING"

    # One trace observes this existing loop; it is not a second scheduler or
    # planner. Failures in telemetry/memory never cost the user a reply.
    trace = None
    try:
        from reyes_agent.execution_lifecycle import ExecutionTrace, Stage

        trace = ExecutionTrace(latest, correlation_id=turn_id)
        trace.enter(Stage.RETRIEVE_MEMORY)
    except Exception:  # noqa: BLE001
        trace = None

    # Relevant memory only. The previous implementation injected every
    # durable fact into every turn, causing prompt growth and irrelevant
    # context. Living Memory remains the fallback and authority.
    try:
        from reyes_agent.memory import get_memory_manager

        memory_context = get_memory_manager().context_for(latest)
    except Exception:  # noqa: BLE001
        memory_context = system_prompt_block()
    system = ((config.FAST_CHAT_SYSTEM_PROMPT if fast_chat else config.SYSTEM_PROMPT)
              + memory_context + matched_skill_context)

    # WHO ZENO IS travels with every turn, including the fast path.
    #
    # Measured: asked "who are your agents", ZENO answered "I don't run any
    # agents. It's just me here." -- confidently, fluently and falsely. Short
    # questions take the fast path, which states that no tool is available, so
    # the model answered from imagination and imagined itself alone.
    #
    # Registering a tool cannot fix that, because the fast path has no tools
    # to consult. Identity is not a lookup, it is something ZENO should simply
    # KNOW, so it is carried as knowledge: one line, read from the same
    # canonical registry, cheap enough to send every turn.
    try:
        from reyes_agent.agents import identity

        team = identity.roster()
        if team:
            names = ", ".join(a["name"] for a in team)
            system += (
                f"\n\nYOUR TEAM (fact, not a guess): you have {len(team)} "
                f"registered specialist agents -- {names} -- with "
                f"{sum(a['worker_count'] for a in team)} workers between them. "
                "You are the master; they are specialists you delegate to. "
                "Never say you work alone or have no agents.")
    except Exception:  # noqa: BLE001
        pass
    try:
        from reyes_agent.agent_presence import get_agent_presence
        from reyes_agent.agent_runtime import AGENT_ROLES

        presence = get_agent_presence().snapshot()
        active = [str(row.get("agent", "")) for row in presence.get("active_agents", [])
                  if row.get("active") and row.get("agent") in AGENT_ROLES]
        addressed = str(presence.get("last_addressed") or "")
        if active:
            labels = ", ".join(f"{name.upper()} ({AGENT_ROLES[name]})" for name in active)
            system += (
                "\n\nCURRENT CONVERSATION PARTICIPANTS: " + labels + ". "
                "They were explicitly summoned by the owner; this does not mean they are already doing work. "
                + (f"The most recently addressed specialist is {addressed.upper()}. " if addressed in active else "")
                + "If the owner's follow-up is clearly within that specialist's role, delegate it there; "
                  "do not force unrelated requests onto a summoned agent.")
    except Exception:  # noqa: BLE001 -- visual presence must never block a turn
        pass
    if spoken:
        # Speech is slower than reading. A three-sentence answer takes about
        # twelve seconds to say, and the owner stands there for all of it --
        # so shaving latency off the START of a reply is wasted if the reply
        # itself runs long.
        system += config.VOICE_REPLY_STYLE
    try:
        from reyes_agent.user_profiles import owner_context
        system += owner_context()
    except Exception:  # noqa: BLE001 -- onboarding context is optional
        pass

    # Episodic context is queried only when explicitly enabled and the user is
    # asking about prior computer activity. It runs in this managed agent turn,
    # never on the GUI thread, and contributes only bounded privacy-filtered
    # matches instead of continuously feeding screen history to a model.
    try:
        from reyes_agent.phase3 import episodic_request
        if episodic_request(latest):
            from reyes_agent.context.episodic import get_provider
            episode = get_provider().query(latest, limit=8)
            if episode.get("ok") and episode.get("items"):
                compact = [f"- {item.get('application', '')}: {item.get('title', '')} — {item.get('text', '')[:300]}"
                           for item in episode["items"][:8]]
                system += "\n\nRelevant private episodic context (use only for this request):\n" + "\n".join(compact)
    except Exception:
        pass
    if decision is not None:
        from reyes_agent import cognition, creator_mode, design_intelligence, foodie_intelligence, humour, instinct, learning_mode, website_builder

        # Two short per-turn directives, both bounded: how hard to think, and
        # whether there is something genuinely worth pointing out. Kept tight
        # on purpose -- prompt length is latency on every single turn.
        system += "\n\n" + cognition.prompt_directive(decision)
        try:
            from reyes_agent import agents
            from reyes_agent.agents import router as agent_router

            delegation = agents.decide(latest, decision)
            delegation_nudge = agent_router.directive(delegation)
            if delegation_nudge:
                system += "\n" + delegation_nudge
        except Exception:  # noqa: BLE001 -- Phase 1 adapter remains optional
            pass
        nudge = instinct.turn_directive(decision, latest)
        if nudge:
            system += "\n" + nudge
        # Humour is a local policy nudge, never another model call or a
        # response generator.  It therefore keeps an explicit joke or
        # playful exchange on the already-selected FAST turn.
        humour_nudge = humour.directive(latest, decision)
        if humour_nudge:
            system += "\n" + humour_nudge
        design_nudge = design_intelligence.directive(latest)
        if design_nudge:
            system += "\n" + design_nudge
        learning_nudge = learning_mode.directive(latest)
        if learning_nudge:
            system += "\n" + learning_nudge
        creator_nudge = creator_mode.directive(latest)
        if creator_nudge:
            system += "\n" + creator_nudge
        foodie_nudge = foodie_intelligence.directive(latest)
        if foodie_nudge:
            system += "\n" + foodie_nudge
        website_nudge = website_builder.directive(latest)
        if website_nudge:
            system += "\n" + website_nudge

    # Claude's bounded situational/anticipation layer reuses sensors ZENO
    # already owns. Both calls are cached and best-effort: context can make a
    # reply more useful, but must never become a new dependency for replying.
    try:
        from reyes_agent import anticipation, awareness

        # Fast chat may omit tool schemas and use the compact system prompt,
        # but it must not become context-blind.  These directives are bounded,
        # cached local projections (no provider call or sensor loop).
        awareness_nudge = awareness.directive()
        if awareness_nudge:
            system += "\n" + awareness_nudge
        anticipation_nudge = anticipation.directive()
        if anticipation_nudge:
            system += "\n" + anticipation_nudge
    except Exception:  # noqa: BLE001 -- optional context must never block a turn
        pass

    # A FAST turn that genuinely needs more room is a routing miss, not a
    # user-visible failure: the budget extends once to the full DEEP limit
    # rather than reporting "stuck in a loop". Misrouting costs a little
    # speed, never correctness -- see cognition.py.
    round_index = 0
    while round_index < max_rounds:
        round_index += 1
        if round_index == max_rounds and max_rounds < MAX_TOOL_ROUNDS:
            max_rounds = MAX_TOOL_ROUNDS
        if cancel_check:
            cancel_check()
        if on_stage:
            on_stage("planning")
        if trace is not None:
            try:
                from reyes_agent.execution_lifecycle import Stage
                trace.enter(Stage.PLAN, round=round_index)
            except Exception:
                pass
        # First round is the model thinking about the request; later rounds
        # are it reacting to tool results, which is planning, not fresh
        # thought. Naming them differently is what makes the state readable.
        _state(thinking_state if round_index == 1 else "PLANNING")
        _mark("context_ready")
        _mark("model_requested")

        # first_model_token has to be observed at the STREAM, not after the
        # call returns -- "time to first token" measured at the end is just
        # total latency wearing a different name.
        def _timed_on_text(chunk: str) -> None:
            _mark("first_model_token")
            if on_text:
                on_text(chunk)

        try:
            turn = run_turn(
                history, system=system, tools=tools, on_text=_timed_on_text,
                cancel_check=cancel_check, task_kind=task_kind,
            )
        except Exception as exc:
            if trace is not None:
                try:
                    trace.fail(f"{type(exc).__name__}: {exc}")
                except Exception:
                    pass
            raise

        if not turn.wants_tool:
            if on_stage:
                on_stage("responding")
            if turn.text.strip():
                _mark("first_sentence_ready")
            history.append({"role": "assistant", "content": turn.text})
            if trace is not None:
                try:
                    verification = trace.verification()
                    from reyes_agent.memory import get_memory_manager

                    decisions = get_memory_manager().consider_turn(
                        latest, turn.text, verified=bool(verification.get("verified") and trace.evidence))
                    trace.finish(stored=any(item.durable for item in decisions))
                except Exception:
                    try:
                        trace.finish(stored=False)
                    except Exception:
                        pass
            # Bounded, process-local recent-joke history only.  A failure in
            # this optional personality aid must never prevent a reply.
            try:
                from reyes_agent import humour

                humour.record_reply(latest, turn.text)
            except Exception:  # noqa: BLE001
                pass
            return

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

        # Agent Selection + Parallel Execution: when ZENO fans a request out
        # to two or more specialists in the same round, run those delegate()
        # calls concurrently instead of one after another -- a real
        # wall-clock win, and safe to do because each delegate() call is
        # already self-contained (its own bounded sub-agent loop; no shared
        # mutable state beyond SQLite, and every module already opens its
        # own short-lived connection per call -- see tools/__init__.py).
        # Everything else keeps running exactly as before: single delegate
        # calls and non-delegate tools stay sequential, so this only changes
        # behavior in the one case it's actually meant for.
        delegate_calls = [tc for tc in turn.tool_calls if tc.name == "delegate"]
        other_calls = turn.tool_calls if len(delegate_calls) < 2 else [
            tc for tc in turn.tool_calls if tc.name != "delegate"
        ]
        if len(delegate_calls) < 2:
            delegate_calls = []

        results: dict[str, object] = {}

        if delegate_calls:
            if on_stage:
                on_stage("delegating")
            _state("EXECUTING", "delegating to specialists")
            for tc in delegate_calls:
                if cancel_check:
                    cancel_check()
                if on_tool_call:
                    on_tool_call(tc.name, tc.input, tc.id)
                if trace is not None:
                    tool = TOOLS.get(tc.name)
                    results[f"__autonomy__{tc.id}"] = trace.selected_tool(
                        tc.name, requires_confirmation=bool(tool and tool.requires_confirmation))
                    try:
                        from reyes_agent.execution_lifecycle import Stage
                        trace.enter(Stage.EXECUTE, tool=tc.name, agent=True)
                    except Exception:
                        pass
            # Reuse the bounded runtime rather than making a fresh executor
            # (and fresh OS threads) for every delegated turn. The enclosing
            # chat worker occupies one slot; the pool deliberately retains
            # capacity for the bounded delegate fan-out.
            from reyes_agent.worker_pool import PRIORITY_AGENT, get_worker_pool

            pool = get_worker_pool()
            pending = {
                pool.submit(
                    run_tool, tc.name, tc.input,
                    name=f"delegate:{tc.name}", priority=PRIORITY_AGENT,
                    timeout=120,
                ): tc
                for tc in delegate_calls
            }
            while pending:
                if cancel_check:
                    cancel_check()
                completed = [handle for handle in pending if handle.done]
                if not completed:
                    time.sleep(0.02)
                    continue
                for handle in completed:
                    tc = pending.pop(handle)
                    result = handle.result()
                    results[tc.id] = result
                    if trace is not None:
                        trace.observed(tc.name, result, results.get(f"__autonomy__{tc.id}", {}))  # type: ignore[arg-type]
                    if on_tool_result:
                        on_tool_result(tc.name, result, tc.id)

        if other_calls:
            if on_stage:
                on_stage("acting")
            _state("EXECUTING", "running tools")
            for tc in other_calls:
                if cancel_check:
                    cancel_check()
                if on_tool_call:
                    on_tool_call(tc.name, tc.input, tc.id)
                autonomy = {}
                if trace is not None:
                    tool = TOOLS.get(tc.name)
                    autonomy = trace.selected_tool(
                        tc.name, requires_confirmation=bool(tool and tool.requires_confirmation))
                    try:
                        from reyes_agent.execution_lifecycle import Stage
                        trace.enter(Stage.EXECUTE, tool=tc.name)
                    except Exception:
                        pass
                result = run_tool(tc.name, tc.input)
                # Widen the toolset for the remainder of this turn. Done
                # here rather than inside the tool because the tool list is
                # rebuilt per round by this loop.
                widen = ""
                if tc.name == "enable_tools":
                    widen = str(tc.input.get("group", "")).strip().lower()
                elif tc.name == "build_project":
                    # A build that has just started will want build_add_files
                    # (large projects), build_status and cancel_build. Loading
                    # the group here rather than making the model ask for it
                    # keeps those within the MAX_TOOL_ROUNDS budget -- running
                    # out of rounds mid-build is precisely what used to leave
                    # ZENO explaining the rest instead of doing it.
                    widen = "build"
                if widen:
                    enabled_groups.add(widen)
                    if config.MODEL_PROVIDER != "ollama":
                        tools = tool_definitions(groups=enabled_groups)
                if on_tool_result:
                    on_tool_result(tc.name, result, tc.id)
                results[tc.id] = result
                if trace is not None:
                    trace.observed(tc.name, result, autonomy)

        if on_stage:
            on_stage("verifying")
        for tc in turn.tool_calls:
            history.append(
                {
                    "role": "tool_result",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": results[tc.id],
                }
            )

    if trace is not None:
        trace.fail(f"tool round limit reached ({max_rounds})")
    raise ProviderError(
        f"Stopped after {max_rounds} tool calls in a row without a final answer "
        "-- it may be stuck in a loop."
    )
