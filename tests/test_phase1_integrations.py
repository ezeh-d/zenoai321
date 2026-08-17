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
    if not scene.reliable:
        # Whatever happens to be in front during a test run is not ours to
        # choose -- it may be minimized or a suspended UWP app. An honest
        # "I could not read this, and here is why" is a correct outcome,
        # not an empty window, so there is nothing to assert about elements.
        assert scene.coverage.reason and scene.coverage.remedy
        return
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
    first_scene = scene_state.current()
    first = scene_state.stats()
    # Keep this a cache test rather than a race with whatever window receives
    # focus while the test suite is running.
    scene_state.current(handle=first_scene.window_handle)
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
    assert deterministic.match("run my tests") is None
    assert deterministic.match("run this Python script") is None


def test_agentic_deadline_uses_a_monotonic_clock() -> None:
    from reyes_agent.computer import agentic

    real_clock = agentic.time.monotonic
    real_act = agentic.act
    ticks = iter((100.0, 101.0))
    agentic.time.monotonic = lambda: next(ticks)
    agentic.act = lambda *_a, **_k: (_ for _ in ()).throw(
        AssertionError("an already-expired plan must not execute an action"))
    try:
        result = agentic._run_locked(
            "expired", [{"action": "observe"}], approved=False,
            override_idle=False, max_steps=1, deadline_s=0.5, cancel_check=None)
    finally:
        agentic.time.monotonic = real_clock
        agentic.act = real_act
    assert result.reason.startswith("stopped at the")


def test_window_focus_timeout_uses_a_monotonic_clock() -> None:
    from pathlib import Path

    source = (Path(__file__).parents[1] / "reyes_agent" / "computer" / "window.py").read_text(
        encoding="utf-8")
    activate = source.split("def activate(", 1)[1]
    assert "deadline = time.monotonic()" in activate
    assert "while time.monotonic() < deadline" in activate


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


# --- input isolation -----------------------------------------------------

def test_zeno_will_not_take_the_pointer_while_the_owner_is_using_it() -> None:
    from reyes_agent.computer import input_guard

    original = input_guard.owner_idle_seconds
    try:
        input_guard.owner_idle_seconds = lambda: 0.2      # owner just typed
        grant = input_guard.may_take_control()
        assert grant.allowed is False
        assert "working" in grant.reason or "mouse" in grant.reason

        # ...but an explicit instruction from the owner still wins.
        assert input_guard.may_take_control(override=True).allowed is True

        input_guard.owner_idle_seconds = lambda: 60.0     # owner is away
        assert input_guard.may_take_control().allowed is True
    finally:
        input_guard.owner_idle_seconds = original
        input_guard.reset()


def test_a_blocked_step_is_reported_as_waiting_not_as_failure() -> None:
    """The owner being busy is not the plan being wrong."""
    from reyes_agent.computer import agentic, input_guard

    original = input_guard.owner_idle_seconds
    try:
        input_guard.owner_idle_seconds = lambda: 0.1
        outcome = agentic.run("type something", [{"action": "type", "text": "hello"}])
        assert outcome.ok is False
        assert outcome.blocked_on_owner is True, "must be distinguishable from a failed step"
        assert outcome.steps and outcome.steps[0].blocked_on_owner is True
    finally:
        input_guard.owner_idle_seconds = original
        input_guard.reset()


def test_revoking_control_stops_further_input() -> None:
    from reyes_agent.computer import input_guard

    original = input_guard.owner_idle_seconds
    try:
        input_guard.owner_idle_seconds = lambda: 60.0
        assert input_guard.may_take_control().allowed is True
        input_guard.revoke("owner said stop")
        assert input_guard.may_take_control().allowed is False
        # An override must NOT resurrect a revoked run.
        assert input_guard.may_take_control(override=True).allowed is False
    finally:
        input_guard.owner_idle_seconds = original
        input_guard.reset()


def test_observing_is_never_blocked_by_the_owner_being_busy() -> None:
    """Looking costs the owner nothing; only input does."""
    from reyes_agent.computer import agentic, input_guard

    original = input_guard.owner_idle_seconds
    try:
        input_guard.owner_idle_seconds = lambda: 0.0
        step = agentic.act("observe")
        assert step.ok is True and step.blocked_on_owner is False
    finally:
        input_guard.owner_idle_seconds = original
        input_guard.reset()


# --- accessibility coverage ---------------------------------------------

def test_an_unreadable_window_is_not_reported_as_an_empty_one() -> None:
    """The bug this prevents: 'Calculator has no buttons'."""
    from reyes_agent.vision import coverage
    from reyes_agent.vision.elements import Scene

    for state in (coverage.MINIMIZED, coverage.SUSPENDED, coverage.OPAQUE, coverage.SLOW):
        scene = Scene(window="Calculator")
        scene.coverage = coverage.Coverage(state, "because reasons", "do this")
        assert scene.reliable is False
        summary = scene.summary()
        assert "could not properly read" in summary
        assert "do this" in summary, "a diagnosis without a remedy is not useful"
        assert "exposes no readable elements" not in summary


def test_coverage_never_calls_a_busy_window_opaque() -> None:
    """A window that published 4300 elements is slow, not featureless."""
    from reyes_agent.vision import coverage

    verdict = coverage.assess(0, 0, 0, enumerate_s=30.0, reported_total=4300)
    assert verdict.state == coverage.SLOW
    assert verdict.worth_ocr is False, "OCR cannot fix an app that is merely slow"
    assert "4300" in verdict.reason


def test_a_healthy_window_is_trusted() -> None:
    from reyes_agent.vision import coverage

    verdict = coverage.assess(0, 120, 80)
    assert verdict.trustworthy is True and verdict.state == coverage.GOOD


def test_a_missing_element_admits_when_the_read_was_bad() -> None:
    """'Not on screen' is a claim about the world; only make it when we looked."""
    from reyes_agent.computer import agentic, input_guard
    from reyes_agent.vision import coverage, scene_state

    original_idle = input_guard.owner_idle_seconds
    original_current = scene_state.current
    blind = _scene()
    blind.window = "Calculator"
    blind.coverage = coverage.Coverage(coverage.SUSPENDED, "it is suspended",
                                       "bring it to the foreground")
    try:
        input_guard.owner_idle_seconds = lambda: 60.0
        scene_state.current = lambda **_: blind
        step = agentic.act("click", "Seven")
        assert step.ok is False
        assert "may well be there" in step.detail
        assert "foreground" in step.detail
    finally:
        input_guard.owner_idle_seconds = original_idle
        scene_state.current = original_current
        input_guard.reset()


def test_zeno_can_read_what_a_text_box_contains_not_just_its_name() -> None:
    """A field's Name is its label; its Value is what the owner typed.

    Verified live against Notepad: the typed text appears ONLY in the Value
    pattern. Reading Name alone reported an empty document that was not.
    """
    from reyes_agent.vision.elements import Element

    box = Element(type="edit", label="Search", value="quarterly report")
    assert "Search" in box.describe() and "quarterly report" in box.describe()
    assert box.as_dict()["value"] == "quarterly report"


def test_focus_is_a_real_action_because_coverage_prescribes_it() -> None:
    """Diagnosing 'bring it to the foreground' is useless without a way to."""
    from reyes_agent.computer import agentic, input_guard, window

    assert hasattr(window, "activate") and hasattr(window, "find_by_title")

    original = input_guard.owner_idle_seconds
    try:
        input_guard.owner_idle_seconds = lambda: 60.0
        step = agentic.act("focus", "a window that does not exist at all")
        assert step.ok is False and "no open window matching" in step.detail

        # Yanking a window forward while the owner types is as rude as
        # taking the mouse, so it answers to the same guard.
        input_guard.owner_idle_seconds = lambda: 0.1
        busy = agentic.act("focus", "Notepad")
        assert busy.blocked_on_owner is True
    finally:
        input_guard.owner_idle_seconds = original
        input_guard.reset()


def test_throwing_away_unsaved_work_needs_approval() -> None:
    """Found by running a real GUI task, not by reading the code."""
    from reyes_agent.computer import safety

    for label in ("Don't save", "Dont save", "Close without saving", "Discard changes"):
        allowed, risk = safety.gate("click", label)
        assert allowed is False and risk.tier == safety.APPROVAL, label
    # ...without turning every ordinary button into a prompt.
    for label in ("Save", "Save as...", "OK", "Cancel"):
        allowed, _risk = safety.gate("click", label)
        assert allowed is True, label


def test_input_is_never_sent_to_a_window_we_did_not_read() -> None:
    """Coordinates grounded in window A must not be typed into window B."""
    from reyes_agent.computer import agentic, input_guard
    from reyes_agent.vision import parser, scene_state

    original_idle = input_guard.owner_idle_seconds
    original_current = scene_state.current
    original_fg = parser.foreground_handle

    stale = _scene()
    stale.window = "The window I read"
    stale.window_handle = 111111
    try:
        input_guard.owner_idle_seconds = lambda: 60.0
        scene_state.current = lambda **_: stale
        parser.foreground_handle = lambda: 222222        # owner alt-tabbed
        step = agentic.act("type", text="a private sentence")
        assert step.ok is False
        assert step.focus_moved is True
        assert "focus moved" in step.detail
    finally:
        input_guard.owner_idle_seconds = original_idle
        scene_state.current = original_current
        parser.foreground_handle = original_fg
        input_guard.reset()


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
