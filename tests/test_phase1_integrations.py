"""Phase 1: vision, computer control, browser, agents, voice session.

The standard here is behaviour, not presence. Most of these assert that a
subsystem REFUSES correctly — an agentic loop that cannot be stopped, or a
click at an invented coordinate, is the failure mode that matters.

Run: `.venv/Scripts/python.exe tests/test_phase1_integrations.py`
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _scene(*elements):
    from reyes_agent.vision.elements import Element, Scene

    scene = Scene(window="Test Window")
    for kind, label, rect, interactive in elements:
        scene.elements.append(Element(type=kind, label=label, position=rect,
                                      interactive=interactive))
    return scene


# --- feature flags -------------------------------------------------------

def test_every_integration_is_off_by_default_and_reports_reality() -> None:
    from reyes_agent import integrations

    status = integrations.status()
    for name in ("livekit", "agent_framework", "cua", "omniparser", "browser_agent"):
        assert name in status, f"{name} must be reportable"
        assert status[name]["default_backend"], "every flag must name what runs instead"
    # A flag being on is not the same as the backend existing; both are reported.
    assert integrations.status()["omniparser"]["installed"] is integrations.available("torch")


# --- 4. vision -----------------------------------------------------------

def test_uia_returns_real_structured_elements_fast() -> None:
    """The measured claim: cached scoped UIA, not a 30s desktop walk."""
    from reyes_agent.vision import parser

    started = time.time()
    scene = parser.parse_uia()
    elapsed = time.time() - started

    assert elapsed < 8.0, f"a screen parse took {elapsed:.1f}s -- that is the slow COM path"
    if scene.error:
        return                     # headless/locked session: nothing to assert against
    assert scene.elements, "a real window should expose elements"
    for element in scene.elements:
        assert element.type and element.position
        left, top, width, height = element.position
        assert width > 0 and height > 0, "zero-size elements are not clickable and must be dropped"
        assert element.source == "uia" and element.confidence == 1.0


def test_grounding_refuses_rather_than_guessing_coordinates() -> None:
    """The core safety property of a computer-use agent."""
    from reyes_agent.vision import grounding

    scene = _scene(("button", "Send", (10, 10, 60, 30), True),
                   ("button", "Cancel", (80, 10, 60, 30), True),
                   ("text", "Message body", (10, 50, 200, 20), False))

    found = grounding.find(scene, "Send")
    assert found is not None and found.label == "Send"
    assert found.center == (40, 25), "the click point must come from the real rectangle"

    # Nothing remotely matching -> None, never a fallback guess.
    assert grounding.find(scene, "Publish to production") is None
    assert grounding.find(scene, "") is None


def test_ambiguous_targets_are_detected_not_picked() -> None:
    from reyes_agent.vision import grounding

    scene = _scene(("button", "Save", (10, 10, 60, 30), True),
                   ("button", "Save As", (80, 10, 60, 30), True))
    assert grounding.ambiguous(scene, "Save"), "two close matches must be flagged, not chosen"
    ranked = grounding.candidates(scene, "Save", limit=2)
    assert len(ranked) == 2 and ranked[0][0] > 0


def test_the_scene_cache_expires_and_can_be_invalidated() -> None:
    from reyes_agent.vision import scene_state

    scene_state.reset()
    scene_state.current()
    first = scene_state.stats()
    scene_state.current()
    assert scene_state.stats()["hits"] > first["hits"], "a second read must reuse the cache"
    scene_state.invalidate()
    assert scene_state.stats()["cached"] is False, "invalidate must drop the scene"
    assert scene_state.TTL_S <= 5.0, "a stale scene sends clicks to where a button used to be"


def test_omniparser_reports_why_it_cannot_run_instead_of_an_empty_screen() -> None:
    from reyes_agent.vision import parser

    scene = parser.parse_omniparser()
    assert scene.error, "an unavailable backend must say so, not return an empty scene"
    assert "torch" in scene.error.lower() or "not wired" in scene.error.lower()


# --- 3. computer control -------------------------------------------------

def test_payments_and_security_are_refused_even_with_approval() -> None:
    from reyes_agent.computer import safety

    for target in ("Confirm payment", "Place order", "Buy now", "Checkout",
                   "Change my password", "Disable the firewall", "Factory reset"):
        allowed, risk = safety.gate("click", target, approved=True)
        assert not allowed, f"{target!r} ran with approval -- it must never be automated"
        assert risk.tier == safety.REFUSED


def test_destructive_actions_need_approval_but_can_be_approved() -> None:
    from reyes_agent.computer import safety

    for target in ("Delete account", "Uninstall", "Sign out", "Publish", "Submit"):
        blocked, risk = safety.gate("click", target)
        assert not blocked and risk.tier == safety.APPROVAL, target
        allowed, _ = safety.gate("click", target, approved=True)
        assert allowed, f"{target!r} should proceed once explicitly approved"


def test_ordinary_and_read_only_actions_are_not_obstructed() -> None:
    from reyes_agent.computer import safety

    for action, target in (("click", "Save"), ("type", "hello"), ("click", "Next"),
                           ("observe", ""), ("screenshot", "")):
        allowed, risk = safety.gate(action, target)
        assert allowed, f"{action}({target!r}) was blocked -- safety must not break normal use"
        assert risk.tier in {safety.SAFE, safety.ORDINARY}


def test_the_fast_path_handles_known_commands_without_perception() -> None:
    from reyes_agent.computer import controller, deterministic

    for request in ("Open Chrome", "open visual studio code", "set volume to 40",
                    "take a screenshot", "lock the screen"):
        assert controller.classify(request) == controller.FAST, request
        matched = deterministic.match(request)
        assert matched and matched[0], request

    # Anything needing eyes escalates rather than being faked.
    assert controller.classify("find the settings menu and turn on dark mode") == controller.AGENTIC
    assert deterministic.match("find the settings menu") is None


def test_fast_path_does_not_turn_a_gated_non_execution_into_success() -> None:
    from reyes_agent.computer import controller, deterministic

    original = deterministic.run
    deterministic.run = lambda _request: deterministic.FastResult(
        handled=True, ok=False, tool="open_app", result="Queued: action has NOT run yet")
    try:
        result = controller.run("Open Chrome")
    finally:
        deterministic.run = original
    assert result.ok is False
    assert result.detail["executed"] is False


def test_the_agentic_loop_cannot_run_forever() -> None:
    from reyes_agent.computer import agentic

    assert agentic.MAX_STEPS <= 20 and agentic.DEADLINE_S <= 300
    assert agentic.MAX_NO_CHANGE <= 5, "a no-progress detector must stop a grinding loop"

    # A plan longer than the cap is truncated, not run in full.
    plan = [{"action": "observe"} for _ in range(agentic.MAX_STEPS + 20)]
    outcome = agentic.run("stress", plan, max_steps=3)
    assert len(outcome.steps) <= 3


def test_a_click_with_no_matching_element_fails_instead_of_clicking() -> None:
    from reyes_agent.computer import agentic

    step = agentic.act("click", "a control that certainly does not exist anywhere")
    assert step.ok is False
    assert "not on screen" in step.detail or "ambiguous" in step.detail
    assert "nothing was clicked" in step.detail or "ambiguous" in step.detail


def test_agentic_run_stops_on_a_refused_step() -> None:
    from reyes_agent.computer import agentic

    outcome = agentic.run("pay", [{"action": "click", "target": "Confirm payment"}])
    assert outcome.ok is False and outcome.reason.startswith("refused")


def test_verification_reports_real_change_not_assumed_success() -> None:
    from reyes_agent.computer import verification

    before = _scene(("button", "Send", (0, 0, 10, 10), True))
    same = _scene(("button", "Send", (0, 0, 10, 10), True))
    after = _scene(("button", "Sent", (0, 0, 10, 10), True))

    assert verification.compare(before, same).changed is False
    assert "nothing observably changed" in verification.compare(before, same).detail
    change = verification.compare(before, after)
    assert change.changed and "Sent" in change.appeared

    ok, why = verification.expects(after, "Sent")
    assert ok and "Sent" in why
    assert verification.expects(after, "Completely absent text")[0] is False


# --- 5. browser ----------------------------------------------------------

def test_browser_strategy_is_chosen_from_the_task() -> None:
    from reyes_agent.browser import router

    assert router.choose("go to https://example.com").strategy == router.DETERMINISTIC
    assert router.choose("read the page").strategy == router.DETERMINISTIC
    assert router.choose("find the pricing page").strategy == router.AGENTIC
    # A URL plus exploration is still exploration once it lands.
    assert router.choose("go to example.com and find their pricing").strategy == router.AGENTIC


def test_bulk_submission_is_refused() -> None:
    from reyes_agent.browser import router

    for task in ("apply to all the jobs on this page",
                 "send a message to every contact",
                 "submit applications in bulk"):
        route = router.choose(task)
        assert route.refused, f"{task!r} was not refused"
        assert "bulk submission" in route.reason


def test_important_submissions_are_confirmed_first() -> None:
    from reyes_agent.browser import verification

    for task in ("submit the application form", "buy the ticket", "delete the account"):
        needs, why = verification.needs_confirmation(task)
        assert needs and why, task
    assert verification.needs_confirmation("read the article")[0] is False


def test_a_page_that_did_not_load_is_not_reported_as_success() -> None:
    from reyes_agent.browser import verification

    assert verification.check().ok is False
    blocked = verification.check(title="Verify it's you", text="unusual traffic detected " * 5)
    assert blocked.ok is False and "verification" in blocked.blocker.lower()
    consent = verification.check(title="Cookies", text="Accept all cookies " * 6)
    assert consent.ok is False
    good = verification.check(title="Python docs",
                              text="Python is a programming language " * 8, expect="python")
    assert good.ok is True


# --- 2. agents -----------------------------------------------------------

def test_the_registry_reports_real_agents_from_the_real_supervisor() -> None:
    from reyes_agent import agents

    described = agents.describe()
    assert described["executive"] == "ZENO"
    assert described["count"] >= 1, "ZENO's existing specialists must be visible here"
    assert "agent_teams" in described["backend"], "this must wrap the EXISTING orchestrator"
    for specialist in described["specialists"]:
        assert specialist["name"] and specialist["status"] in {"idle", "working", "unknown"}


def test_delegation_is_restrained() -> None:
    """Thirteen agents must not answer 'what is Node.js'."""
    from reyes_agent import agents
    from reyes_agent.agents import router

    assert agents.decide("What is Node.js?").shape == router.DIRECT
    assert agents.decide("Open Chrome").shape == router.TOOL
    assert agents.decide("Convene the council on this").shape == router.COUNCIL

    for ordinary in ("Hey", "Thanks", "What time is it?"):
        assert agents.decide(ordinary).max_agents == 0, ordinary


def test_agent_health_reads_the_supervisor_not_a_second_copy() -> None:
    from reyes_agent.agents import health

    snapshot = health.snapshot()
    assert snapshot["state"] in {health.HEALTHY, health.DEGRADED, health.FAILED, health.STOPPED}
    assert snapshot.get("source") == "agent_runtime.health()"


# --- 1. voice session ----------------------------------------------------

def test_a_session_stays_open_until_standby() -> None:
    from reyes_agent.voice import realtime_session as session

    session.reset()
    try:
        opened = session.start()
        assert opened.open and opened.turns == 0
        # A second wake must NOT create a competing session for one microphone.
        assert session.start().id == opened.id

        session.touch(turn=True)
        session.touch(turn=True)
        assert session.current().turns == 2

        for phrase in ("standby", "zeno standby", "that's all", "go to sleep"):
            assert session.is_standby(phrase), phrase
        assert not session.is_standby("stand up"), "ordinary speech must not end the session"

        ended = session.end("standby")
        assert ended is not None and not ended.open
        assert session.current() is None
    finally:
        session.reset()


def test_the_default_transport_is_local() -> None:
    from reyes_agent.voice import realtime_session as session

    status = session.status()
    assert status["backend"] == session.LOCAL, \
        "mic and brain are on one machine; a LiveKit room would add a round trip"
    assert status["livekit_enabled"] is False
    assert "phone companion" in status["note"]


def test_barge_in_goes_through_the_existing_state_machine() -> None:
    from reyes_agent import conversation_state
    from reyes_agent.voice import realtime_session as session

    conversation_state.reset()
    session.reset()
    try:
        session.start()
        turn = conversation_state.begin_turn()
        conversation_state.enter("UNDERSTANDING", source="test", turn_id=turn)
        conversation_state.enter("THINKING", source="test", turn_id=turn)
        conversation_state.enter("SPEAKING", source="test", turn_id=turn)

        result = session.barge_in()
        assert result["ok"] and result["state"] == "LISTENING"
        # The interrupted turn is closed, so cancelled audio cannot resume.
        assert conversation_state.enter("SPEAKING", source="ghost", turn_id=turn).rejected
    finally:
        conversation_state.reset()
        session.reset()


# --- isolation -----------------------------------------------------------

def test_no_subsystem_raises_into_the_caller() -> None:
    """A Phase 1 failure must degrade, never take ZENO down."""
    from reyes_agent import agents, browser, computer, vision
    from reyes_agent.voice import realtime_session as session

    for call in (vision.observe, computer.status, browser.status,
                 agents.describe, session.status, agents.health.snapshot):
        result = call()
        assert result is not None, f"{call.__name__} returned nothing"


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
