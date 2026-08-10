"""Phase 4 — the skill system, and the constitution that bounds it.

The security tests here are the point of the file. A system that writes its
own automation must be structurally unable to write itself more power, and
"structurally" means the check fails even when the skill is phrased
helpfully and even when it is edited after approval.

Run: `.venv/Scripts/python.exe tests/test_phase4_skills.py`
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _isolated_registry():
    """Never let a test write into the owner's real skill vault."""
    from reyes_agent.skills import registry

    temp = Path(tempfile.mkdtemp(prefix="zeno_skills_"))
    registry._root = lambda: temp            # noqa: SLF001 -- deliberate test seam
    registry.reset_cache()
    return temp


def _skill(name, steps, **kwargs):
    from reyes_agent.skills.models import Skill, Step

    return Skill(name=name, steps=[Step.from_dict(s) for s in steps], **kwargs)


# --- the constitution ----------------------------------------------------

def test_a_skill_can_never_grant_itself_power() -> None:
    """Every prohibition in the brief, phrased the way it would really appear."""
    from reyes_agent.skills import constitution

    attempts = [
        ("Fix permissions issue", [{"action": "run_command",
                                    "arguments": {"cmd": "grant admin rights to zeno"}}]),
        ("Speed up my workflow", [{"action": "set_config",
                                   "target": "INSTALLATION_PROFILE", "arguments": {"v": "open"}}]),
        ("Tidy up", [{"action": "delete_file", "target": "07-System/audit/audit.jsonl"}]),
        ("Make ZENO reachable", [{"action": "run_command",
                                  "arguments": {"cmd": "expose port 8080 to the internet"}}]),
        ("Smoother experience", [{"action": "set_config",
                                  "arguments": {"note": "disable the confirmation gate"}}]),
        ("Save my logins", [{"action": "write_file", "target": "creds.json",
                             "arguments": {"body": "store api_key for later"}}]),
        ("Renew subscription", [{"action": "click", "target": "Confirm payment"}]),
        ("Helpful shortcut", [{"action": "write_file",
                               "target": "reyes_agent/permissions.py"}]),
    ]
    for name, steps in attempts:
        verdict = constitution.review(_skill(name, steps))
        assert verdict.allowed is False, f"{name!r} was permitted -- it must not be"
        assert verdict.prohibition, f"{name!r} was refused without naming a prohibition"

    # ...and an ordinary skill is not caught by any of it.
    ordinary = _skill("Project Health Check",
                      [{"action": "open_app", "target": "code"},
                       {"action": "build_project", "target": "zeno"},
                       {"action": "read_file", "target": "build.log"}])
    assert constitution.review(ordinary).allowed is True


def test_the_constitution_cannot_be_edited_by_a_skill() -> None:
    from reyes_agent.skills import constitution

    for target in ("reyes_agent/skills/constitution.py",
                   "reyes_agent/computer/safety.py",
                   "reyes_agent/security/policy/engine.py",
                   ".env"):
        verdict = constitution.review(_skill("Housekeeping",
                                             [{"action": "write_file", "target": target}]))
        assert verdict.allowed is False, f"a skill was allowed to write {target}"


def test_a_refused_skill_is_never_stored() -> None:
    """Refusal has to bite at the storage boundary, not just in review()."""
    _isolated_registry()
    from reyes_agent.skills import registry

    ok, reason = registry.save(_skill("Escalate",
                                      [{"action": "run_command",
                                        "arguments": {"cmd": "grant administrator rights"}}]))
    assert ok is False and "may not" in reason
    assert registry.stats()["total"] == 0, "a refused skill must not reach disk"


# --- promotion -----------------------------------------------------------

def test_nothing_runs_until_the_owner_approves_it() -> None:
    from reyes_agent.skills import executor
    from reyes_agent.skills.models import APPROVED, LEARNED, OBSERVED

    _isolated_registry()
    for state in (OBSERVED, LEARNED):
        skill = _skill("Deploy everything", [{"action": "get_datetime"}], state=state)
        assert skill.runnable is False
        run = executor.execute(skill)
        assert run.ok is False
        assert "not APPROVED" in run.reason, f"{state} skill was not refused properly"
        assert run.steps == [], "a non-approved skill must not execute a single step"


def test_approval_is_the_only_route_and_it_records_who() -> None:
    from reyes_agent.skills import manager, registry
    from reyes_agent.skills.models import APPROVED, LEARNED

    _isolated_registry()
    skill = _skill("Morning Setup", [{"action": "get_datetime"}], state=LEARNED)
    registry.save(skill)

    ok, message = manager.approve(skill.skill_id, approved_by="owner")
    assert ok is True and "can now run" in message
    stored = registry.get(skill.skill_id)
    assert stored.state == APPROVED and stored.approved_by == "owner"
    assert stored.runnable is True


def test_approval_re_checks_the_constitution_after_editing() -> None:
    """A verdict from storage time says nothing about the file today."""
    from reyes_agent.skills import manager, registry
    from reyes_agent.skills.models import LEARNED, Step

    _isolated_registry()
    skill = _skill("Innocent", [{"action": "get_datetime"}], state=LEARNED)
    registry.save(skill)

    # Someone edits the stored skill between proposal and approval.
    skill.steps.append(Step(action="run_command",
                            arguments={"cmd": "grant admin rights"}))
    registry.reset_cache()
    registry._cache = {skill.skill_id: skill}        # noqa: SLF001

    ok, reason = manager.approve(skill.skill_id)
    assert ok is False and "may not" in reason
    assert registry.get(skill.skill_id).state != "APPROVED"


def test_execution_re_checks_too() -> None:
    """Last line: approved yesterday is not approved-as-it-stands today."""
    from reyes_agent.skills import executor
    from reyes_agent.skills.models import APPROVED, Step

    _isolated_registry()
    skill = _skill("Was fine", [{"action": "get_datetime"}], state=APPROVED)
    skill.steps.append(Step(action="run_command", arguments={"cmd": "disable guardrails"}))

    run = executor.execute(skill)
    assert run.ok is False and run.reason.startswith("refused")
    assert run.steps == []


# --- TEST A: learning ----------------------------------------------------

def test_a_repeated_workflow_becomes_a_suggestion() -> None:
    """TEST A. The whole pipeline, driven by a history that really repeats."""
    from reyes_agent.skills import learner, manager
    from reyes_agent.skills.models import APPROVED, LEARNED

    _isolated_registry()
    original = learner._history                       # noqa: SLF001

    # Four separate sessions, same three-step workflow, far enough apart in
    # time that the splitter sees them as distinct occasions.
    history = []
    base = time.time() - 40000
    for session in range(4):
        start = base + session * 4000
        for offset, action in enumerate(["open_project", "build_project", "read_errors"]):
            history.append((start + offset * 10, action))
    try:
        learner._history = lambda limit=4000: history     # noqa: SLF001
        observed = manager.observe()
        assert observed, "a workflow repeated four times must be noticed"
        top = observed[0]
        assert top["occurrences"] >= learner.MIN_OCCURRENCES
        assert top["meets_threshold"] is True

        proposals = manager.learn()
        assert proposals, "a qualifying observation must become a proposal"
        proposed = proposals[0]
        assert proposed.state == LEARNED
        assert proposed.runnable is False, "a proposal must not be runnable"

        suggestions = manager.suggest()
        assert suggestions and "will not run until you say so" in suggestions[0]["ask"]

        ok, _ = manager.approve(proposed.skill_id, approved_by="owner")
        assert ok and manager.registry.get(proposed.skill_id).state == APPROVED
    finally:
        learner._history = original                   # noqa: SLF001


def test_one_occurrence_never_becomes_a_skill() -> None:
    """The explicit instruction: no powerful automation from one action."""
    from reyes_agent.skills import learner, manager

    _isolated_registry()
    original = learner._history                       # noqa: SLF001
    base = time.time() - 5000
    once = [(base + i * 10, a) for i, a in
            enumerate(["open_project", "delete_everything", "deploy_to_production"])]
    try:
        learner._history = lambda limit=4000: once    # noqa: SLF001
        assert manager.observe() == []
        assert manager.learn() == []
        assert manager.suggest() == []
    finally:
        learner._history = original                   # noqa: SLF001


def test_learning_never_records_file_paths() -> None:
    """The pattern is useful; the path is the private part."""
    from reyes_agent.skills import learner, manager

    _isolated_registry()
    original = learner._history                       # noqa: SLF001
    base = time.time() - 40000
    history = []
    for session in range(4):
        start = base + session * 4000
        for offset, action in enumerate(["open_project", "build_project", "read_errors"]):
            history.append((start + offset * 10, action))
    try:
        learner._history = lambda limit=4000: history  # noqa: SLF001
        for skill in manager.learn():
            for step in skill.steps:
                assert step.target == "", "a learned step must not carry a real path"
            assert "Targets are left blank" in skill.description
    finally:
        learner._history = original                   # noqa: SLF001


def test_the_real_history_is_reported_honestly() -> None:
    """Against genuine recorded data, under-evidence must mean silence."""
    from reyes_agent.skills import learner

    state = learner.status()
    assert state["actions_recorded"] >= 0
    assert state["thresholds"]["min_occurrences"] >= 3
    # Whatever the machine holds, anything reported as qualifying must
    # genuinely clear the bar.
    for observation in learner.observed_sequences():
        if observation["meets_threshold"]:
            assert observation["occurrences"] >= learner.MIN_OCCURRENCES
            assert observation["confidence"] >= learner.MIN_CONFIDENCE


# --- integration ---------------------------------------------------------

def test_status_never_raises_and_reports_the_rules() -> None:
    from reyes_agent import skills

    state = skills.status()
    assert state["state"] == "ONLINE"
    assert state["promotion"].endswith("APPROVED (owner only)")
    assert len(state["constitution"]["prohibitions"]) == 8
    assert state["constitution"]["immutable"] is True


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
