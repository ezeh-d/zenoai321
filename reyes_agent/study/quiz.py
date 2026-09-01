"""Quiz generator + answer evaluator (#21, #24, #25) -- active recall.

Generates questions FROM studied material and the concept graph, deterministically
(so it works offline and is testable): cloze (fill-the-blank from a real passage),
definition, and multiple-choice. A model generator can be injected for richer
questions, but the deterministic path is the floor, not a stub.

Evaluation is honest: it never just says "Correct." It scores, says what was
right and what was missing, and feeds the mastery model with real evidence
(so one lucky answer is still not mastery). MCQ/cloze are graded
deterministically; free-text uses keyword overlap unless a model evaluator is
injected.

Reuses: study index (passages + citations), concept graph, mastery tracker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

EASY, MEDIUM, HARD, VERY_HARD = "EASY", "MEDIUM", "HARD", "VERY_HARD"
CLOZE, DEFINITION, MCQ, SHORT = "cloze", "definition", "mcq", "short"

_STOP = {"the", "a", "an", "of", "to", "in", "and", "or", "is", "are", "was",
         "for", "on", "with", "as", "by", "that", "this", "it", "be", "which",
         "from", "at", "into", "than", "then", "these", "those", "can", "will"}


@dataclass
class Question:
    qid: str
    kind: str
    prompt: str
    answer: str
    options: list[str] = field(default_factory=list)
    topic: str = ""
    difficulty: str = MEDIUM
    citation: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        d = {"qid": self.qid, "kind": self.kind, "prompt": self.prompt,
             "topic": self.topic, "difficulty": self.difficulty,
             "citation": self.citation}
        if self.options:
            d["options"] = self.options
        return d


@dataclass
class Verdict:
    correct: bool
    score: float
    feedback: str
    expected: str
    missing: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"correct": self.correct, "score": round(self.score, 2),
                "feedback": self.feedback, "expected": self.expected,
                "missing": self.missing}


def _norm(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(s).lower()))


def _keywords(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", str(s).lower()) if w not in _STOP}


def _salient_term(text: str, concepts: list[str]) -> str:
    """A term worth blanking: a known concept present in the text, else the
    longest non-stopword token."""
    low = text.lower()
    for c in sorted(concepts, key=len, reverse=True):
        if c and c.lower() in low and len(c) >= 4:
            return c
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9\-]{3,}", text)
             if w.lower() not in _STOP]
    return max(words, key=len) if words else ""


class QuizEngine:
    def __init__(self, *, generate: Callable[..., list] | None = None,
                 evaluate: Callable[..., dict] | None = None) -> None:
        self._gen = generate      # optional model question generator
        self._eval = evaluate     # optional model free-text evaluator

    # -- generation --------------------------------------------------------
    def generate(self, *, source: str = "", course: str = "", count: int = 5,
                 difficulty: str = MEDIUM, kinds: list[str] | None = None,
                 chunks: list[dict] | None = None,
                 concepts: list[dict] | None = None) -> dict[str, Any]:
        """Build up to `count` questions from studied material. `chunks` and
        `concepts` can be injected (tests); otherwise they're pulled from the
        study index and concept graph."""
        try:
            if chunks is None:
                from reyes_agent.study import get_study_engine
                chunks = get_study_engine().sample_chunks(source=source, limit=40)
            if concepts is None:
                from reyes_agent.study import get_concept_graph
                g = get_concept_graph().summary(course=course)
                concepts = [{"name": n} for n in g.get("names", [])]
            names = [c.get("name", "") for c in (concepts or []) if c.get("name")]

            if not chunks and not names:
                return {"ok": False, "error": "nothing studied to quiz on yet",
                        "questions": []}

            want = set(kinds or [CLOZE, DEFINITION, MCQ])
            out: list[Question] = []
            n = 0

            # definition / MCQ from concepts
            for name in names:
                if len(out) >= count:
                    break
                if MCQ in want and len(names) >= 4:
                    distract = [x for x in names if x != name][:3]
                    opts = sorted({name, *distract}, key=lambda s: _norm(s))
                    out.append(Question(f"q{n}", MCQ,
                                        f"Which of these is: '{name}'?",
                                        name, options=opts, topic=name,
                                        difficulty=difficulty)); n += 1
                elif DEFINITION in want:
                    out.append(Question(f"q{n}", DEFINITION,
                                        f"In your own words, what is {name}?",
                                        name, topic=name, difficulty=difficulty)); n += 1

            # cloze from real passages (with citation)
            if CLOZE in want:
                for ch in chunks:
                    if len(out) >= count:
                        break
                    term = _salient_term(ch["text"], names)
                    if not term:
                        continue
                    sentence = _first_sentence_with(ch["text"], term)
                    if not sentence:
                        continue
                    blanked = re.sub(re.escape(term), "_____", sentence, count=1,
                                     flags=re.I)
                    out.append(Question(
                        f"q{n}", CLOZE, f"Fill in the blank: {blanked.strip()}",
                        term, topic=term, difficulty=difficulty,
                        citation={"source": ch.get("source", ""),
                                  "page": ch.get("page")})); n += 1

            # optional model enrichment
            if self._gen and len(out) < count:
                try:
                    extra = self._gen(chunks=chunks, concepts=names,
                                      count=count - len(out), difficulty=difficulty)
                    for q in extra or []:
                        out.append(Question(f"q{n}", q.get("kind", SHORT),
                                            q["prompt"], q.get("answer", ""),
                                            options=q.get("options", []),
                                            topic=q.get("topic", ""),
                                            difficulty=difficulty)); n += 1
                except Exception:  # noqa: BLE001
                    pass

            return {"ok": bool(out), "count": len(out),
                    "questions": [q.as_dict() for q in out[:count]],
                    "_answers": {q.qid: {"kind": q.kind, "answer": q.answer,
                                         "topic": q.topic, "options": q.options}
                                 for q in out[:count]}}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200],
                    "questions": []}

    # -- evaluation --------------------------------------------------------
    def evaluate(self, *, kind: str, expected: str, user_answer: str,
                 options: list[str] | None = None, topic: str = "",
                 course: str = "", record: bool = True) -> dict[str, Any]:
        """Grade an answer honestly and (by default) feed the mastery model."""
        ua = str(user_answer or "").strip()
        verdict = self._grade(kind, expected, ua, options or [])
        if record and topic:
            try:
                from reyes_agent.study import get_mastery_tracker
                get_mastery_tracker().answered(topic, correct=verdict.correct,
                                               course=course)
            except Exception:  # noqa: BLE001
                pass
        return {"ok": True, **verdict.as_dict(), "topic": topic}

    def _grade(self, kind: str, expected: str, ua: str,
               options: list[str]) -> Verdict:
        if not ua:
            return Verdict(False, 0.0, "No answer given.", expected)
        if kind == MCQ:
            correct = _norm(ua) == _norm(expected) or (
                ua.strip() in options and _norm(ua) == _norm(expected))
            return Verdict(correct, 1.0 if correct else 0.0,
                           "Correct." if correct else f"Not quite -- it's '{expected}'.",
                           expected)
        if kind in (CLOZE, DEFINITION, SHORT):
            # exact/contained term -> correct; else keyword overlap -> partial
            exp_norm, ua_norm = _norm(expected), _norm(ua)
            if exp_norm and (exp_norm == ua_norm or exp_norm in ua_norm):
                return Verdict(True, 1.0, "Correct.", expected)
            if self._eval and kind in (DEFINITION, SHORT):
                try:
                    r = self._eval(expected=expected, answer=ua)
                    return Verdict(bool(r.get("correct")), float(r.get("score", 0)),
                                   str(r.get("feedback", "")), expected,
                                   list(r.get("missing", [])))
                except Exception:  # noqa: BLE001
                    pass
            exp_k, ua_k = _keywords(expected), _keywords(ua)
            overlap = (len(exp_k & ua_k) / len(exp_k)) if exp_k else 0.0
            missing = sorted(exp_k - ua_k)[:6]
            if overlap >= 0.6:
                return Verdict(True, overlap, "Right idea.", expected, missing)
            if overlap > 0:
                return Verdict(False, overlap,
                               f"Partly there -- you're missing: {', '.join(missing)}.",
                               expected, missing)
            return Verdict(False, 0.0, f"Not quite. Expected around: {expected}.",
                           expected, missing)
        return Verdict(False, 0.0, "Unscorable question type.", expected)


def _first_sentence_with(text: str, term: str) -> str:
    for sent in re.split(r"(?<=[.!?])\s+", str(text)):
        if term.lower() in sent.lower() and 12 <= len(sent) <= 240:
            return sent
    return ""


_engine: QuizEngine | None = None


def get_quiz_engine() -> QuizEngine:
    global _engine
    if _engine is None:
        _engine = QuizEngine()
    return _engine
