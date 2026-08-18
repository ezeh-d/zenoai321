"""Phase 4 — the backend ladder, lifecycle events, vision routing, and the web surface.

TEST F (fall back from deterministic methods to a visual agent), TEST K
(events appear in the right lifecycle order), TEST E (local vision routing)
and the security half of TEST M/N (the deployed page holds no secrets and
cannot control the machine).

Run: `.venv/Scripts/python.exe tests/test_phase4_routing.py`
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _Scene:
    def __init__(self, reliable=True, interactive=(), state="GOOD"):
        self.reliable = reliable
        self.interactive = list(interactive)
        self.coverage = type("C", (), {"state": state})()


# --- TEST F: the ladder --------------------------------------------------

def test_the_cheapest_technique_wins() -> None:
    """A visual agent can open Chrome. open_app does it in milliseconds."""
    from reyes_agent.computer import agent_backends as backends

    choice = backends.choose("open chrome", deterministic=lambda r: True)
    assert choice.backend == backends.NATIVE
    assert choice.guesses is False


def test_an_approved_skill_beats_generic_perception() -> None:
    from reyes_agent.computer import agent_backends as backends

    choice = backends.choose("run my project health check",
                             deterministic=lambda r: False,
                             has_skill=lambda r: True)
    assert choice.backend == backends.WORKFLOW
    assert "already approved" in choice.reason


def test_a_readable_window_is_acted_on_structurally() -> None:
    from reyes_agent.computer import agent_backends as backends

    choice = backends.choose("click Send", scene=_Scene(True, ["Send"]),
                             deterministic=lambda r: False)
    assert choice.backend == backends.ACCESSIBILITY
    assert choice.guesses is False


def test_an_unreadable_window_falls_down_the_ladder() -> None:
    """TEST F. Structure failed, so and only so does a visual backend apply."""
    from reyes_agent.computer import agent_backends as backends

    blind = _Scene(reliable=False, interactive=[], state="OPAQUE")
    choice = backends.choose("click the render button", scene=blind,
                             deterministic=lambda r: False)

    # Nothing visual is installed here, so it must reach the last rung and
    # be honest that the last rung guesses.
    assert choice.backend == backends.COORDINATES
    assert choice.guesses is True
    assert "rather ask you" in choice.reason
    # ...and it must have genuinely considered the visual rungs on the way.
    assert backends.CUA in choice.considered and backends.TARS in choice.considered


def test_a_visual_backend_is_used_when_one_is_actually_available() -> None:
    from reyes_agent.computer import agent_backends as backends
    from reyes_agent.computer.agent_backends import ladder

    original_enabled, original_installed = ladder.enabled, ladder.installed
    try:
        ladder.enabled = lambda b: b == backends.TARS
        ladder.installed = lambda b: b == backends.TARS
        choice = backends.choose("click render", scene=_Scene(False, [], "OPAQUE"),
                                 deterministic=lambda r: False)
        assert choice.backend == backends.TARS
        assert choice.guesses is False
    finally:
        ladder.enabled, ladder.installed = original_enabled, original_installed


def test_optional_rungs_are_off_by_default() -> None:
    from reyes_agent.computer import agent_backends as backends

    for rung in backends.describe()["ladder"]:
        if rung["optional"]:
            assert rung["enabled"] is False, f"{rung['backend']} must be opt-in"
            assert rung["flag"], "an optional rung must name its flag"


def test_the_ladder_order_matches_the_brief() -> None:
    from reyes_agent.computer import agent_backends as backends

    assert backends.LADDER[0] == backends.NATIVE
    assert backends.LADDER[-1] == backends.COORDINATES
    assert backends.LADDER.index(backends.UIA) < backends.LADDER.index(backends.CUA)
    assert backends.LADDER.index(backends.CUA) < backends.LADDER.index(backends.TARS)
    assert backends.LADDER.index(backends.TARS) < backends.LADDER.index(backends.VISION)


# --- TEST K: lifecycle events -------------------------------------------

def test_events_appear_in_the_right_lifecycle_order() -> None:
    """TEST K."""
    from reyes_agent import event_bus
    from reyes_agent.computer import lifecycle

    run = lifecycle.new_run_id()
    queue = event_bus.subscribe()
    try:
        lifecycle.observed(run, _Scene(True, ["Send"]))
        lifecycle.planned(run, "send it", [{"action": "click"}], backend="accessibility_action")
        lifecycle.requested(run, 0, "click", "Send", risk="ORDINARY")
        lifecycle.started(run, 0, "click", backend="accessibility_action")
        lifecycle.completed(run, 0, "click", "clicked (410,300)")
        lifecycle.verified(run, 0, True, "window changed: 'Draft' -> 'Sent'")
        lifecycle.succeeded(run, "1 step", steps=1)

        seen = []
        deadline = time.time() + 5
        while time.time() < deadline and len(seen) < 7:
            try:
                event = queue.get(timeout=0.5)
            except Exception:  # noqa: BLE001
                break
            payload = getattr(event, "payload", None) or {}
            if payload.get("run_id") == run:
                seen.append(payload.get("stage"))

        assert seen == [lifecycle.OBSERVATION, lifecycle.PLAN_CREATED,
                        lifecycle.ACTION_REQUESTED, lifecycle.ACTION_STARTED,
                        lifecycle.ACTION_COMPLETED, lifecycle.VERIFICATION,
                        lifecycle.SUCCESS], seen
    finally:
        event_bus.unsubscribe(queue)


def test_a_completed_step_cannot_be_claimed_without_evidence() -> None:
    """No fake progress -- the rule this project has held since phase 1."""
    from reyes_agent.computer import lifecycle

    run = lifecycle.new_run_id()
    for stage in (lifecycle.ACTION_COMPLETED, lifecycle.VERIFICATION, lifecycle.SUCCESS):
        assert lifecycle.emit(stage, run, {"index": 0}) is False, (
            f"{stage} was published with no evidence")
        assert lifecycle.emit(stage, run, {"index": 0}, evidence="really happened") is True

    # Stages that only announce intent do not need evidence.
    assert lifecycle.emit(lifecycle.ACTION_REQUESTED, run, {"index": 0}) is True


def test_all_nine_stages_exist() -> None:
    from reyes_agent.computer import lifecycle

    for stage in ("OBSERVATION", "PLAN_CREATED", "ACTION_REQUESTED", "ACTION_STARTED",
                  "ACTION_COMPLETED", "VERIFICATION", "RETRY", "FAILURE", "SUCCESS"):
        assert stage in lifecycle.STAGES


# --- TEST E: vision routing ---------------------------------------------

def test_a_structural_question_never_pays_for_a_model() -> None:
    """TEST E. UIA answers this in under a second, from ground truth."""
    from reyes_agent.vision import models

    for question in ("is there an error dialog?", "what buttons are on screen",
                     "what does the field say"):
        route = models.route(question, scene_reliable=True)
        assert route.tier == models.ACCESSIBILITY, question
        assert route.available is True


def test_a_visual_question_routes_to_the_smallest_model_and_admits_absence() -> None:
    from reyes_agent.vision import models

    route = models.route("does this layout look aligned?", scene_reliable=True)
    assert route.tier in (models.LIGHT, models.BALANCED, models.STRONG, models.CLOUD)
    if not route.available:
        assert route.fallback, "an unavailable tier must name what happens instead"


def test_hardware_is_measured_not_assumed() -> None:
    from reyes_agent.vision import models

    spec = models.hardware()
    assert spec.ram_gb > 0, "real RAM must be read"
    # torch is genuinely absent here; the profile must reflect that honestly.
    if not spec.torch:
        assert spec.best_local_tier is None
        assert models.status()["profile"] == "NONE_LOCAL"


def test_an_unreadable_screen_does_not_route_to_accessibility() -> None:
    from reyes_agent.vision import models

    route = models.route("what is on screen", scene_reliable=False)
    assert route.tier != models.ACCESSIBILITY


# --- the deployed web surface -------------------------------------------

def _web(name: str) -> str:
    return (ROOT / "web" / name).read_text(encoding="utf-8")


def test_the_public_page_cannot_control_the_computer() -> None:
    """The brief's critical rule, checked against the file that ships."""
    page = _web("index.html")
    for forbidden in ("/control-computer", "/run-command", "/shell", "/open-file",
                      "run_tool", "subprocess", "eval("):
        assert forbidden not in page, f"the public page references {forbidden!r}"

    config = (ROOT / "netlify.toml").read_text(encoding="utf-8")
    assert "[functions]" not in config, "no server-side code should ship with this site"


def test_the_deployed_site_ships_a_restrictive_csp() -> None:
    """The CSP is emitted by the BUILD, not by netlify.toml.

    It used to live in netlify.toml. It now lives in `web/_headers`, which is
    written by `scripts/build-config.js` at build time and is gitignored --
    so asserting against netlify.toml checked a file that no longer carries
    the policy, and would have passed happily with no CSP shipping at all.

    The generator is the committed source of truth, so that is what is
    checked here.
    """
    generator = (ROOT / "scripts" / "build-config.js").read_text(encoding="utf-8")
    assert "Content-Security-Policy" in generator, \
        "the build no longer emits a Content-Security-Policy"

    # The two directives that stop a page controlling anything it should not:
    # nothing may frame it, and no form may post anywhere off-origin.
    assert "frame-ancestors 'none'" in generator
    assert ("form-action 'none'" in generator or "form-action 'self'" in generator), \
        "form-action must be restricted; an unrestricted form can post credentials anywhere"

    for wildcard in ("default-src *", "script-src *", "connect-src *"):
        assert wildcard not in generator, f"CSP contains a wildcard: {wildcard!r}"


def test_no_secret_is_committed_to_the_web_surface() -> None:
    from reyes_agent.security.privacy import detector

    for name in ("index.html", "zeno-config.js"):
        hits = [h for h in detector.detect(_web(name)) if h.always_redact]
        assert not hits, f"{name} contains something credential-shaped"

    config = (ROOT / "netlify.toml").read_text(encoding="utf-8")
    assert not re.search(r"(?i)(api[_-]?key|secret|token|password)\s*=\s*[\"']\S{8,}", config)


def test_the_page_reports_offline_rather_than_breaking() -> None:
    """TEST N, as a property of the source rather than a live fetch."""
    page = _web("index.html")
    assert "ZENO CORE OFFLINE" in page
    assert ".catch(" in page, "a failed fetch must be handled, not thrown"
    assert "setTimeout" in page, "an unreachable backend must time out, not hang"


def test_nested_routes_are_redirected_so_a_refresh_works() -> None:
    config = (ROOT / "netlify.toml").read_text(encoding="utf-8")
    assert 'from = "/*"' in config and "status = 200" in config


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
