"""ZENO Universal Language Intelligence.

One engine, every input surface. Desktop microphone, phone microphone, web
chat and the remote command queue all call `understand_text`, so multilingual
behaviour cannot drift between them.

The engine converts any input into clear English and reports how confident it
is. It never executes anything: the intent parser, capability system and
permission gates run afterwards, unchanged.
"""

from reyes_agent.language.engine import (  # noqa: F401
    CLARIFY_THRESHOLD,
    SENSITIVE_THRESHOLD,
    Understanding,
    diagnostics,
    normalize_to_plain_english,
    status,
    translate as translate_text,
    translate_to_english,
    understand_text,
)

__all__ = [
    "Understanding", "understand_text", "translate_to_english", "translate_text",
    "normalize_to_plain_english", "diagnostics", "status",
    "SENSITIVE_THRESHOLD", "CLARIFY_THRESHOLD",
]
