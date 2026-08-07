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
from reyes_agent.tools import run_tool, tool_definitions
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
    tools = [] if config.MODEL_PROVIDER == "ollama" else tool_definitions(groups=enabled_groups)

    # --- Intelligence Router ------------------------------------------------
    # One local, sub-millisecond decision about how hard this turn should
    # think (reyes_agent/cognition.py). It sets the tool-round budget and the
    # provider preference; it never answers and never blocks. A FAST turn is
    # not a dumber turn -- it is the same brain with a shorter leash, which is
    # what keeps "hey" from costing eight tool rounds.
    decision = None
    try:
        from reyes_agent import cognition, task_engine

        latest = next((m.get("content", "") for m in reversed(history)
                       if m.get("role") == "user" and isinstance(m.get("content"), str)), "")
        if latest:
            decision = cognition.route(latest, has_active_task=task_engine.latest_open() is not None)
    except Exception:  # noqa: BLE001 -- routing is an optimisation, never a gate
        decision = None

    max_rounds = decision.max_tool_rounds if decision else MAX_TOOL_ROUNDS
    task_kind = decision.model_kind if decision else "general"

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

    # Recalled facts are plain prompt text, not a tool schema -- costs
    # nothing extra on Ollama's constrained decoding, so every provider
    # gets "remembers me" even though only cloud providers can currently
    # write new facts (remember/forget are gated behind tools like everything else).
    system = config.SYSTEM_PROMPT + system_prompt_block()
    if decision is not None:
        from reyes_agent import cognition, creator_mode, design_intelligence, foodie_intelligence, humour, instinct, learning_mode, website_builder

        # Two short per-turn directives, both bounded: how hard to think, and
        # whether there is something genuinely worth pointing out. Kept tight
        # on purpose -- prompt length is latency on every single turn.
        system += "\n\n" + cognition.prompt_directive(decision)
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

        turn = run_turn(
            history, system=system, tools=tools, on_text=_timed_on_text,
            cancel_check=cancel_check, task_kind=task_kind,
        )

        if not turn.wants_tool:
            if on_stage:
                on_stage("responding")
            if turn.text.strip():
                _mark("first_sentence_ready")
            history.append({"role": "assistant", "content": turn.text})
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

        results: dict[str, str] = {}

        if delegate_calls:
            if on_stage:
                on_stage("delegating")
            _state("EXECUTING", "delegating to specialists")
            for tc in delegate_calls:
                if cancel_check:
                    cancel_check()
                if on_tool_call:
                    on_tool_call(tc.name, tc.input, tc.id)
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

    raise ProviderError(
        f"Stopped after {max_rounds} tool calls in a row without a final answer "
        "-- it may be stuck in a loop."
    )
