"""Brain tools for the Universal Content Engine.

ZENO calls these when the owner says things like "look at this file", "what is
it", "open that PDF". They return FACTS (format, what was found, honest status,
provenance) -- never a finished sentence; the NaturalResponseEngine decides the
wording. They set the working context so follow-ups ("open it", "that table")
resolve without repeating the filename.

Read-only in Phase 1: open / inspect / understand. Editing, conversion and
versioning arrive as their own gated tools in later phases.
"""

from __future__ import annotations

import json
from typing import Any

from reyes_agent.tools import register


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


@register(
    name="content_open",
    description=(
        "Open and understand a file, or a reference to one ('it', 'that file', "
        "'the previous one'). Detects the real format by content, parses it with "
        "the right backend (PDF/DOCX/XLSX/PPTX text, images via OCR, plain text "
        "and CSV/JSON directly), and remembers it as the active file so "
        "follow-up commands don't need the name again. Returns structured facts "
        "and an HONEST status -- it never claims to have read a file it could "
        "not parse. Use when the owner asks ZENO to look at / read / open a file."
    ),
    input_schema={"type": "object", "properties": {
        "target": {"type": "string",
                   "description": "A file path, or a reference like 'it' / 'that file' / 'the second one'."},
        "max_chars": {"type": "integer",
                      "description": "Cap the extracted text (default 20000)."},
    }, "required": ["target"]},
    light=True,
)
def content_open(target: str, max_chars: int = 20000) -> str:
    from reyes_agent.content import get_engine

    result = get_engine().open(target, max_chars=max(500, min(int(max_chars or 20000), 200000)))
    payload = result.as_dict()
    # Include a bounded preview so the model can summarise WITHOUT re-reading.
    if result.text:
        payload["preview"] = result.text[:1500]
    if result.structured is not None and isinstance(result.structured, dict):
        payload["structured_summary"] = {k: result.structured.get(k)
                                         for k in ("headers", "row_count", "col_count")
                                         if k in result.structured}
    if not result.ok:
        payload["note"] = ("Parsing did not succeed; do not invent the file's "
                           "contents. Tell the owner the honest status.")
    return _json(payload)


@register(
    name="content_inspect",
    description=(
        "Quickly identify a file WITHOUT fully parsing it: real format (by "
        "content), category, MIME, size, and whether OCR would be needed. Fast; "
        "use to answer 'what kind of file is this?' or before deciding how to "
        "open something large."
    ),
    input_schema={"type": "object", "properties": {
        "target": {"type": "string", "description": "File path or reference."},
    }, "required": ["target"]},
    light=True,
)
def content_inspect(target: str) -> str:
    from reyes_agent.content import get_engine

    return _json(get_engine().inspect(target))


@register(
    name="content_context",
    description=(
        "Show what the file conversation is currently about: the active file, "
        "active page/sheet/slide, recent files and any noted selection. Use to "
        "resolve or confirm what 'it' / 'that one' refers to."
    ),
    input_schema={"type": "object", "properties": {}},
    light=True,
)
def content_context() -> str:
    from reyes_agent.content import get_context

    return _json(get_context().snapshot())
