"""How to explain the same thing to different audiences (pack6 #36-45).

Turns an audience knowledge level + an explicit detail request into a concrete
explanation STRATEGY (directives a prompt can follow). Knowledge level is only
ever a working conversational estimate from evidence -- never a judgement about
the person (pack6 #37).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Knowledge levels (pack6 #37).
BEGINNER = "BEGINNER"
FAMILIAR = "FAMILIAR"
INTERMEDIATE = "INTERMEDIATE"
ADVANCED = "ADVANCED"
EXPERT = "EXPERT"
UNKNOWN = "UNKNOWN"

# Detail requests (pack6 #44).
_DETAIL = {"brief": "brief", "briefly": "brief", "short": "brief", "summary": "brief",
           "normal": "normal", "full": "full", "fully": "full", "detailed": "full",
           "deeper": "deeper", "deep": "deeper", "simpler": "simpler",
           "simple": "simpler", "technical": "technical"}


@dataclass
class ExplanationStrategy:
    level: str
    detail: str
    use_jargon: bool
    use_analogy: bool
    use_examples: bool
    structure: tuple[str, ...]
    directives: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {"level": self.level, "detail": self.detail,
                "use_jargon": self.use_jargon, "use_analogy": self.use_analogy,
                "use_examples": self.use_examples, "structure": list(self.structure),
                "directives": list(self.directives)}


# Per audience level: (jargon, analogy, examples, structure, directives)
_BY_LEVEL = {
    BEGINNER: (False, True, True,
               ("plain overview", "analogy", "concrete example"),
               ("Use plain language and minimal jargon.",
                "Lead with an analogy, then one concrete example.")),
    FAMILIAR: (False, True, True,
               ("recap", "key points", "example"),
               ("Assume the basics; define only new terms.")),
    INTERMEDIATE: (True, False, True,
                   ("key points", "example", "caveats"),
                   ("Use correct terminology; keep it efficient.")),
    ADVANCED: (True, False, True,
               ("mechanism", "tradeoffs", "edge cases"),
               ("Be precise and technical; state tradeoffs.")),
    EXPERT: (True, False, False,
             ("architecture", "tradeoffs", "implementation"),
             ("Technical vocabulary, architecture and implementation detail; skip basics.")),
    UNKNOWN: (False, True, True,
              ("short overview", "offer to go deeper"),
              ("Give a short neutral overview, then offer a simple or technical version.")),
}

# Executive framing (pack6 #41) is a purpose, applied on top of the level.
_EXECUTIVE_STRUCTURE = ("what it is", "why it matters", "risk", "impact", "next step")
_LECTURER_STRUCTURE = ("problem", "architecture", "method", "implementation",
                       "limitations", "evaluation")


class ExplanationAdapter:
    def normalise_detail(self, detail: str) -> str:
        return _DETAIL.get(str(detail or "").strip().casefold(), "normal")

    def strategy(self, audience_level: str = UNKNOWN, *, detail: str = "normal",
                 purpose: str = "") -> ExplanationStrategy:
        level = str(audience_level or UNKNOWN).strip().upper()
        if level not in _BY_LEVEL:
            level = UNKNOWN
        det = self.normalise_detail(detail)
        jargon, analogy, examples, structure, directives = _BY_LEVEL[level]
        directives = list(directives)

        purpose_l = str(purpose or "").strip().casefold()
        if purpose_l in {"executive", "manager", "official"}:
            structure = _EXECUTIVE_STRUCTURE
            directives.append("Answer first, then detail on request.")
        elif purpose_l in {"lecturer", "academic", "class"}:
            structure = _LECTURER_STRUCTURE

        # Detail request modulates depth/simplicity (pack6 #44-45).
        if det == "brief":
            directives.append("Keep it to a couple of sentences.")
        elif det in {"full", "deeper"}:
            directives.append("Go into depth; include mechanism and examples.")
            examples = True
        if det == "simpler":
            jargon, analogy, examples = False, True, True
            directives.append("Re-explain more simply; change the approach, do not repeat.")
        elif det == "technical":
            jargon = True
            directives.append("Use the technical version with implementation detail.")

        return ExplanationStrategy(level, det, jargon, analogy, examples,
                                   tuple(structure), tuple(directives))
