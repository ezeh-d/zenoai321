"""Deterministic candidate scoring, safety filtering, and ranking."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from reyes_agent.charm.models import (
    CandidateScores,
    CharmCandidate,
    CharmMode,
    CharmRequest,
    ContextSignals,
    Recommendation,
)
from reyes_agent.charm.styles import get_style


_PLEADING_RE = re.compile(
    r"\b(?:please\s+please|i beg|don'?t ignore me|need you|give me (?:one|another) chance|"
    r"why (?:won't|don'?t) you reply|answer me|i can'?t live without you)\b",
    re.IGNORECASE,
)
_PRESSURE_RE = re.compile(
    r"\b(?:you owe me|must reply|have to reply|just say yes|won'?t take no|"
    r"keep asking|keep (?:texting|messaging|calling)|until you say yes|"
    r"prove (?:you|that)|if you (?:cared|loved me)|after all i did)\b",
    re.IGNORECASE,
)
_OVERCLAIM_RE = re.compile(
    r"\b(?:love of my life|perfect (?:girl|woman|man|goddess|angel)|soulmate|"
    r"forever yours|all i need|meant to be together)\b",
    re.IGNORECASE,
)
_WARM_RE = re.compile(
    r"\b(?:glad|happy|nice|love|enjoy|proud|good|great|sounds|tell me|hope)\b|[😊😄❤❤️]",
    re.IGNORECASE,
)
_HUMOR_RE = re.compile(r"\b(?:lol|haha+|joke|plot twist|😂|🤣)\b|[😂🤣😄]", re.IGNORECASE)
_FLIRT_RE = re.compile(
    r"\b(?:cute|beautiful|handsome|attractive|date|chemistry|miss you|thinking of you)\b|[😉😍🥰]",
    re.IGNORECASE,
)


def _clamp(value: float | int) -> int:
    return max(0, min(100, round(float(value))))


def _digest(text: str) -> str:
    normalized = " ".join(str(text or "").casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _conversation_terms(request: CharmRequest) -> set[str]:
    text = " ".join(request.conversation).casefold()
    return {
        word for word in re.findall(r"[\w']+", text)
        if len(word) >= 4 and word not in {"them", "that", "this", "with", "have", "your", "what"}
    }


def score_candidate(
    text: str,
    request: CharmRequest,
    signals: ContextSignals,
    recent_hashes: Iterable[str] = (),
) -> CandidateScores:
    clean = " ".join(str(text or "").split())
    lower = clean.casefold()
    words = re.findall(r"[\w']+", lower)
    word_count = len(words)
    exclamations = clean.count("!")
    questions = clean.count("?")
    emoji_count = len(re.findall(r"[^\x00-\x7F]", clean))
    repeated_punctuation = bool(re.search(r"([!?])\1{2,}", clean))

    pleading = bool(_PLEADING_RE.search(clean))
    pressure_phrase = bool(_PRESSURE_RE.search(clean))
    overclaim = bool(_OVERCLAIM_RE.search(clean))
    conversation_terms = _conversation_terms(request)
    candidate_terms = set(words)
    overlap = len(conversation_terms & candidate_terms)
    context_relevance = _clamp(38 + min(42, overlap * 12) + (10 if questions else 0))

    desperation = _clamp(
        (75 if pleading else 0)
        + (25 if overclaim and not request.relationship else 0)
        + max(0, exclamations - 2) * 8
    )
    pressure = _clamp(
        (82 if pressure_phrase else 0)
        + (65 if pleading else 0)
        + (25 if signals.recommendation in {Recommendation.PULL_BACK, Recommendation.ABORT} else 0)
    )
    cringe = _clamp(
        (58 if overclaim else 0)
        + (30 if repeated_punctuation else 0)
        + max(0, emoji_count - 2) * 9
        + (20 if word_count > 50 else 0)
    )
    repetition = 100 if _digest(clean) in set(recent_hashes) else 0

    naturalness = _clamp(
        82
        - (35 if repeated_punctuation else 0)
        - max(0, emoji_count - 2) * 7
        - (35 if overclaim else 0)
        - (30 if pleading else 0)
        - (18 if word_count > 45 or word_count < 2 else 0)
    )
    warmth = _clamp(40 + (28 if _WARM_RE.search(clean) else 0) + min(18, signals.engagement / 5))
    humor = _clamp(12 + (58 if _HUMOR_RE.search(clean) else 0))
    flirt = _clamp(10 + (58 if _FLIRT_RE.search(clean) else 0) + (15 if request.mode in {CharmMode.FLIRTY, CharmMode.ROMANTIC, CharmMode.CHEEKY} else 0))
    confidence = _clamp(
        72
        - (35 if pleading else 0)
        - (25 if pressure_phrase else 0)
        - (12 if clean.endswith("...") else 0)
    )

    profile = get_style(request.mode)
    mode_fit = _clamp(
        100
        - abs(warmth - profile.warmth) * 0.35
        - abs(humor - profile.humor) * 0.25
        - abs(flirt - profile.flirt) * 0.30
    )
    rank = _clamp(
        naturalness * 0.24
        + context_relevance * 0.24
        + confidence * 0.14
        + warmth * 0.10
        + mode_fit * 0.14
        - pressure * 0.12
        - desperation * 0.13
        - cringe * 0.10
        - repetition * 0.16
    )
    return CandidateScores(
        naturalness=naturalness,
        context_relevance=context_relevance,
        confidence=confidence,
        warmth=warmth,
        humor=humor,
        flirt_level=flirt,
        pressure_level=pressure,
        desperation_risk=desperation,
        cringe_risk=cringe,
        repetition_risk=repetition,
        rank_score=rank,
    )


def rank_candidates(
    texts: Iterable[str],
    request: CharmRequest,
    signals: ContextSignals,
    recent_hashes: Iterable[str] = (),
) -> tuple[CharmCandidate, ...]:
    ranked: list[CharmCandidate] = []
    seen: set[str] = set()
    recent = tuple(recent_hashes)
    unsafe_context = signals.recommendation in {
        Recommendation.PULL_BACK,
        Recommendation.ABORT,
    }
    for raw in texts:
        clean = " ".join(str(raw or "").split())[:1000]
        digest = _digest(clean)
        if not clean or digest in seen:
            continue
        seen.add(digest)
        scores = score_candidate(clean, request, signals, recent)
        reasons: list[str] = []
        if unsafe_context:
            reasons.append("Back-off context makes escalation inappropriate.")
        if scores.pressure_level >= 60:
            reasons.append("Pressure is too high.")
        if scores.desperation_risk >= 70:
            reasons.append("Desperation risk is too high.")
        if scores.cringe_risk >= 85:
            reasons.append("Cringe risk is too high.")
        if scores.repetition_risk >= 100:
            reasons.append("This repeats a recent suggestion.")
        eligible = not reasons
        ranked.append(
            CharmCandidate(
                id=f"charm_{digest[:16]}",
                text=clean,
                scores=scores,
                eligible=eligible,
                reasons=tuple(reasons),
            )
        )
    ranked.sort(key=lambda item: (item.eligible, item.scores.rank_score), reverse=True)
    return tuple(ranked)
