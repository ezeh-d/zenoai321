"""Fast deterministic intent recognition for lazy Charm activation."""

from __future__ import annotations

import re


_DIRECT_CHARM_RE = re.compile(
    r"\b(?:charm engine|best reply|smooth reply|sweet reply|funny reply|"
    r"pidgin smooth|dry repl(?:y|ies)|sound desperate|sound cringe|cringe risk|"
    r"rizz intensity|conversation momentum|reciprocity|make (?:that|this) "
    r"(?:smoother|sweeter|funnier|playful|witty|romantic|natural)|"
    r"what should i (?:text|message|say|reply)|"
    r"help me (?:text|message|reply|respond))\b",
    re.IGNORECASE,
)
_MODE_RE = re.compile(
    r"\b(?:natural|smooth|sweet|flirty|playful|funny|witty|romantic|confident|"
    r"gentleman|cheeky|deep|serious)\b",
    re.IGNORECASE,
)
_SOCIAL_CONTEXT_RE = re.compile(
    r"\b(?:reply|replies|message|text|conversation|chat|say|her|him|date|"
    r"compliment|opener|wingman|sound like me|three options)\b",
    re.IGNORECASE,
)
_COMMAND_RE = re.compile(
    r"\b(?:give me something (?:natural|smooth|sweet|flirty|playful|funny|witty|"
    r"romantic|confident|gentleman|cheeky|deep|serious)|"
    r"make (?:it|this|that) (?:funny|playful|witty|romantic|natural|sweeter|smoother)|"
    r"make (?:it|this|that) sound (?:natural|like me)|"
    r"give me (?:one|two|three|four|five|some|\d+) (?:reply )?options)\b",
    re.IGNORECASE,
)


def is_charm_request(text: str) -> bool:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return False
    if _DIRECT_CHARM_RE.search(normalized) or _COMMAND_RE.search(normalized):
        return True
    return bool(_MODE_RE.search(normalized) and _SOCIAL_CONTEXT_RE.search(normalized))
