"""Brain tools for the Universal Learning Engine (Phase 1).

ZENO calls these when the owner says "study this", "what did you learn?", "where
did you get that?". They ingest and index documents for study and return
GROUNDED passages with citations -- ZENO's brain then does the explaining/
teaching on top. Owner-direct: studying and recalling user-provided content are
normal actions and do not ask for repeated approval (#40).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from reyes_agent.tools import register


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _resolve(target: str) -> str:
    raw = str(target or "it").strip().strip('"').strip("'")
    if raw and Path(os.path.expanduser(raw)).exists():
        return str(Path(os.path.expanduser(raw)))
    try:
        from reyes_agent.content import get_context
        ref = get_context().resolve(target or "it")
        return ref.path if ref.ok else ""
    except Exception:  # noqa: BLE001
        return ""


@register(
    name="study_document",
    description=(
        "Study a document so ZENO can answer questions about it later WITH "
        "citations. Parses it, splits it into passages with real provenance "
        "(per-page for PDFs), embeds them and saves them to a persistent study "
        "store. Accepts a path or a reference ('it', 'that file'). Use when the "
        "owner says 'study this', 'learn this', 'read this document'."
    ),
    input_schema={"type": "object", "properties": {
        "target": {"type": "string", "description": "File path or reference (default: the active file)."},
    }},
)
def study_document(target: str = "it") -> str:
    from reyes_agent.study import get_study_engine
    path = _resolve(target)
    if not path:
        return _json({"ok": False, "error": f"couldn't resolve '{target}' to a file"})
    return _json(get_study_engine().study(path))


@register(
    name="study_ask",
    description=(
        "Retrieve the passages from studied material most relevant to a question, "
        "each with a source citation (file + page/chunk) and an honest confidence. "
        "This GROUNDS ZENO's answer -- answer from these passages and cite them; if "
        "grounded is false, say the studied material doesn't cover it rather than "
        "guessing. Optionally restrict to one source. Use for 'what does the "
        "document say about X', 'where did you get that', exam questions."
    ),
    input_schema={"type": "object", "properties": {
        "question": {"type": "string", "description": "The question to ground."},
        "source": {"type": "string", "description": "Optional: restrict to one studied file path."},
    }, "required": ["question"]},
    light=True,
)
def study_ask(question: str, source: str = "") -> str:
    from reyes_agent.study import get_study_engine
    src = _resolve(source) if source else ""
    result = get_study_engine().ask(question, source=src)
    return _json(result)


@register(
    name="study_status",
    description=(
        "List what ZENO has studied: each document, its passage/page count and "
        "when it was studied. Use for 'what have you learned?' / 'what's in your "
        "study memory?'."
    ),
    input_schema={"type": "object", "properties": {}},
    light=True,
)
def study_status() -> str:
    from reyes_agent.study import get_study_engine
    return _json(get_study_engine().catalog())


@register(
    name="study_forget",
    description=(
        "Remove a document from ZENO's study memory (e.g. 'forget this course', "
        "'don't keep that study session'). Reversible by studying it again."
    ),
    input_schema={"type": "object", "properties": {
        "target": {"type": "string", "description": "File path or reference to forget."},
    }, "required": ["target"]},
)
def study_forget(target: str) -> str:
    from reyes_agent.study import get_study_engine
    path = _resolve(target) or str(target)
    return _json(get_study_engine().forget(path))


@register(
    name="study_report",
    description=(
        "How much has been learned in a course: honest progress %, and how many "
        "topics are mastered / practiced / understood / still learning / need "
        "revision. Numbers come from tracked evidence, never invented. Use for "
        "'how much have I learned?' / 'what's my progress?'."
    ),
    input_schema={"type": "object", "properties": {
        "course": {"type": "string", "description": "Course name (default: general)."},
    }},
    light=True,
)
def study_report(course: str = "") -> str:
    from reyes_agent.study import get_mastery_tracker
    return _json(get_mastery_tracker().report(course=course))


@register(
    name="study_weak_areas",
    description=(
        "The topics the owner is weakest in (needs-revision first, then still-"
        "learning), so ZENO can target them. Use for 'what am I weak in?' / "
        "'test my weak areas'."
    ),
    input_schema={"type": "object", "properties": {
        "course": {"type": "string", "description": "Course name (default: general)."},
    }},
    light=True,
)
def study_weak_areas(course: str = "") -> str:
    from reyes_agent.study import get_mastery_tracker
    return _json({"ok": True, "weak": get_mastery_tracker().weak_topics(course=course)})


@register(
    name="study_mastery_update",
    description=(
        "Record real evidence of learning so mastery stays honest: event=introduce "
        "(first seen), studied (covered it), or answer (with correct true/false). "
        "Mastery is only reached after sustained correct answers across sessions, "
        "never one lucky answer. Call after teaching a topic or grading an answer."
    ),
    input_schema={"type": "object", "properties": {
        "topic": {"type": "string"},
        "event": {"type": "string", "enum": ["introduce", "studied", "answer"]},
        "correct": {"type": "boolean", "description": "for event=answer"},
        "course": {"type": "string"},
    }, "required": ["topic", "event"]},
)
def study_mastery_update(topic: str, event: str, correct: bool = False,
                         course: str = "") -> str:
    from reyes_agent.study import get_mastery_tracker
    m = get_mastery_tracker()
    ev = (event or "").strip().lower()
    if ev == "answer":
        return _json(m.answered(topic, correct=bool(correct), course=course))
    if ev == "studied":
        return _json(m.studied(topic, course=course))
    return _json(m.introduce(topic, course=course))


@register(
    name="quiz_generate",
    description=(
        "Generate quiz questions from studied material for active recall: cloze "
        "(fill-the-blank from a real passage, with citation), definition, and "
        "multiple-choice. Returns the questions AND their answers (so ZENO can "
        "grade). Present the questions to the owner one at a time, then grade "
        "each with quiz_evaluate. Use for 'quiz me', 'make 10 questions', 'test "
        "me on this'."
    ),
    input_schema={"type": "object", "properties": {
        "source": {"type": "string", "description": "Restrict to one studied file (optional)."},
        "course": {"type": "string", "description": "Course name for the concept graph (optional)."},
        "count": {"type": "integer", "description": "How many questions (default 5)."},
        "kinds": {"type": "string", "description": "Comma list of cloze,definition,mcq (default all)."},
    }},
)
def quiz_generate(source: str = "", course: str = "", count: int = 5,
                  kinds: str = "") -> str:
    from reyes_agent.study import get_quiz_engine
    src = _resolve(source) if source else ""
    kind_list = [k.strip() for k in kinds.split(",") if k.strip()] or None
    return _json(get_quiz_engine().generate(
        source=src, course=course, count=max(1, min(int(count or 5), 30)),
        kinds=kind_list))


@register(
    name="quiz_evaluate",
    description=(
        "Grade the owner's answer to a quiz question honestly -- says what was "
        "right and what was missing, not just 'correct' -- and records the result "
        "in the mastery model (one lucky answer is still not mastery). Pass the "
        "question's kind + expected answer (from quiz_generate) and the owner's "
        "answer."
    ),
    input_schema={"type": "object", "properties": {
        "kind": {"type": "string", "enum": ["cloze", "definition", "mcq", "short"]},
        "expected": {"type": "string", "description": "The correct answer from quiz_generate."},
        "user_answer": {"type": "string", "description": "What the owner answered."},
        "topic": {"type": "string", "description": "The question's topic (feeds mastery)."},
        "course": {"type": "string"},
        "options": {"type": "array", "items": {"type": "string"}, "description": "MCQ options (optional)."},
    }, "required": ["kind", "expected", "user_answer"]},
)
def quiz_evaluate(kind: str, expected: str, user_answer: str, topic: str = "",
                  course: str = "", options: list | None = None) -> str:
    from reyes_agent.study import get_quiz_engine
    return _json(get_quiz_engine().evaluate(
        kind=kind, expected=expected, user_answer=user_answer,
        options=options or [], topic=topic, course=course))


@register(
    name="concept_prerequisites",
    description=(
        "The prerequisite chain for a concept (what must be understood first), "
        "and which prerequisites the owner is MISSING given what they already "
        "know. Use before teaching an advanced topic so ZENO doesn't skip the "
        "foundations. Reads the concept graph built while studying."
    ),
    input_schema={"type": "object", "properties": {
        "concept": {"type": "string"},
        "known": {"type": "array", "items": {"type": "string"},
                  "description": "concepts the owner already knows (optional)."},
        "course": {"type": "string"},
    }, "required": ["concept"]},
    light=True,
)
def concept_prerequisites(concept: str, known: list | None = None,
                          course: str = "") -> str:
    from reyes_agent.study import get_concept_graph
    g = get_concept_graph()
    return _json({"ok": True, "concept": concept,
                  "prerequisites": g.prerequisites(concept, course=course),
                  "missing": g.missing_prerequisites(concept, known or [], course=course),
                  "relations": g.relations_of(concept, course=course)})
