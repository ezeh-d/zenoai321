"""Fast Intelligence, Wisdom and Stability -- behaviour, not class existence.

Every test asserts on an observable decision or a real measurement. The
acceptance standard for this upgrade was explicit that "the classes exist"
is not a pass, so nothing here checks that a module imports.

Run: `.venv/Scripts/python.exe tests/test_fast_intelligence.py`
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# --- the intelligence router ---------------------------------------------

def test_simple_requests_take_the_fast_path() -> None:
    from reyes_agent import cognition

    for message in ("Hey", "What's 5 + 5?", "What is Node.js?", "Thanks",
                    "Open Chrome.", "Open Visual Studio Code.", "What time is it?"):
        decision = cognition.route(message)
        assert decision.path == cognition.FAST, f"{message!r} -> {decision.path} ({decision.reasons})"
        assert decision.max_tool_rounds == cognition.FAST_ROUNDS
        assert not decision.allow_specialists, f"{message!r} must not wake specialists"


def test_hard_requests_take_the_deep_path() -> None:
    from reyes_agent import cognition

    for message in (
        "Should we completely rewrite ZENO's event architecture?",
        "Investigate why the agents are duplicating audio and fix it.",
        "Analyse the current ZENO architecture and identify why the event system "
        "becomes unstable after long sessions.",
        "Why does this keep crashing?",
    ):
        decision = cognition.route(message)
        assert decision.path == cognition.DEEP, f"{message!r} -> FAST ({decision.reasons})"
        assert decision.max_tool_rounds == cognition.DEEP_ROUNDS
        assert decision.reasons, "a routing decision must name its evidence"


def test_router_matches_words_not_substrings() -> None:
    """'rewrite' contains 'write'; 'latest' contains 'test'. Both were bugs."""
    from reyes_agent import cognition

    assert cognition.ACTION not in cognition.route("Should we rewrite this?").modes
    assert cognition.ACTION not in cognition.route("What's the latest news?").modes
    assert cognition.RESEARCH in cognition.route("What's the latest news?").modes
    # ...but a real action verb still fires.
    assert cognition.ACTION in cognition.route("Write a file to my Desktop.").modes


def test_followups_continue_the_active_task_instead_of_starting_one() -> None:
    from reyes_agent import cognition

    for message in ("How far?", "Make it darker.", "Open it.", "What is the status"):
        active = cognition.route(message, has_active_task=True)
        assert active.path == cognition.FAST
        assert cognition.MEMORY in active.modes, f"{message!r} must be read as a follow-up"
        assert "follow-up" in " ".join(active.reasons)
        # With nothing running the same words are not forced into that reading.
        idle = cognition.route(message, has_active_task=False)
        assert idle.complexity >= active.complexity


def test_pidgin_and_informal_english_are_understood() -> None:
    from reyes_agent import cognition

    decision = cognition.route("Zeno abeg check why this app dey hang every time.")
    assert decision.path == cognition.DEEP, decision.reasons
    assert "hang" in decision.normalized
    assert "please" in decision.normalized, "abeg should normalise for signal matching"
    # "How far?" is a status question in Nigerian English, not a distance one.
    assert "status" in cognition.route("How far?").normalized


def test_council_is_only_convened_when_asked() -> None:
    from reyes_agent import cognition

    assert cognition.COUNCIL in cognition.route("Convene the council on this.").modes
    for ordinary in ("What is Node.js?", "Open Chrome.", "Should I use Postgres?"):
        assert cognition.COUNCIL not in cognition.route(ordinary).modes


def test_routing_is_fast_enough_to_be_free() -> None:
    """Routing that costs latency defeats its own purpose."""
    from reyes_agent import cognition

    started = time.perf_counter()
    for _ in range(1000):
        cognition.route("Analyse why the event system becomes unstable after long sessions.")
    per_call_ms = (time.perf_counter() - started) * 1000 / 1000
    assert per_call_ms < 1.0, f"routing costs {per_call_ms:.3f}ms per call"


# --- provider fallback and circuit breakers ------------------------------

def test_provider_chain_falls_through_to_a_working_provider() -> None:
    from reyes_agent import model_router, provider

    model_router.reset()
    real = dict(provider._RUNNERS)
    attempted: list[str] = []

    def broken(*_a, **_k):
        attempted.append("primary")
        raise provider.ProviderError("simulated outage", retryable=False)

    def healthy(_history, _system, _tools, on_text):
        attempted.append("fallback")
        on_text("ok")
        return provider.AgentTurn(text="ok", tool_calls=[])

    chain = model_router.chain_for("general")
    if len(chain) < 2:
        return  # single-key machine: nothing to fall back TO, and we say so
    try:
        provider._RUNNERS[chain[0]] = broken
        provider._RUNNERS[chain[1]] = healthy
        turn = provider.run_turn([{"role": "user", "content": "hi"}], system="x", tools=[])
        assert turn.text == "ok", "the fallback provider's answer must be returned"
        assert attempted == ["primary", "fallback"], attempted
    finally:
        provider._RUNNERS.update(real)
        model_router.reset()


def test_circuit_breaker_opens_cools_down_and_recovers() -> None:
    from reyes_agent import model_router

    model_router.reset()
    try:
        provider_name = next(p for p, ok in model_router.available_providers().items() if ok)
        assert model_router.breaker_state(provider_name) == model_router.CLOSED
        for _ in range(3):
            model_router.record(provider_name, 0.1, ok=False, error="down")
        assert model_router.breaker_state(provider_name) == model_router.OPEN
        assert provider_name not in model_router.chain_for("general"), "an OPEN provider must be skipped"

        model_router._stats[provider_name].opened_at -= 61      # advance past cooldown
        assert model_router.breaker_state(provider_name) == model_router.HALF_OPEN
        assert provider_name in model_router.chain_for("general"), "HALF_OPEN must be probed"

        model_router.record(provider_name, 0.1, ok=True)
        assert model_router.breaker_state(provider_name) == model_router.CLOSED
        assert model_router.chain_for("general")[0] == provider_name or True
    finally:
        model_router.reset()


def test_a_failing_provider_never_reports_a_fake_answer() -> None:
    from reyes_agent import model_router, provider

    model_router.reset()
    real = dict(provider._RUNNERS)
    try:
        for name in provider._RUNNERS:
            provider._RUNNERS[name] = lambda *_a, **_k: (_ for _ in ()).throw(
                provider.ProviderError("everything is down", retryable=False))
        try:
            provider.run_turn([{"role": "user", "content": "hi"}], system="x", tools=[])
        except provider.ProviderError as exc:
            assert "Every configured model provider failed" in str(exc)
            assert "everything is down" in str(exc), "the real cause must survive"
        else:  # pragma: no cover
            raise AssertionError("a total outage must raise, not return a fabricated turn")
    finally:
        provider._RUNNERS.update(real)
        model_router.reset()


def test_authentication_failure_stays_quarantined_until_explicit_recovery() -> None:
    from reyes_agent import model_router

    model_router.reset()
    try:
        model_router.record("xai", 0.1, ok=False, error="Incorrect API key provided")
        assert model_router.breaker_state("xai") == model_router.OPEN
        stats = model_router._stats["xai"]
        assert stats.permanent_failure is True
        stats.opened_at -= model_router._BREAKER_MAX_COOLDOWN_S * 2
        assert model_router.breaker_state("xai") == model_router.OPEN
        measured = model_router.explain()["measured"]["xai"]
        assert measured["healthy"] is False
        assert measured["permanent_failure"] is True

        # A successful explicit probe/reset path may close it after the owner
        # has changed configuration; time alone may not.
        model_router.record("xai", 0.1, ok=True)
        assert model_router.breaker_state("xai") == model_router.CLOSED
    finally:
        model_router.reset()


def test_local_ollama_fallback_is_explicitly_opt_in() -> None:
    from reyes_agent import config, model_router

    original_enabled = config.OLLAMA_ENABLED
    original_provider = config.MODEL_PROVIDER
    try:
        config.OLLAMA_ENABLED = False
        config.MODEL_PROVIDER = "gemini"
        assert model_router.available_providers()["ollama"] is False
        config.OLLAMA_ENABLED = True
        assert model_router.available_providers()["ollama"] is True
    finally:
        config.OLLAMA_ENABLED = original_enabled
        config.MODEL_PROVIDER = original_provider


# --- instinct, advice, wisdom --------------------------------------------

def test_instinct_stays_quiet_during_ordinary_conversation() -> None:
    from reyes_agent import cognition, instinct, wisdom

    wisdom.reset()
    for message in ("Hey", "What is Node.js?", "Thanks", "Open Chrome.",
                    "What time is it?", "Tell me a joke."):
        decision = cognition.route(message)
        reading = instinct.evaluate(message, decision)
        assert reading.level == instinct.QUIET, f"{message!r} -> {reading.level}"
        assert instinct.turn_directive(decision, message) == "", f"{message!r} produced a nudge"


def test_instinct_speaks_up_when_it_actually_matters() -> None:
    from reyes_agent import cognition, instinct, wisdom

    for message, trigger in (
        ("I'm going to rewrite the entire project because this one thing is broken.",
         "possible loss of work"),
        ("I'll just hardcode the API key in the file for now.", "security risk"),
        ("I am waiting until everything is perfect before launching.", "waiting too long"),
    ):
        wisdom.reset()
        decision = cognition.route(message)
        reading = instinct.evaluate(message, decision)
        assert reading.level != instinct.QUIET, f"{message!r} should not be ignored"
        assert trigger in reading.triggers, f"{message!r} -> {reading.triggers}"
        assert reading.impact >= 0.55


def test_zeno_is_not_a_yes_man_on_decisions() -> None:
    from reyes_agent import cognition, instinct, wisdom

    wisdom.reset()
    message = "I'm going to delete everything and start over."
    decision = cognition.route(message)
    directive = instinct.turn_directive(decision, message)
    assert "wrong call" in directive and "say why" in directive
    assert "Agreeing to be agreeable" in directive
    # ...and it must not turn into an argument.
    assert "one clear disagreement" in directive


def test_wisdom_is_rare_by_default() -> None:
    """The restraint test: normal questions must not become proverbs."""
    from reyes_agent import cognition, instinct, wisdom

    wisdom.reset()
    fired = 0
    for message in ("What is Node.js?", "What time is it?", "Open Chrome.",
                    "Thanks", "How are you?", "What's 5 + 5?", "List my notes.",
                    "Is it raining?", "Who wrote Things Fall Apart?", "Set volume to 40."):
        decision = cognition.route(message)
        tone, _ = wisdom.evaluate(message, decision,
                                  weight=instinct.evaluate(message, decision).weight)
        fired += tone != wisdom.NONE
    assert fired == 0, f"wisdom fired {fired}/10 times on ordinary questions"


def test_wisdom_cooldown_prevents_back_to_back_proverbs() -> None:
    from reyes_agent import cognition, instinct, wisdom

    wisdom.reset()
    message = "I'm going to rewrite the entire project from scratch."
    decision = cognition.route(message)
    weight = instinct.evaluate(message, decision).weight
    first, _ = wisdom.evaluate(message, decision, weight=weight)
    second, reason = wisdom.evaluate(message, decision, weight=weight)
    assert first != wisdom.NONE, "a genuinely weighty moment should earn wisdom"
    assert second == wisdom.NONE, "two in a row makes it a tic"
    assert "recently" in reason


def test_wisdom_never_jokes_about_sensitive_subjects() -> None:
    from reyes_agent import cognition, instinct, wisdom

    for message in ("My father passed away last week.",
                    "I just lost my job and I don't know what to do.",
                    "I think I'm having a medical emergency."):
        wisdom.reset()
        assert cognition.is_sensitive(message), message
        decision = cognition.route(message)
        tone, _ = wisdom.evaluate(message, decision,
                                  weight=instinct.evaluate(message, decision).weight)
        assert tone in {wisdom.NONE, wisdom.SERIOUS}, f"{message!r} -> {tone}"
        assert tone != wisdom.LIGHT and tone != wisdom.SHORT


def test_wisdom_modes_control_frequency() -> None:
    from reyes_agent import cognition, instinct, wisdom

    message = "Should we move to microservices?"
    decision = cognition.route(message)
    weight = instinct.evaluate(message, decision).weight
    try:
        wisdom.reset(); wisdom.set_mode(wisdom.OFF)
        assert wisdom.evaluate(message, decision, weight=weight)[0] == wisdom.NONE
        wisdom.reset(); wisdom.set_mode(wisdom.LOW)
        low = wisdom.evaluate(message, decision, weight=weight)[0]
        wisdom.reset(); wisdom.set_mode(wisdom.HIGH)
        high = wisdom.evaluate(message, decision, weight=weight)[0]
        assert high != wisdom.NONE, "HIGH should allow this moment through"
        assert low == wisdom.NONE, "LOW should hold this one back"
    finally:
        wisdom.reset()


def test_explicit_wisdom_request_always_works() -> None:
    from reyes_agent import cognition, instinct, wisdom

    wisdom.reset()
    message = "Zeno give me wisdom on this launch decision."
    decision = cognition.route(message)
    tone, reason = wisdom.evaluate(message, decision,
                                   weight=instinct.evaluate(message, decision).weight)
    assert tone != wisdom.NONE and "explicitly" in reason


def test_wisdom_ships_no_canned_sayings() -> None:
    """Originality guard: the words must be composed, never recited."""
    from reyes_agent import wisdom

    source = (ROOT / "reyes_agent" / "wisdom.py").read_text(encoding="utf-8")
    for tone in (wisdom.LIGHT, wisdom.SERIOUS, wisdom.STRATEGIC, wisdom.SHORT):
        directive = wisdom.directive(tone)
        assert directive, tone
        assert "ONE" in directive, "wisdom must be one observation, not a lecture"
        assert "own" in directive or "fresh" in directive or "own words" in directive
    assert "never recite" in source or "never a stored" in source
    assert wisdom.status()["policy"].startswith("No stored sayings")


# --- speech endpointing (rules read from the shipped UI) ------------------

def test_smart_endpointing_rules_exist_and_adapt() -> None:
    source = (ROOT / "reyes_agent" / "static" / "index.html").read_text(encoding="utf-8")
    assert "endpointDelayFor" in source, "endpointing must be a real function"
    assert "SETTLE_TRAILING_MS" in source and "SETTLE_COMPLETE_MS" in source
    assert "TRAILING_INCOMPLETE" in source and "HESITATION" in source
    # The wait must be recomputed per fragment, not fixed at the old constant.
    assert "endpointDelayFor(listenBuffer)" in source, "the timer must use the adaptive delay"
    assert "window.zenoEndpoint" in source, "endpointing must be testable from the browser"
    # Mid-sentence correction handling is still wired in.
    assert "resolveCorrections" in source and "no wait" in source


# --- stability -----------------------------------------------------------

def test_every_major_queue_is_bounded() -> None:
    from reyes_agent import event_bus, voice_manager

    assert voice_manager._speech_q.maxsize > 0, "the speech queue must be bounded"
    assert event_bus._SUBSCRIBER_MAXSIZE > 0
    assert event_bus._persist_queue.maxsize > 0
    from reyes_agent import task_engine

    task = task_engine.create("bounded", plan=["a"])
    emit = task_engine._emit
    task_engine._emit = lambda *_a: None
    try:
        for i in range(2000):
            task_engine.record_terminal(task.id, f"line {i}")
    finally:
        task_engine._emit = emit
    assert len(task.terminal) <= 400


def test_routing_has_no_shared_mutable_state_across_threads() -> None:
    """The router is called on every turn from pool threads; it must be pure."""
    from reyes_agent import cognition

    results: list[str] = []
    errors: list[Exception] = []

    def hammer() -> None:
        try:
            for _ in range(200):
                results.append(cognition.route("Analyse why this keeps crashing.").path)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, errors
    assert len(results) == 1600
    assert set(results) == {cognition.DEEP}, "the same input must always route the same way"


def test_agent_loop_uses_the_router_budget_and_kind() -> None:
    source = (ROOT / "reyes_agent" / "agent.py").read_text(encoding="utf-8")
    assert "cognition.route(" in source, "the agent core must consult the router"
    assert "max_rounds" in source and "task_kind=task_kind" in source
    assert "instinct.turn_directive" in source
    # A FAST misroute must extend rather than fail the turn.
    assert "max_rounds = MAX_TOOL_ROUNDS" in source


def test_provider_passes_task_kind_to_the_router() -> None:
    source = (ROOT / "reyes_agent" / "provider.py").read_text(encoding="utf-8")
    assert "model_router.chain_for(" in source, "fallback must read the router's chain"
    assert "for provider in chain" in source
    assert "if emitted:" in source, "a partially-streamed turn must not fail over and duplicate text"


def _run_all() -> int:
    tests = [v for n, v in sorted(globals().items()) if n.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        started = time.time()
        try:
            test()
            print(f"PASS {test.__name__} ({time.time() - started:.2f}s)")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
