"""Lightweight context, reciprocity, momentum, and back-off analysis."""

from __future__ import annotations

import re
from dataclasses import replace

from reyes_agent.charm.models import ContextSignals, Recommendation


_ME = frozenset({"me", "i", "divine", "user", "owner", "you", "zeno"})
_THEM = frozenset({"them", "her", "him", "they", "other", "person"})
_STOP_RE = re.compile(
    r"\b(?:stop (?:messaging|texting|contacting|calling)? ?me|leave me alone|"
    r"do not contact me|don'?t contact me|never message me again|not interested)\b|"
    r"\b(?:do not|don'?t|never) (?:text|message|call) me(?: again)?\b",
    re.IGNORECASE,
)
_DISCOMFORT_RE = re.compile(
    r"\b(?:uncomfortable|creep(?:y|ing)|too much|back off|crossing (?:a )?line|"
    r"making me uneasy|i don'?t like this)\b",
    re.IGNORECASE,
)
_REJECTION_RE = re.compile(
    r"^(?:no|nah|nope)\b|\bi said no\b|\bnot interested\b|\bplease don'?t\b",
    re.IGNORECASE,
)
_POSITIVE_RE = re.compile(
    r"\b(?:great|good|well|love|lovely|enjoy|enjoyed|happy|glad|nice|amazing|"
    r"smile|laugh|fun|alright|fine o)\b|[😂😄😊🥰❤❤️]",
    re.IGNORECASE,
)
_PLAYFUL_RE = re.compile(r"\b(?:lol|lmao|haha+|hehe+|joke|tease)\b|[😂🤣😜]", re.IGNORECASE)
_NEGATIVE_RE = re.compile(r"\b(?:angry|upset|annoyed|sad|bad|tired|frustrated)\b", re.IGNORECASE)


def _clamp(value: float | int) -> int:
    return max(0, min(100, round(float(value))))


def _parse(messages: list[str] | tuple[str, ...]) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    normalized = [
        " ".join(str(raw or "").split())
        for raw in tuple(messages)[-20:]
        if " ".join(str(raw or "").split())
    ]
    # A reply-coaching transcript normally ends with the other person's
    # message. Starting according to parity preserves alternating unlabeled
    # transcripts and makes a single ambiguous message fail safe as incoming.
    fallback = "them" if len(normalized) % 2 else "me"
    for text in normalized:
        label = ""
        content = text
        if ":" in text:
            prefix, remainder = text.split(":", 1)
            prefix_label = prefix.strip().casefold()
            if prefix_label in _ME:
                label, content = "me", remainder.strip()
            elif prefix_label in _THEM:
                label, content = "them", remainder.strip()
            elif remainder.strip() and re.search(r"[a-z]", prefix_label, re.I):
                # A named participant ("Jane:", "Alex:") is the other
                # speaker unless explicitly recognized as the owner above.
                label, content = "them", remainder.strip()
        if not label:
            label = fallback
            fallback = "them" if fallback == "me" else "me"
        else:
            fallback = "them" if label == "me" else "me"
        parsed.append((label, content))
    return parsed


def _is_dry(text: str) -> bool:
    words = re.findall(r"[\w']+", text.casefold())
    expressive = bool(re.search(r"[!?😂🤣😄😊🥰❤❤️]", text))
    return len(words) <= 2 and not expressive


def analyze_conversation(
    messages: list[str] | tuple[str, ...], relationship: str = ""
) -> ContextSignals:
    parsed = _parse(messages)
    if not parsed:
        return ContextSignals(
            recommendation=Recommendation.MATCH,
            confidence=0.2,
            reasons=("No conversation context was supplied.",),
        )

    mine = [text for speaker, text in parsed if speaker == "me"]
    theirs = [text for speaker, text in parsed if speaker == "them"]
    dry_count = sum(_is_dry(text) for text in theirs)
    dry_ratio = dry_count / len(theirs) if theirs else 0.0

    unanswered = 0
    for speaker, _text in reversed(parsed):
        if speaker != "me":
            break
        unanswered += 1

    their_blob = " ".join(theirs)
    stop_requested = bool(_STOP_RE.search(their_blob))
    discomfort = bool(_DISCOMFORT_RE.search(their_blob))
    rejections = sum(bool(_REJECTION_RE.search(text.strip())) for text in theirs)
    repeated_rejection = rejections >= 2

    me_count, them_count = len(mine), len(theirs)
    balance = (
        min(me_count, them_count) / max(me_count, them_count)
        if me_count and them_count else 0.0
    )
    their_questions = sum("?" in text or re.search(r"\b(?:you nko|what about you)\b", text, re.I) is not None for text in theirs)
    average_their_words = (
        sum(len(re.findall(r"[\w']+", text)) for text in theirs) / len(theirs)
        if theirs else 0.0
    )
    reciprocity = _clamp(balance * 70 + min(15, their_questions * 10) + (15 if average_their_words >= 5 else 0))
    momentum = _clamp(
        48 + (18 if average_their_words >= 5 else 0) + min(15, their_questions * 8)
        - dry_ratio * 42 - max(0, unanswered - 1) * 18
    )
    engagement = _clamp(
        (reciprocity + momentum) / 2 + (10 if _POSITIVE_RE.search(their_blob) else 0)
        - dry_ratio * 25 - max(0, unanswered - 1) * 12
    )

    if _PLAYFUL_RE.search(their_blob):
        tone = "playful"
    elif _POSITIVE_RE.search(their_blob):
        tone = "positive" if engagement >= 65 else "warm"
    elif _NEGATIVE_RE.search(their_blob):
        tone = "negative"
    elif dry_ratio >= 0.66:
        tone = "dry"
    else:
        tone = "neutral"

    reasons: list[str] = []
    if stop_requested:
        recommendation = Recommendation.ABORT
        reasons.append("The other person explicitly asked for contact to stop.")
    elif repeated_rejection:
        recommendation = Recommendation.ABORT
        reasons.append("The conversation contains repeated rejection.")
    elif discomfort:
        recommendation = Recommendation.PULL_BACK
        reasons.append("The other person expressed discomfort.")
    elif rejections:
        recommendation = Recommendation.PULL_BACK
        reasons.append("The other person declined; do not escalate.")
    elif unanswered >= 2:
        recommendation = Recommendation.WAIT
        reasons.append(f"There are {unanswered} consecutive owner messages without a reply.")
    elif dry_ratio >= 0.66 and len(theirs) >= 2:
        recommendation = Recommendation.MATCH
        reasons.append("Recent replies are consistently brief; match the energy or pause.")
    elif engagement < 30 and len(parsed) >= 3:
        recommendation = Recommendation.PULL_BACK
        reasons.append("Observed engagement is low.")
    else:
        recommendation = Recommendation.CONTINUE
        reasons.append("The exchange shows enough reciprocity to continue naturally.")

    confidence = min(1.0, 0.45 + len(parsed) * 0.08)
    signals = ContextSignals(
        recommendation=recommendation,
        tone=tone,
        reciprocity=reciprocity,
        momentum=momentum,
        engagement=engagement,
        dry_reply_ratio=round(dry_ratio, 3),
        unanswered_streak=unanswered,
        message_balance=round(balance, 3),
        stop_requested=stop_requested,
        discomfort_detected=discomfort,
        repeated_rejection=repeated_rejection,
        confidence=round(confidence, 3),
        reasons=tuple(reasons),
    )
    if relationship and not signals.reasons:
        return replace(signals, reasons=("Relationship context was supplied.",))
    return signals


def is_charm_request(text: str) -> bool:
    """Backward-compatible import; new callers should use ``charm.routing``."""
    from reyes_agent.charm.routing import is_charm_request as classify

    return classify(text)
