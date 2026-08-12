"""Knowing which questions are not ZENO's to answer.

THE FAILURE THIS PREVENTS IS THE WORST ONE AVAILABLE
-----------------------------------------------------
A supervisor asks "what did you find hardest?" and an assistant answers
fluently -- inventing a feeling on behalf of a student sitting right there.
Everything else in the room becomes suspect at that moment, because the one
claim the supervisor could check against the person in front of him was
false.

ZENO cannot know what Divine found hard. It can know what BROKE, and when,
and how it was fixed -- that is in the repository. It cannot know how that
felt, what he was worried about, why he chose this over something else, or
what he would do differently. Those belong to Divine.

WHERE THE LINE SITS
-------------------
    "DO NOT OVERUSE HUMAN HANDOFF."

Equally real. An assistant that defers everything is useless, and a
supervisor learns nothing from watching a student answer questions his own
software should answer. Architecture, feature status, verified history and
general programming are ZENO's to explain, and it should explain them
confidently.

The test is not "is this about Divine" -- almost everything is. It is: does
answering require access to Divine's INTERIOR? If yes, hand over. If the
answer is in the code, the commits or the measurements, answer it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Interior: feelings, opinions, motives, counterfactuals. ZENO has no access.
_PERSONAL = (
    r"\bhow (?:did|does) (?:he|divine) feel\b",
    # Up to two words may sit between the subject and the verb -- "Divine
    # PERSONALLY find", "he ACTUALLY found". Without that slack this missed
    # the most obvious question a supervisor asks.
    r"\b(?:he|divine)\s+(?:\w+\s+){0,2}(?:find|finds|found)\s+(?:\w+\s+){0,2}"
    r"(?:hard|hardest|difficult|easy|easiest|challenging|frustrating)\b",
    r"\bwhat\b.*\b(?:he|divine)\b.*\b(?:personally|himself)\b",
    r"\bhardest (?:part|thing|bit)\b",
    r"\bmost difficult\b",
    r"\bwas it (?:hard|difficult|easy|stressful|fun)\b",
    r"\bdid (?:he|you) enjoy\b",
    r"\bwhy did (?:he|divine) (?:choose|decide|pick|want)\b",
    r"\bwhat (?:motivated|inspired) (?:him|divine)\b",
    r"\bwould (?:he|divine) do .* differently\b",
    r"\bwhat (?:did|has) (?:he|divine) learn(?:ed)? (?:about himself|personally)\b",
    r"\bhis (?:opinion|view|feeling|experience|plan|ambition)\b",
    r"\bhow (?:is|was) (?:he|divine) (?:finding|coping|managing)\b",
    r"\bwhat does (?:he|divine) (?:think|want|hope)\b",
    r"\b(?:proud|frustrat|worried|nervous|confiden)\w*\b",
    # Order-independent: "what does he plan to do after graduation" puts the
    # verb BEFORE the milestone, which the original pattern could not see.
    r"\b(?:plan|plans|hope|hopes|want|wants|intend)\w*\b.*\b(?:after|next|future|graduation)\b",
    r"\b(?:after|once)\b.*\b(?:graduat|school|siwes|placement)\w*\b",
    r"\bcourse\b.*\b(?:like|enjoy|experience)\b",
)

# ZENO's own ground: verifiable from the project. Checked FIRST, because
# "what was the hardest bug" is a question the repository can answer.
_TECHNICAL = (
    r"\barchitecture\b", r"\bhow do(?:es)? (?:it|you|zeno) work\b",
    r"\bwhat (?:is|are) (?:zeno|the agents?|the stack)\b",
    r"\bwhich (?:features?|parts?) (?:work|are working)\b",
    r"\bfeature status\b", r"\bwhat.*implemented\b",
    r"\bshow me the code\b", r"\bhow many\b", r"\bwhat language\b",
    r"\bwhat (?:library|libraries|framework|model|api)\b",
    r"\bhow does .* (?:memory|agent|voice|wake|phone) work\b",
    r"\bwhat (?:bug|problem|issue)s? (?:were|was|did).*(?:fixed|solved)\b",
)

_PERSONAL_RE = [re.compile(p, re.I) for p in _PERSONAL]
_TECHNICAL_RE = [re.compile(p, re.I) for p in _TECHNICAL]

# Varied, so a visit with several personal questions does not sound stuck.
_LINES = (
    "That's one I'd let Divine answer -- he was the one working through it.",
    "Divine would explain that part better than I can, sir.",
    "I can tell you what broke and when. How he found it is his to say.",
    "That's really a question for Divine.",
)


@dataclass
class Handoff:
    hand_over: bool
    reason: str
    say: str = ""
    confidence: str = "clear"

    def as_dict(self) -> dict[str, Any]:
        return {"hand_over": self.hand_over, "reason": self.reason,
                "say": self.say, "confidence": self.confidence,
                "ui": "HANDOFF -> DIVINE" if self.hand_over else ""}


def consider(question: str) -> Handoff:
    """Should Divine answer this instead."""
    text = (question or "").strip()
    if not text:
        return Handoff(False, "nothing was asked")

    # Technical first: the repository can answer "what was the hardest bug",
    # and deferring that would be the overuse the brief warns about.
    for pattern in _TECHNICAL_RE:
        if pattern.search(text):
            return Handoff(False, "answerable from the project record")

    for index, pattern in enumerate(_PERSONAL_RE):
        if pattern.search(text):
            return Handoff(True,
                           "asks for Divine's own experience, opinion or motive",
                           _LINES[index % len(_LINES)])
    return Handoff(False, "no personal-experience marker found")


def took_over() -> dict[str, Any]:
    """Divine said 'ZENO, take over'. Resume normally."""
    return {"handed_back": True,
            "say": "", "note": "Resume answering; do not re-introduce yourself."}


def status() -> dict[str, Any]:
    return {
        "state": "ONLINE",
        "personal_markers": len(_PERSONAL_RE),
        "technical_overrides": len(_TECHNICAL_RE),
        "rule": ("The test is not whether a question is ABOUT Divine -- almost "
                 "all of them are. It is whether answering needs access to his "
                 "interior. Feelings, motives and counterfactuals are his; "
                 "code, commits and measurements are ZENO's."),
    }
