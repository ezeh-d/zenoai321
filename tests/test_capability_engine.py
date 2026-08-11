"""The universal capability engine — and the promise not to bluff.

Most of this file tests REFUSALS, because the brief's central demand is
negative: never claim a capability ZENO does not have, never fabricate a
result, and never hide behind "I don't support that".

Run: `.venv/Scripts/python.exe tests/test_capability_engine.py`
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# --- the cached inventory (the performance fix) --------------------------

def test_availability_is_asked_once_and_remembered() -> None:
    from reyes_agent.capabilities import inventory

    inventory.invalidate()
    started = time.perf_counter()
    inventory.which("definitely-not-a-real-binary-xyz")
    cold = time.perf_counter() - started

    started = time.perf_counter()
    for _ in range(50):
        inventory.which("definitely-not-a-real-binary-xyz")
    warm = (time.perf_counter() - started) / 50

    assert warm < cold / 5, f"cache is not helping: cold {cold*1000:.1f}ms, warm {warm*1000:.3f}ms"
    assert inventory.stats()["hits"] >= 50


def test_the_cache_tells_the_truth_about_this_machine() -> None:
    """A fast wrong answer is worse than a slow right one."""
    from reyes_agent.capabilities import inventory

    inventory.invalidate()
    for binary in ("git", "node", "definitely-not-real-xyz"):
        assert (inventory.which(binary) is not None) is (shutil.which(binary) is not None), binary
    for package in ("numpy", "psutil", "definitely_not_real_xyz"):
        expected = importlib.util.find_spec(package) is not None
        assert inventory.has_package(package) is expected, package


def test_installing_something_can_be_noticed() -> None:
    from reyes_agent.capabilities import inventory

    inventory.invalidate()
    inventory.which("git")
    before = inventory.stats()["binaries_cached"]
    inventory.invalidate("git")
    assert inventory.stats()["binaries_cached"] == before - 1
    inventory.invalidate()
    assert inventory.stats()["binaries_cached"] == 0


# --- capability state is detected, not declared -------------------------

def test_a_capability_is_never_ready_just_because_it_imported() -> None:
    from reyes_agent.capabilities import registry

    registry.status()
    for capability in registry.all_capabilities():
        state, why = capability.health()
        assert state in (registry.ONLINE, registry.READY, registry.STANDBY,
                         registry.AUTH_REQUIRED, registry.DEPENDENCY_MISSING,
                         registry.DEGRADED, registry.FAILED, registry.DISABLED), state
        assert why, f"{capability.name} reported {state} with no reason"
        if state in registry.USABLE:
            assert capability.present(), f"{capability.name} is READY but not present"


def test_detection_matches_the_real_machine() -> None:
    from reyes_agent.capabilities import registry

    registry.status()
    checks = [("ffmpeg", shutil.which("ffmpeg") is not None),
              ("node", shutil.which("node") is not None),
              ("numpy", importlib.util.find_spec("numpy") is not None),
              ("docling", importlib.util.find_spec("docling") is not None)]
    for name, really_here in checks:
        capability = registry.get(name)
        assert capability is not None, name
        assert capability.present() is really_here, (
            f"{name}: registry says present={capability.present()}, reality is {really_here}")


def test_a_missing_credential_is_auth_required_not_missing() -> None:
    """Different problems need different answers from the owner."""
    from reyes_agent.capabilities import registry

    registry.status()
    capability = registry.get("github")
    state, why = capability.health()
    if not capability.present():
        return
    if state == registry.AUTH_REQUIRED:
        assert "credential" in why.lower()


def test_credential_detection_is_deterministic() -> None:
    """It flapped between READY and AUTH_REQUIRED depending on import order."""
    from reyes_agent.capabilities import registry

    registry.status()
    for name in ("gemini", "openai", "deepgram"):
        answers = {registry.get(name).health()[0] for _ in range(5)}
        assert len(answers) == 1, f"{name} gave inconsistent answers: {answers}"


# --- the three honest answers -------------------------------------------

def test_email_automation_names_what_is_missing() -> None:
    """ACCEPTANCE 1. The exact exchange the brief opens with."""
    from reyes_agent import capabilities

    verdict = capabilities.can_i("automate my email")
    assert verdict.answer in (capabilities.UNDERSTOOD, capabilities.CAN_DO,
                              capabilities.HAVE_SKILL)
    assert "don't currently support" not in verdict.say.lower()

    if verdict.answer == capabilities.UNDERSTOOD:
        assert verdict.assessment.matched == "email_automation"
        assert verdict.assessment.blocking, "UNDERSTOOD must name a blocker"
        blockers = [g.capability for g in verdict.assessment.blocking]
        assert "email_provider" in blockers
        # ...and say what would fix it.
        assert any(s.needs_owner for s in verdict.steps)
        assert any("connect" in s.detail.lower() or "connect" in s.action
                   for s in verdict.steps)


def test_a_missing_dependency_never_becomes_a_fabricated_result() -> None:
    """ACCEPTANCE 6."""
    from reyes_agent import capabilities
    from reyes_agent.capabilities import registry

    registry.status()
    if registry.get("docling").present():
        return                       # nothing to assert on this machine

    verdict = capabilities.can_i("reconcile these invoices")
    assert verdict.executable is False
    assert verdict.answer == capabilities.UNDERSTOOD
    assert "docling" in " ".join(g.capability for g in verdict.assessment.blocking)
    plan = capabilities.plan("reconcile these invoices")
    assert plan["owner_actions"], "a fixable gap must name an owner action"
    assert "has been done" in plan["note"]


def test_an_unknown_request_offers_research_rather_than_a_guess() -> None:
    from reyes_agent import capabilities

    verdict = capabilities.can_i("flurbulate the widget matrix")
    assert verdict.answer == capabilities.UNKNOWN
    assert verdict.executable is False
    assert "research" in verdict.say.lower()
    assert any(s.action == "research" for s in verdict.steps)


def test_a_capability_we_really_have_answers_yes() -> None:
    """The engine must not be uselessly pessimistic either."""
    from reyes_agent import capabilities

    verdict = capabilities.can_i("research the best framework for computer use agents")
    assert verdict.answer == capabilities.CAN_DO
    assert verdict.executable is True
    assert verdict.assessment.have


def test_it_never_says_it_does_not_support_something() -> None:
    """The banned answer, checked across a wide spread of requests."""
    from reyes_agent import capabilities

    requests = ["automate my email", "reconcile these invoices", "design a logo",
                "control my lights", "convert this video to mp3",
                "something entirely made up", "prepare me for tomorrow",
                "analyse this business", "write code for me", "scrape this website"]
    for request in requests:
        say = capabilities.can_i(request).say.lower()
        assert say, request
        for banned in ("i don't support", "i do not support", "not supported",
                       "i can't help with that"):
            assert banned not in say, f"banned phrasing for {request!r}: {say[:80]}"


def test_an_optional_gap_degrades_instead_of_refusing() -> None:
    """A missing nice-to-have must not veto a whole task."""
    from reyes_agent.capabilities import graph

    assessment = graph.assess("prepare me for tomorrow")
    assert assessment.matched == "meeting_preparation"
    # Everything meeting prep touches is optional, so it must remain possible.
    assert assessment.can_do is True
    assert not assessment.blocking


def test_skill_composition_needs_no_hardcoded_command() -> None:
    """ACCEPTANCE 7."""
    from reyes_agent.capabilities import graph

    assessment = graph.assess("prepare me for tomorrow")
    assert len(assessment.optional) >= 3, "composition should draw on several capabilities"
    assert set(assessment.have) & {"memory", "semantic_search", "web_research"}


def test_an_approved_skill_is_the_strongest_yes() -> None:
    """ACCEPTANCE 9 -- and it must come from the persisted registry."""
    import tempfile

    from reyes_agent import capabilities, skills
    from reyes_agent.skills import registry as skill_registry

    temp = Path(tempfile.mkdtemp(prefix="zeno_cap_skills_"))
    original_root = skill_registry._root                    # noqa: SLF001
    try:
        skill_registry._root = lambda: temp                 # noqa: SLF001
        skill_registry.reset_cache()
        ok, _ = skills.manager.author("nightly backup", [{"action": "get_datetime"}],
                                      approved_by="owner")
        assert ok
        verdict = capabilities.can_i("run my nightly backup please")
        assert verdict.answer == capabilities.HAVE_SKILL
        assert verdict.skill == "nightly backup"
        assert verdict.executable is True
    finally:
        skill_registry._root = original_root                # noqa: SLF001
        skill_registry.reset_cache()


# --- security -----------------------------------------------------------

def test_a_capability_cannot_grant_itself_reach() -> None:
    """ACCEPTANCE 10. Acquiring a capability is never automatic."""
    from reyes_agent import capabilities

    plan = capabilities.plan("automate my email")
    for step in plan["steps"]:
        if step["action"] in ("install", "connect_account", "purchase",
                              "grant_permission"):
            assert step["needs_owner"] is True, step
    assert plan["executable"] is False


def test_dangerous_capabilities_are_marked_as_such() -> None:
    from reyes_agent.capabilities import registry

    registry.status()
    for name in ("github", "home_assistant", "computer_control", "sandbox",
                 "email_provider"):
        capability = registry.get(name)
        assert capability is not None, name
        assert capability.risk in (registry.SENSITIVE, registry.DANGEROUS), (
            f"{name} is marked {capability.risk}")


def test_what_can_you_do_is_read_from_reality() -> None:
    from reyes_agent import capabilities
    from reyes_agent.capabilities import registry

    answer = capabilities.what_can_you_do()
    assert answer["capabilities"], "the answer must not be empty"
    assert "not from a list someone wrote" in answer["note"]
    # Everything claimed usable must genuinely be usable right now.
    for name in registry.usable_names():
        assert registry.get(name).usable, name
    assert set(answer["can_do_now"]).isdisjoint(set(answer["blocked"]))


def test_nothing_in_the_engine_raises() -> None:
    from reyes_agent import capabilities

    for call in (capabilities.status, capabilities.what_can_you_do,
                 capabilities.registry.status, capabilities.graph.status,
                 capabilities.inventory.stats):
        assert call() is not None


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
