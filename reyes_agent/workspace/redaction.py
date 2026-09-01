"""Small, bounded redaction helpers for workspace-facing records."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_DENIED_KEY_PARTS = (
    "token",
    "secret",
    "password",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "private_message",
    "message_body",
    "prompt",
    "chain_of_thought",
)
_SECRET_VALUE = re.compile(
    r"(?:\bbearer\s+[a-z0-9._~+/=-]+|\bsk-(?:proj-)?[a-z0-9_-]{6,})",
    re.IGNORECASE,
)
_CONTROLS = re.compile(r"[\x00-\x1f\x7f]+")
_WHITESPACE = re.compile(r"\s+")


def safe_text(value: object, limit: int = 300) -> str:
    """Return one compact line with a hard character bound."""
    maximum = max(0, min(int(limit), 5_000))
    if maximum == 0:
        return ""
    try:
        text = str(value or "")
    except Exception:
        text = type(value).__name__
    text = _WHITESPACE.sub(" ", _CONTROLS.sub(" ", text)).strip()
    return text[:maximum]


def _denied_key(key: object) -> bool:
    folded = safe_text(key, 80).casefold().replace("-", "_")
    return any(part in folded for part in _DENIED_KEY_PARTS)


def _sanitize(value: object, *, depth: int, max_depth: int) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if depth >= max_depth:
        return safe_text(value, 200)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, raw_value in list(value.items())[:50]:
            if _denied_key(raw_key):
                continue
            key = safe_text(raw_key, 80)
            if key:
                result[key] = _sanitize(raw_value, depth=depth + 1, max_depth=max_depth)
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_sanitize(item, depth=depth + 1, max_depth=max_depth)
                for item in list(value)[:50]]
    return safe_text(value, 500)


def sanitize_mapping(value: object, *, max_depth: int = 4) -> dict[str, Any]:
    """Redact a mapping recursively and cap its breadth/depth."""
    if not isinstance(value, Mapping):
        return {}
    return _sanitize(value, depth=0, max_depth=max(1, min(int(max_depth), 8)))


def secret_free(value: object) -> bool:
    """Conservatively verify that a public projection contains no secret hints."""
    if isinstance(value, Mapping):
        return all(not _denied_key(key) and secret_free(item)
                   for key, item in value.items())
    if isinstance(value, (list, tuple, set, frozenset)):
        return all(secret_free(item) for item in value)
    if isinstance(value, str):
        return _SECRET_VALUE.search(value) is None
    return True
