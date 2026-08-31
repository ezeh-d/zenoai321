"""Brain tools for the Universal Learning Engine (Phase 1).

ZENO calls these when the owner says "study this", "what did you learn?", "where
did you get that?". They ingest and index documents for study and return
GROUNDED passages with citations -- ZENO's brain then does the explaining/
teaching on top. Owner-direct: studying and recalling user-provided content are
normal actions and do not ask for repeated approval (#40).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from reyes_agent.tools import register


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _resolve(target: str) -> str:
    raw = str(target or "it").strip().strip('"').strip("'")
    if raw and Path(os.path.expanduser(raw)).exists():
        return str(Path(os.path.expanduser(raw)))
    try:
        from reyes_agent.content import get_context
        ref = get_context().resolve(target or "it")
        return ref.path if ref.ok else ""
    except Exception:  # noqa: BLE001
        return ""


@register(
    name="study_document",
    description=(
        "Study a document so ZENO can answer questions about it later WITH "
        "citations. Parses it, splits it into passages with real provenance "
        "(per-page for PDFs), embeds them and saves them to a persistent study "
        "store. Accepts a path or a reference ('it', 'that file'). Use when the "
        "owner says 'study this', 'learn this', 'read this document'."
    ),
    input_schema={"type": "object", "properties": {
        "target": {"type": "string", "description": "File path or reference (default: the active file)."},
    }},
)
def study_document(target: str = "it") -> str:
    from reyes_agent.study import get_study_engine
    path = _resolve(target)
    if not path:
        return _json({"ok": False, "error": f"couldn't resolve '{target}' to a file"})
    return _json(get_study_engine().study(path))


@register(
    name="study_ask",
    description=(
        "Retrieve the passages from studied material most relevant to a question, "
        "each with a source citation (file + page/chunk) and an honest confidence. "
        "This GROUNDS ZENO's answer -- answer from these passages and cite them; if "
        "grounded is false, say the studied material doesn't cover it rather than "
        "guessing. Optionally restrict to one source. Use for 'what does the "
        "document say about X', 'where did you get that', exam questions."
    ),
    input_schema={"type": "object", "properties": {
        "question": {"type": "string", "description": "The question to ground."},
        "source": {"type": "string", "description": "Optional: restrict to one studied file path."},
    }, "required": ["question"]},
    light=True,
)
def study_ask(question: str, source: str = "") -> str:
    from reyes_agent.study import get_study_engine
    src = _resolve(source) if source else ""
    result = get_study_engine().ask(question, source=src)
    return _json(result)


@register(
    name="study_status",
    description=(
        "List what ZENO has studied: each document, its passage/page count and "
        "when it was studied. Use for 'what have you learned?' / 'what's in your "
        "study memory?'."
    ),
    input_schema={"type": "object", "properties": {}},
    light=True,
)
def study_status() -> str:
    from reyes_agent.study import get_study_engine
    return _json(get_study_engine().catalog())


@register(
    name="study_forget",
    description=(
        "Remove a document from ZENO's study memory (e.g. 'forget this course', "
        "'don't keep that study session'). Reversible by studying it again."
    ),
    input_schema={"type": "object", "properties": {
        "target": {"type": "string", "description": "File path or reference to forget."},
    }, "required": ["target"]},
)
def study_forget(target: str) -> str:
    from reyes_agent.study import get_study_engine
    path = _resolve(target) or str(target)
    return _json(get_study_engine().forget(path))
