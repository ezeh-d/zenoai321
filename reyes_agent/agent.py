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

    # Recalled facts are plain prompt text, not a tool schema -- costs
    # nothing extra on Ollama's constrained decoding, so every provider
    # gets "remembers me" even though only cloud providers can currently
    # write new facts (remember/forget are gated behind tools like everything else).
    system = config.SYSTEM_PROMPT + system_prompt_block()

    for _ in range(MAX_TOOL_ROUNDS):
        if cancel_check:
            cancel_check()
        if on_stage:
            on_stage("planning")
        turn = run_turn(
            history, system=system, tools=tools, on_text=on_text,
            cancel_check=cancel_check,
        )

        if not turn.wants_tool:
            if on_stage:
                on_stage("responding")
            history.append({"role": "assistant", "content": turn.text})
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
            for tc in other_calls:
                if cancel_check:
                    cancel_check()
                if on_tool_call:
                    on_tool_call(tc.name, tc.input, tc.id)
                result = run_tool(tc.name, tc.input)
                # Widen the toolset for the remainder of this turn. Done
                # here rather than inside the tool because the tool list is
                # rebuilt per round by this loop.
                if tc.name == "enable_tools":
                    group = str(tc.input.get("group", "")).strip().lower()
                    if group:
                        enabled_groups.add(group)
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
        f"Stopped after {MAX_TOOL_ROUNDS} tool calls in a row without a final answer "
        "-- it may be stuck in a loop."
    )
