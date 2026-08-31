"""Learning Engine Phase 2: mastery model (#20, #35) and concept graph (#4, #5).
Both are deterministic -- no model, no network."""

from __future__ import annotations

import pytest

from reyes_agent.study.mastery import (
    LEARNING, MASTERED, NEEDS_REVISION, PRACTICED, UNDERSTOOD, MasteryTracker,
)
from reyes_agent.study.concepts import ConceptGraph, REQUIRES


# --- mastery ----------------------------------------------------------------
@pytest.fixture()
def mastery(tmp_path):
    return MasteryTracker(root=tmp_path / "mastery")


def test_studied_moves_to_learning(mastery):
    mastery.introduce("transfer functions", course="control")
    r = mastery.studied("transfer functions", course="control")
    assert r["state"] == LEARNING


def test_one_correct_answer_is_not_mastery(mastery):
    mastery.studied("root locus", course="control")
    r = mastery.answered("root locus", correct=True, course="control", session="d1")
    assert r["state"] == UNDERSTOOD
    assert r["state"] != MASTERED           # #20: never mastery from one answer


def test_sustained_correct_across_sessions_reaches_mastery(mastery):
    t = "bode plots"
    mastery.studied(t, course="control")
    mastery.answered(t, correct=True, course="control", session="d1")
    mastery.answered(t, correct=True, course="control", session="d1")  # PRACTICED
    assert mastery.state_of(t, course="control") == PRACTICED
    mastery.answered(t, correct=True, course="control", session="d2")
    mastery.answered(t, correct=True, course="control", session="d2")  # 4 correct, 2 sessions
    assert mastery.state_of(t, course="control") == MASTERED


def test_a_miss_on_understood_flags_revision(mastery):
    t = "nyquist"
    mastery.studied(t, course="control")
    mastery.answered(t, correct=True, course="control", session="d1")   # UNDERSTOOD
    r = mastery.answered(t, correct=False, course="control", session="d1")
    assert r["state"] == NEEDS_REVISION


def test_report_progress_is_honest(mastery):
    mastery.studied("a", course="c")                                  # LEARNING
    mastery.answered("b", correct=True, course="c", session="d1")     # UNDERSTOOD
    mastery.answered("c", correct=True, course="c", session="d1")     # UNDERSTOOD
    rep = mastery.report(course="c")
    # 2 of 3 topics reached understanding
    assert rep["topics"] == 3 and rep["progress"] == round(100 * 2 / 3)
    assert rep["understood"] == 2 and rep["learning"] == 1


def test_weak_areas_prioritise_revision(mastery):
    mastery.studied("weak1", course="c")                              # LEARNING
    mastery.answered("weak2", correct=True, course="c", session="d1")
    mastery.answered("weak2", correct=False, course="c", session="d1")  # NEEDS_REVISION
    weak = mastery.weak_topics(course="c")
    assert weak and weak[0]["topic"] == "weak2"                       # revision first


def test_mastery_persists_across_a_fresh_tracker(tmp_path):
    root = tmp_path / "mastery"
    MasteryTracker(root=root).answered("x", correct=True, course="c", session="d1")
    assert MasteryTracker(root=root).state_of("x", course="c") == UNDERSTOOD


def test_reset_clears_a_course(mastery):
    mastery.studied("y", course="c")
    assert mastery.reset(course="c")["cleared"] is True
    assert mastery.report(course="c")["topics"] == 0


# --- concept graph ----------------------------------------------------------
@pytest.fixture()
def graph(tmp_path):
    return ConceptGraph(root=tmp_path / "concepts")


def test_add_concepts_and_a_typed_relation(graph):
    graph.add_relation("Calculus", REQUIRES, "Algebra", course="math")
    rel = graph.relations_of("Calculus", course="math")
    assert rel["ok"] and rel["outgoing"][0]["rel"] == REQUIRES
    assert rel["outgoing"][0]["to"] == "Algebra"


def test_prerequisites_are_transitive_deepest_first(graph):
    graph.add_relation("Fourier Transform", REQUIRES, "Complex Numbers", course="ee")
    graph.add_relation("Complex Numbers", REQUIRES, "Trigonometry", course="ee")
    chain = graph.prerequisites("Fourier Transform", course="ee")
    assert chain == ["Trigonometry", "Complex Numbers"]   # teach deepest first


def test_missing_prerequisites_given_what_is_known(graph):
    graph.add_relation("Fourier Transform", REQUIRES, "Complex Numbers", course="ee")
    graph.add_relation("Complex Numbers", REQUIRES, "Trigonometry", course="ee")
    missing = graph.missing_prerequisites(
        "Fourier Transform", known=["Trigonometry"], course="ee")
    assert missing == ["Complex Numbers"]


def test_deterministic_extraction_from_definitions(graph):
    text = ("Recursion is a technique where a function calls itself. "
            "Voltage refers to electric potential difference.")
    out = graph.ingest_text(text, course="general")
    assert out["concepts_added"] >= 2
    names = [n.lower() for n in graph.summary(course="general")["names"]]
    assert any("recursion" in n for n in names)


def test_extraction_of_requires_edges(graph):
    graph.ingest_text("Calculus requires Algebra.", course="general")
    assert graph.prerequisites("Calculus", course="general") == ["Algebra"]


# --- tools registered -------------------------------------------------------
def test_phase2_tools_registered():
    import reyes_agent.tools.system  # noqa: F401
    from reyes_agent.tools import TOOLS
    for name in ("study_report", "study_weak_areas", "study_mastery_update",
                 "concept_prerequisites"):
        assert name in TOOLS
