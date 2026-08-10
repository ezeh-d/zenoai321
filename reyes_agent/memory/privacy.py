"""Secret detection and prompt-safe redaction for memory."""

from __future__ import annotations

import re

_SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|xai|AIza|ghp|github_pat|eyJ)[-_A-Za-z0-9.]{16,}\b"),
    re.compile(r"(?i)\b(?:api[_ -]?key|password|passwd|secret|token|private[_ -]?key)\s*[:=]\s*[^\s,;]{6,}"),
    # JSON-encoded tool output places a quote between the key and colon;
    # cover that form before it enters model context or persisted audits.
    re.compile(
        r'''(?ix)["']?(?:api[_ -]?key|password|passwd|secret|token|private[_ -]?key)["']?\s*[:=]\s*'''
        r'''(?:"[^"\r\n]{6,}"|'[^'\r\n]{6,}'|[^\s,;]{6,})'''
    ),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+PRIVATE KEY-----"),
)


def contains_secret(text: str) -> bool:
    value = str(text or "")
    return any(pattern.search(value) for pattern in _SECRET_PATTERNS)


def redact(text: str, *, limit: int = 1600) -> str:
    value = str(text or "")[: max(0, int(limit))]
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub("[REDACTED]", value)
    return value
