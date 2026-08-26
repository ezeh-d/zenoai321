"""Stable data contracts for ZENO's native Charm Engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class CharmMode(StrEnum):
    NATURAL = "Natural"
    SMOOTH = "Smooth"
    SWEET = "Sweet"
    FLIRTY = "Flirty"
    PLAYFUL = "Playful"
    FUNNY = "Funny"
    WITTY = "Witty"
    ROMANTIC = "Romantic"
    CONFIDENT = "Confident"
    GENTLEMAN = "Gentleman"
    CHEEKY = "Cheeky"
    DEEP = "Deep"
    SERIOUS = "Serious"
    PIDGIN_SMOOTH = "Pidgin Smooth"

    @classmethod
    def parse(cls, value: "CharmMode | str") -> "CharmMode":
        if isinstance(value, cls):
            return value
        normalized = " ".join(str(value or "").casefold().replace("_", " ").split())
        for item in cls:
            if item.value.casefold() == normalized or item.name.casefold().replace("_", " ") == normalized:
                return item
        raise ValueError(f"Unknown Charm mode '{value}'.")


class CharmFeature(StrEnum):
    REPLY = "reply"
    OPENER = "opener"
    COMPLIMENT = "compliment"
    HUMOR = "humor"
    STORYTELLING = "storytelling"
    RECOVERY = "recovery"
    AFTER_SEND = "after_send"
    SIMULATOR = "simulator"
    VOICE_COACH = "voice_coach"

    @classmethod
    def parse(cls, value: "CharmFeature | str") -> "CharmFeature":
        if isinstance(value, cls):
            return value
        normalized = "_".join(str(value or "reply").casefold().replace("-", " ").split())
        for item in cls:
            if item.value == normalized:
                return item
        raise ValueError(f"Unknown Charm feature '{value}'.")


class Recommendation(StrEnum):
    CONTINUE = "CONTINUE"
    WAIT = "WAIT"
    MATCH = "MATCH"
    PULL_BACK = "PULL_BACK"
    ABORT = "ABORT"


@dataclass(frozen=True)
class ContextSignals:
    recommendation: Recommendation = Recommendation.CONTINUE
    tone: str = "neutral"
    reciprocity: int = 50
    momentum: int = 50
    engagement: int = 50
    dry_reply_ratio: float = 0.0
    unanswered_streak: int = 0
    message_balance: float = 1.0
    stop_requested: bool = False
    discomfort_detected: bool = False
    repeated_rejection: bool = False
    confidence: float = 0.5
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["recommendation"] = self.recommendation.value
        return value


@dataclass(frozen=True)
class CandidateScores:
    naturalness: int
    context_relevance: int
    confidence: int
    warmth: int
    humor: int
    flirt_level: int
    pressure_level: int
    desperation_risk: int
    cringe_risk: int
    repetition_risk: int
    rank_score: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class CharmCandidate:
    id: str
    text: str
    scores: CandidateScores
    rationale: str = ""
    eligible: bool = True
    reasons: tuple[str, ...] = ()

    def as_dict(self, *, include_scores: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "text": self.text,
            "rationale": self.rationale,
            "eligible": self.eligible,
            "reasons": list(self.reasons),
        }
        if include_scores:
            out["scores"] = self.scores.as_dict()
        return out


@dataclass(frozen=True)
class CharmRequest:
    instruction: str
    conversation: tuple[str, ...] | list[str] = ()
    mode: CharmMode | str = CharmMode.NATURAL
    feature: CharmFeature | str = CharmFeature.REPLY
    count: int = 3
    intensity: int = 50
    relationship: str = ""
    objective: str = ""
    include_scores: bool = True
    session_id: str = "default"

    def __post_init__(self) -> None:
        instruction = " ".join(str(self.instruction or "").split())[:1000]
        conversation = tuple(str(item)[:2000] for item in self.conversation)[-20:]
        object.__setattr__(self, "instruction", instruction)
        object.__setattr__(self, "conversation", conversation)
        object.__setattr__(self, "mode", CharmMode.parse(self.mode))
        object.__setattr__(self, "feature", CharmFeature.parse(self.feature))
        try:
            count = int(self.count)
        except (TypeError, ValueError):
            count = 3
        try:
            intensity = int(self.intensity)
        except (TypeError, ValueError):
            intensity = 50
        object.__setattr__(self, "count", max(1, min(5, count)))
        object.__setattr__(self, "intensity", max(0, min(100, intensity)))
        object.__setattr__(self, "relationship", " ".join(str(self.relationship or "").split())[:500])
        object.__setattr__(self, "objective", " ".join(str(self.objective or "").split())[:500])
        object.__setattr__(self, "session_id", str(self.session_id or "default")[:80])


@dataclass(frozen=True)
class CharmResult:
    request: CharmRequest
    signals: ContextSignals
    candidates: tuple[CharmCandidate, ...] = ()
    best: CharmCandidate | None = None
    warning: str = ""
    error: str = ""
    generated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.request.mode.value,
            "feature": self.request.feature.value,
            "intensity": self.request.intensity,
            "recommendation": self.signals.recommendation.value,
            "signals": self.signals.as_dict(),
            "candidates": [
                item.as_dict(include_scores=self.request.include_scores)
                for item in self.candidates
            ],
            "best": (
                self.best.as_dict(include_scores=self.request.include_scores)
                if self.best else None
            ),
            "warning": self.warning,
            "error": self.error,
            "generated": self.generated,
        }


@dataclass(frozen=True)
class StyleProfile:
    mode: CharmMode
    guidance: str
    warmth: int
    humor: int
    flirt: int
    directness: int
    constraints: tuple[str, ...] = field(default_factory=tuple)
