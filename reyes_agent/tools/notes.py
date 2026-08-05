"""Read-only tools over the Obsidian vault. No writes yet -- that's a later tool."""

from __future__ import annotations

import os

from reyes_agent import config
from reyes_agent.tools import register

_SKIP_DIRS = {".obsidian", ".git"}


def _coerce_limit(value, default: int) -> int:
    """Small local models sometimes send limit as null or a numeric string
    instead of an int -- normalize rather than let it blow up mid-search."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _iter_notes():
    if not config.VAULT_PATH.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(config.VAULT_PATH):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            if name.endswith(".md"):
                yield os.path.join(dirpath, name), name[:-3]


@register(
    name="search_notes",
    description=(
        "Search the user's Obsidian vault (their notes / second brain) for a "
        "word or phrase. Use this whenever the user asks about something "
        "that might be written down -- a project, a decision, an idea, a "
        "person, anything they might have noted. Returns matching note "
        "titles with a short snippet of the matching line."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Word or phrase to search for, case-insensitive.",
            },
            "limit": {
                "type": "integer",
                "description": "Max number of matching notes to return. Default 5.",
            },
        },
        "required": ["query"],
    },
    light=True,
)
def search_notes(query: str, limit: int = 5) -> str:
    if not config.VAULT_PATH.is_dir():
        return f"No vault found at {config.VAULT_PATH}. Check VAULT_PATH in .env."

    limit = _coerce_limit(limit, default=5)
    q = query.lower()
    hits: list[str] = []
    for path, title in _iter_notes():
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        if q not in title.lower() and q not in text.lower():
            continue
        snippet = next(
            (line.strip()[:150] for line in text.splitlines() if q in line.lower()),
            "",
        )
        hits.append(f"{title} -- {snippet}" if snippet else title)
        if len(hits) >= limit:
            break

    if not hits:
        return f"No notes matched '{query}'."
    return "\n".join(hits)


@register(
    name="list_notes",
    description=(
        "List the titles of notes in the user's Obsidian vault, most "
        "recently modified first. Use this when the user asks what notes "
        "they have, or wants an overview rather than a specific search."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Max number of note titles to return. Default 20.",
            }
        },
    },
    light=True,
)
def list_notes(limit: int = 20) -> str:
    if not config.VAULT_PATH.is_dir():
        return f"No vault found at {config.VAULT_PATH}. Check VAULT_PATH in .env."

    limit = _coerce_limit(limit, default=20)
    notes = sorted(
        ((os.path.getmtime(path), title) for path, title in _iter_notes()),
        reverse=True,
    )
    if not notes:
        return "The vault has no notes yet."
    return "\n".join(title for _mtime, title in notes[:limit])
