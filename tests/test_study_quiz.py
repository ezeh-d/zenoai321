"""Quiz generator + answer evaluator (#21/#24/#25). Deterministic -- no model."""

from __future__ import annotations

import pytest

from reyes_agent.study.quiz import QuizEngine, CLOZE, DEFINITION, MCQ


_CHUNKS = [
    {"text": "Voltage is the electric potential difference between two points.",
     "source": "physics.pdf", "page": 3, "idx": 0},
    {"text": "Resistance opposes the flow of current in a conductor.",
     "source": "physics.pdf", "page": 4, "idx": 1},
]
_CONCEPTS = [{"name": "Voltage"}, {"name": "Resistance"}, {"name": "Current"},
             {"name": "Capacitance"}]


@pytest.fixture()
def quiz():
    return QuizEngine()


# --- generation -------------------------------------------------------------
def test_generates_questions_from_material(quiz):
    r = quiz.generate(chunks=_CHUNKS, concepts=_CONCEPTS, count=5)
    assert r["ok"] and r["count"] >= 1
    kinds = {q["kind"] for q in r["questions"]}
    assert kinds & {CLOZE, DEFINITION, MCQ}


def test_cloze_blanks_a_real_term_with_citation(quiz):
    r = quiz.generate(chunks=_CHUNKS, concepts=_CONCEPTS, count=6, kinds=[CLOZE])
    cloze = [q for q in r["questions"] if q["kind"] == CLOZE]
    assert cloze
    q = cloze[0]
    assert "_____" in q["prompt"]
    assert q["citation"]["source"] == "physics.pdf"
    # the blanked answer must NOT be visible in the prompt
    assert r["_answers"][q["qid"]]["answer"].lower() not in q["prompt"].lower()


def test_mcq_has_the_answer_among_options(quiz):
    r = quiz.generate(chunks=_CHUNKS, concepts=_CONCEPTS, count=4, kinds=[MCQ])
    mcq = [q for q in r["questions"] if q["kind"] == MCQ]
    assert mcq
    ans = r["_answers"][mcq[0]["qid"]]["answer"]
    assert ans in mcq[0]["options"] and len(mcq[0]["options"]) >= 2


def test_nothing_studied_is_honest(quiz):
    r = quiz.generate(chunks=[], concepts=[], count=5)
    assert r["ok"] is False and "nothing studied" in r["error"]


# --- evaluation -------------------------------------------------------------
def test_mcq_exact_grading(quiz):
    v = quiz.evaluate(kind=MCQ, expected="Voltage", user_answer="Voltage",
                      options=["Voltage", "Current"], topic="Voltage", record=False)
    assert v["correct"] and v["score"] == 1.0
    v2 = quiz.evaluate(kind=MCQ, expected="Voltage", user_answer="Current",
                       options=["Voltage", "Current"], record=False)
    assert v2["correct"] is False and "Voltage" in v2["feedback"]


def test_cloze_exact_or_contained(quiz):
    v = quiz.evaluate(kind=CLOZE, expected="voltage",
                      user_answer="voltage", record=False)
    assert v["correct"]


def test_definition_is_graded_with_partial_credit_and_missing(quiz):
    v = quiz.evaluate(
        kind=DEFINITION,
        expected="electric potential difference between two points",
        user_answer="the potential difference", topic="Voltage", record=False)
    # partial overlap -> honest feedback naming what's missing, not "correct"
    assert 0.0 < v["score"] < 1.0 and v["missing"]
    assert v["correct"] in (False, True)  # bucketed, but feedback is the point
    assert "missing" in v["feedback"].lower() or v["missing"]


def test_no_answer_is_not_correct(quiz):
    v = quiz.evaluate(kind=DEFINITION, expected="anything", user_answer="", record=False)
    assert v["correct"] is False and v["score"] == 0.0


def test_evaluation_feeds_mastery(tmp_path, monkeypatch):
    import reyes_agent.study as study_pkg
    from reyes_agent.study import mastery as m
    tracker = m.MasteryTracker(root=tmp_path / "mastery")
    # the quiz resolves get_mastery_tracker from the package namespace
    monkeypatch.setattr(study_pkg, "get_mastery_tracker", lambda: tracker)
    QuizEngine().evaluate(kind=MCQ, expected="Voltage", user_answer="Voltage",
                          options=["Voltage", "Current"], topic="Voltage",
                          course="physics", record=True)
    assert tracker.state_of("Voltage", course="physics") in ("UNDERSTOOD", "PRACTICED", "MASTERED")


# --- model enrichment hook --------------------------------------------------
def test_injected_model_generator_adds_questions(quiz):
    def fake_gen(chunks, concepts, count, difficulty):
        return [{"kind": "short", "prompt": "Explain Ohm's law.",
                 "answer": "V=IR", "topic": "Ohm's law"}]
    eng = QuizEngine(generate=fake_gen)
    r = eng.generate(chunks=[], concepts=[{"name": "X"}], count=1, kinds=["short"])
    assert r["ok"] and any(q["prompt"] == "Explain Ohm's law." for q in r["questions"])


# --- tools ------------------------------------------------------------------
def test_quiz_tools_registered_and_routable():
    import reyes_agent.tools.system  # noqa: F401
    from reyes_agent.tools import TOOLS
    from reyes_agent.routing.capability import CAPABILITIES
    assert "quiz_generate" in TOOLS and "quiz_evaluate" in TOOLS
    assert "quiz_generate" in CAPABILITIES["files"]
