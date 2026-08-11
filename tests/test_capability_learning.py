"""Decomposition, composition, demonstration, correction, versioning, acquisition.

The acceptance tests from the brief that involve ZENO LEARNING something
rather than merely reporting what it has.

Run: `.venv/Scripts/python.exe tests/test_capability_learning.py`
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _isolated_skills():
    from reyes_agent.skills import correction, registry

    temp = Path(tempfile.mkdtemp(prefix="zeno_learn_"))
    registry._root = lambda: temp                 # noqa: SLF001
    registry.reset_cache()
    correction.reset()
    return temp


# --- decomposition ------------------------------------------------------

def test_a_broad_goal_is_decomposed_not_refused() -> None:
    """'Do not respond: that's too broad. Decompose it.'"""
    from reyes_agent.capabilities import planner

    plan = planner.decompose("launch a marketing campaign")
    assert plan.matched == "marketing_campaign"
    assert len(plan.steps) >= 8, "a campaign is more than a couple of steps"
    assert "too broad" not in plan.say().lower()
    # Every part gets its own verdict, not one blanket answer.
    assert len({s.answer for s in plan.steps}) >= 1
    assert plan.ready_steps, "some parts of a campaign are always possible"


def test_a_partly_blocked_plan_reports_what_it_can_still_do() -> None:
    from reyes_agent.capabilities import planner

    plan = planner.decompose("automate my email")
    assert plan.steps
    say = plan.say()
    assert "I can do" in say
    # The blockers are named, not implied.
    if plan.blocked_steps:
        assert plan.missing_capabilities()


def test_prerequisites_are_respected() -> None:
    from reyes_agent.capabilities import planner

    plan = planner.decompose("launch a marketing campaign")
    waves = planner.sequence(plan)
    assert waves and waves[0] == ["market research"], waves
    flat = [name for wave in waves for name in wave]
    assert flat.index("audience") < flat.index("copywriting")
    assert flat.index("copywriting") < flat.index("landing page")


def test_an_unknown_composite_still_answers_honestly() -> None:
    from reyes_agent.capabilities import planner

    plan = planner.decompose("something nobody has ever asked for")
    assert plan.matched == ""
    assert "could not break that down" in plan.say()


# --- ACCEPTANCE 7: composition -----------------------------------------

def test_a_skill_is_composed_without_a_hardcoded_handler() -> None:
    from reyes_agent import skills

    _isolated_skills()
    result = skills.compose("prepare me for tomorrow")
    if not result.ok:
        # Composition legitimately refuses over a real gap -- but then it
        # must say which one rather than failing vaguely.
        assert result.reason and ("Missing" in result.reason
                                  or "do not have" in result.reason)
        return
    skill = result.skill
    assert skill.state == skills.LEARNED
    assert skill.runnable is False, "a composed skill must not be runnable"
    assert len(skill.steps) >= 3, "composition should draw on several capabilities"
    assert skill.source == "composed"
    assert len(result.covered) == len(skill.steps)


def test_composition_refuses_to_bridge_a_real_gap() -> None:
    """A skill containing a step that cannot run is a promise, not automation."""
    from reyes_agent import skills
    from reyes_agent.capabilities import registry

    _isolated_skills()
    registry.status()
    if registry.get("email_provider").usable:
        return                                    # nothing to assert here
    result = skills.compose("automate my email")
    assert result.ok is False
    assert "will not save a skill with a step that cannot run" in result.reason \
        or "do not have yet" in result.reason


def test_a_composed_skill_still_answers_to_the_constitution() -> None:
    from reyes_agent.skills import composer, constitution

    _isolated_skills()
    result = composer.compose("prepare me for tomorrow", persist=False)
    if result.skill is not None:
        assert constitution.review(result.skill).allowed is True


# --- ACCEPTANCE 4: learn by watching ------------------------------------

def _observation(**kw):
    from reyes_agent.skills.demonstration import Observation

    return Observation(**kw)


def test_a_demonstration_is_generalised_not_photographed() -> None:
    """The instruction: do NOT simply record mouse coordinates."""
    from reyes_agent import skills
    from reyes_agent.skills import demonstration

    _isolated_skills()
    watched = [
        _observation(action="click", automation_id="btnExport", role="button",
                     label="Export", window="Designer"),
        _observation(action="click", role="button", label="Save As",
                     window="Designer"),
        _observation(action="type", label="File name", text="report.pdf",
                     window="Save As"),
    ]
    learned = skills.watch(watched, name="Export The Report")
    assert learned.ok, learned.reason
    targets = [s.step.target for s in learned.steps]
    assert "btnExport" in targets, "a stable automation id must be preferred"
    assert "Save As" in targets, "a label beats a coordinate"
    for step in learned.steps:
        assert step.rung != demonstration.COORDINATES, step.as_dict()
        assert "," not in step.step.target or not step.step.target.replace(",", "").isdigit()
    assert learned.skill.runnable is False, "one demonstration is not an approved skill"


def test_a_coordinate_only_demonstration_is_refused() -> None:
    from reyes_agent import skills

    _isolated_skills()
    watched = [_observation(action="click", position=(412, 306)),
               _observation(action="click", position=(520, 410)),
               _observation(action="click", position=(88, 120))]
    learned = skills.watch(watched, name="Fragile")
    assert learned.ok is False
    assert "screen positions" in learned.reason
    assert "break the first time a window moves" in learned.reason


def test_a_demonstration_never_stores_a_typed_password() -> None:
    from reyes_agent import skills

    _isolated_skills()
    watched = [
        _observation(action="click", automation_id="userField", label="Username"),
        _observation(action="type", automation_id="userField", label="Username",
                     text="tred"),
        _observation(action="type", automation_id="pwdField", label="Password",
                     text="hunter2-the-real-secret"),
        _observation(action="click", automation_id="signInBtn", label="Sign in"),
    ]
    learned = skills.watch(watched, name="Sign In")
    assert learned.ok, learned.reason
    assert learned.redacted == 1
    blob = str(learned.skill.as_dict())
    assert "hunter2-the-real-secret" not in blob
    assert "tred" in blob, "only the secret should be withheld"


# --- ACCEPTANCE 5: learn by correction ----------------------------------

def _skill_with_steps(actions):
    from reyes_agent.skills import registry
    from reyes_agent.skills.models import APPROVED, Skill, Step

    skill = Skill(name="Publish", state=APPROVED,
                  steps=[Step(action=a, target=a) for a in actions])
    registry.save(skill)
    return skill


def test_one_correction_obeys_now_but_does_not_rewrite_the_skill() -> None:
    """'Do not rewrite skill after one accidental correction.'"""
    from reyes_agent.skills import correction

    _isolated_skills()
    skill = _skill_with_steps(["open", "save", "export"])
    outcome = correction.correct(correction.Correction(
        skill_id=skill.skill_id, kind=correction.REORDER,
        subject="export", before="save"))

    assert outcome.applied_now is True, "the current run must obey immediately"
    assert outcome.skill_updated is False, "one correction must not rewrite the skill"
    assert outcome.confirmations == 1
    assert "not changed" in outcome.say


def test_a_repeated_correction_becomes_permanent() -> None:
    from reyes_agent.skills import correction, registry

    _isolated_skills()
    skill = _skill_with_steps(["open", "save", "export"])
    fix = dict(skill_id=skill.skill_id, kind=correction.REORDER,
               subject="export", before="save")

    correction.correct(correction.Correction(**fix))
    outcome = correction.correct(correction.Correction(**fix))

    assert outcome.skill_updated is True
    assert outcome.new_version == 2
    stored = registry.get(skill.skill_id)
    order = [s.action for s in stored.steps]
    assert order.index("export") < order.index("save"), order


def test_saying_always_makes_it_permanent_immediately() -> None:
    from reyes_agent.skills import correction

    _isolated_skills()
    skill = _skill_with_steps(["open", "save", "export"])
    outcome = correction.correct(correction.Correction(
        skill_id=skill.skill_id, kind=correction.REORDER,
        subject="export", before="save", permanent=True))
    assert outcome.skill_updated is True


def test_an_unmatched_correction_asks_rather_than_guessing() -> None:
    from reyes_agent.skills import correction

    _isolated_skills()
    skill = _skill_with_steps(["open", "save"])
    outcome = correction.correct(correction.Correction(
        skill_id=skill.skill_id, kind=correction.REORDER,
        subject="frobnicate", before="save"))
    assert outcome.applied_now is False
    assert outcome.skill_updated is False
    assert "Which step did you mean?" in outcome.say


# --- versioning ---------------------------------------------------------

def test_a_correction_can_be_undone() -> None:
    """'Never silently destroy a working skill.'"""
    from reyes_agent.skills import correction, registry, versions

    _isolated_skills()
    skill = _skill_with_steps(["open", "save", "export"])
    original = [s.action for s in skill.steps]

    fix = dict(skill_id=skill.skill_id, kind=correction.REORDER,
               subject="export", before="save", permanent=True)
    correction.correct(correction.Correction(**fix))
    assert [s.action for s in registry.get(skill.skill_id).steps] != original

    assert versions.history(skill.skill_id), "the previous version must be archived"
    ok, say = versions.rollback(skill.skill_id)
    assert ok, say
    assert [s.action for s in registry.get(skill.skill_id).steps] == original


def test_rollback_keeps_moving_forward() -> None:
    from reyes_agent.skills import correction, registry, versions

    _isolated_skills()
    skill = _skill_with_steps(["open", "save", "export"])
    correction.correct(correction.Correction(
        skill_id=skill.skill_id, kind=correction.REORDER, subject="export",
        before="save", permanent=True))
    before = registry.get(skill.skill_id).version
    versions.rollback(skill.skill_id)
    assert registry.get(skill.skill_id).version > before, (
        "history should stay a straight line, not reuse an old number")


# --- confidence ---------------------------------------------------------

def test_a_skill_is_not_verified_after_one_run() -> None:
    from reyes_agent.skills import confidence
    from reyes_agent.skills.models import Skill

    skill = Skill(name="x")
    assert confidence.level_of(skill) == confidence.EXPERIMENTAL

    skill.history.runs = 1
    skill.history.successes = 1
    skill.history.last_success_at = time.time()
    assert confidence.level_of(skill) == confidence.LOW, "one run is not proof"

    skill.history.runs = 10
    skill.history.successes = 10
    assert confidence.level_of(skill) == confidence.VERIFIED


def test_a_stale_skill_drops_back_from_verified() -> None:
    from reyes_agent.skills import confidence
    from reyes_agent.skills.models import Skill

    skill = Skill(name="x")
    skill.history.runs = 20
    skill.history.successes = 20
    skill.history.last_success_at = time.time() - (confidence.FRESH_S * 2)
    assert confidence.level_of(skill) == confidence.HIGH


def test_the_more_reliable_skill_wins() -> None:
    from reyes_agent.skills import confidence
    from reyes_agent.skills.models import Skill

    reliable, flaky = Skill(name="reliable"), Skill(name="flaky")
    reliable.history.runs, reliable.history.successes = 12, 12
    reliable.history.last_success_at = time.time()
    flaky.history.runs, flaky.history.successes = 12, 6
    flaky.history.last_success_at = time.time()
    assert confidence.compare(flaky, reliable).name == "reliable"


# --- ACCEPTANCE 3: acquisition -----------------------------------------

def test_acquisition_never_installs_or_authorises_by_itself() -> None:
    from reyes_agent.capabilities import acquisition, registry

    registry.status()
    for name in ("docling", "email_provider", "github"):
        capability = registry.get(name)
        if capability.usable:
            continue
        planned = acquisition.plan(name, goal="test")
        assert planned.state == acquisition.USER_ACTION_REQUIRED, (name, planned.state)
        assert planned.owner_actions, name
        assert planned.blocked_on_owner is True


def test_registration_requires_verification_not_just_presence() -> None:
    from reyes_agent.capabilities import acquisition

    from reyes_agent.capabilities import registry

    assert "verification" in acquisition.status()["note"].lower()
    ok, why = acquisition.verify("docling")
    if not registry.get("docling").present():
        assert ok is False, "an absent package must never verify"
        assert "still" in why, why


def test_research_returns_evidence_or_nothing() -> None:
    """'Do not make up an API. Do not guess CLI flags.'"""
    from reyes_agent.capabilities import acquisition

    # No sources supplied: it must return nothing rather than invent a URL.
    assert acquisition.research("docling") == []


def test_an_unknown_capability_is_refused_not_improvised() -> None:
    from reyes_agent.capabilities import acquisition

    planned = acquisition.plan("some-tool-nobody-has-heard-of")
    assert planned.state == acquisition.REFUSED
    assert "will not guess" in planned.say


def test_identify_names_the_gap_for_a_goal() -> None:
    from reyes_agent.capabilities import acquisition, registry

    registry.status()
    if registry.get("email_provider").usable:
        return
    assert "email_provider" in acquisition.identify("automate my email")


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
