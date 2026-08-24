"""'What am I looking at?' -- resolve the target of a vague command (Pack 10 #3-5).

When the user says "explain this" / "fix this", ZENO must decide WHAT "this" is.
The rule (#5) is a fixed priority: an explicit text selection beats the focused
window, which beats the current conversation reference, the active file, the
active webpage, and finally whatever was recently in view. #4: a highlight plus
"explain this" always prefers the selection over the whole screen. Pure logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ScreenContext:
    selection: str = ""          # explicitly highlighted text
    focused_app: str = ""
    focused_title: str = ""
    active_file: str = ""
    active_url: str = ""
    conversation_ref: str = ""   # a thing referenced in the current chat
    recent: str = ""             # last thing in view


# (attribute, source-label, reason) in strict priority order (#5).
_PRIORITY = [
    ("selection", "selection", "you highlighted this"),
    ("_focused", "focused_window", "it is the focused window"),
    ("conversation_ref", "conversation", "it was referenced in the conversation"),
    ("active_file", "active_file", "it is the active file"),
    ("active_url", "active_webpage", "it is the open webpage"),
    ("recent", "recent", "it was recently in view"),
]


def resolve(ctx: ScreenContext) -> dict[str, Any]:
    """Pick the most specific available context. Returns source, content, reason.
    Empty content with source 'none' when nothing is available."""
    focused = " - ".join(p for p in (ctx.focused_app, ctx.focused_title) if p).strip()
    for attr, source, reason in _PRIORITY:
        value = focused if attr == "_focused" else getattr(ctx, attr, "")
        if value and str(value).strip():
            return {"source": source, "content": str(value).strip(), "reason": reason}
    return {"source": "none", "content": "",
            "reason": "nothing is selected, focused or recently in view"}


def resolve_for(command: str, ctx: ScreenContext) -> dict[str, Any]:
    """Same, but a command that names a concrete target ('explain this page',
    'read the selection') nudges the priority toward that target."""
    low = str(command or "").casefold()
    if "selection" in low or "highlight" in low:
        if ctx.selection.strip():
            return {"source": "selection", "content": ctx.selection.strip(),
                    "reason": "you asked about the selection"}
    if ("page" in low or "site" in low or "url" in low) and ctx.active_url.strip():
        return {"source": "active_webpage", "content": ctx.active_url.strip(),
                "reason": "you asked about the page"}
    if "file" in low and ctx.active_file.strip():
        return {"source": "active_file", "content": ctx.active_file.strip(),
                "reason": "you asked about the file"}
    return resolve(ctx)
