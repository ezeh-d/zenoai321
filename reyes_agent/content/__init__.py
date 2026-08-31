"""ZENO Universal Content Engine (Phase 1).

One coherent content system -- detect format by content, parse with the right
existing backend, track what the conversation is about, and never fake success.
Editing/conversion/OCR-routing/versioning are later phases built on this core.
"""

from __future__ import annotations

from reyes_agent.content.engine import (
    ContentResult, UniversalContentEngine, get_engine,
)
from reyes_agent.content.format_router import (
    ContentFormatRouter, FormatInfo, detect,
)
from reyes_agent.content.working_context import (
    WorkingContext, get_context,
)

__all__ = [
    "ContentResult", "UniversalContentEngine", "get_engine",
    "ContentFormatRouter", "FormatInfo", "detect",
    "WorkingContext", "get_context",
]
