"""Deterministic memory retention policy.

The policy deliberately does not call a model.  A second model call merely to
decide whether to remember a sentence would add latency and may itself leak
the sentence.  Ambiguous content stays session-only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from reyes_agent.memory.privacy import contains_secret


class Category(str, Enum):
    USER = "user"
    PROJECT = "project"
    AGENT = "agent"
    SESSION = "session"
    IGNORE = "ignore"


class Retention(str, Enum):
    LONG_TERM = "long_term"
    SESSION = "session"
    IGNORE = "ignore"


@dataclass(frozen=True)
class Decision:
    category: Category
    retention: Retention
    reason: str
    expires_s: int | None = None

    @property
    def durable(self) -> bool:
        return self.retention is Retention.LONG_TERM


_PREFERENCE = re.compile(
    r"(?i)\b(?:i (?:prefer|like|dislike|always use|usually use|want you to)|"
    r"my preferred|call me|please always|communication style)\b"
)
_PROJECT = re.compile(
    r"(?i)\b(?:project|repository|repo|codebase|architecture|decision|roadmap|"
    r"milestone|unfinished|next step|work(?:ing)? on|build error|root cause)\b"
)
_AGENT = re.compile(
    r"(?i)\b(?:agent|specialist|strategy|tool|execution|failed because|succeeded by|"
    r"recovery|workaround|lesson learned)\b"
)
_EXPLICIT = re.compile(r"(?i)\b(?:remember this|remember that|save this|don't forget|do not forget)\b")
_TRANSIENT = re.compile(
    r"(?i)\b(?:right now|for now|this time only|today only|temporary|temporarily|"
    r"current screen|current window|loading|thinking|waiting)\b"
)


def decide(text: str, *, source: str = "user", verified: bool = False,
           explicit: bool = False) -> Decision:
    value = " ".join(str(text or "").split())
    if not value or len(value) < 4:
        return Decision(Category.IGNORE, Retention.IGNORE, "empty or too short")
    if contains_secret(value):
        return Decision(Category.IGNORE, Retention.IGNORE, "contains credentials or secret material")
    if len(value) > 4000:
        return Decision(Category.SESSION, Retention.SESSION, "large raw content is not durable memory", 8 * 3600)
    if _TRANSIENT.search(value):
        return Decision(Category.SESSION, Retention.SESSION, "explicitly temporary context", 8 * 3600)

    explicit = bool(explicit or _EXPLICIT.search(value))
    if _PREFERENCE.search(value):
        return Decision(Category.USER, Retention.LONG_TERM, "stable owner preference")
    if _PROJECT.search(value) and (verified or explicit):
        return Decision(Category.PROJECT, Retention.LONG_TERM,
                        "verified or explicitly requested project context")
    if source.startswith("agent") and _AGENT.search(value) and verified:
        return Decision(Category.AGENT, Retention.LONG_TERM, "verified execution lesson")
    if explicit:
        return Decision(Category.USER, Retention.LONG_TERM, "owner explicitly requested retention")
    return Decision(Category.SESSION, Retention.SESSION, "useful for this session only", 8 * 3600)
