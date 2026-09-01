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
from reyes_agent.content.versioning import (
    VersionManager, get_version_manager,
)
from reyes_agent.content.save import (
    classify_save_intent, verify_write, write_verified,
)
from reyes_agent.content.tables import (
    Table, extract_tables, save_table, to_csv, to_json, to_markdown,
)
# Import only the helper by name; keep the `convert` MODULE unshadowed so
# `reyes_agent.content.convert` stays importable as a module (callers use
# reyes_agent.content.convert.convert(...)).
from reyes_agent.content.convert import available_conversions

__all__ = [
    "ContentResult", "UniversalContentEngine", "get_engine",
    "ContentFormatRouter", "FormatInfo", "detect",
    "WorkingContext", "get_context",
    "VersionManager", "get_version_manager",
    "write_verified", "verify_write", "classify_save_intent",
    "Table", "extract_tables", "save_table", "to_csv", "to_json", "to_markdown",
    "available_conversions",
]
