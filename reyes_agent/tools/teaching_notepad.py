"""Types a Teaching Whiteboard lesson into Notepad, one checkpointed block at
a time -- the fix for "ZENO writes a little into Notepad and then stops".

REUSE, NOT A NEW AUTOMATION PATH
---------------------------------
Every keystroke goes through the existing gated/verified engine
(computer.agentic.act via tools.hands_tools.type_text/press_keys): permission
-gated, refuses to steal input while the owner is typing, and refuses to send
a keystroke to a window whose focus moved since it was last read. This module
adds none of that itself -- it only decides WHAT to type and WHEN to stop.

WHY DUPLICATION CAN'T HAPPEN
-----------------------------
teaching.py is the single source of truth for lesson content (the same
blocks the Teaching Whiteboard panel renders). This module only ever sends
blocks[notepad_written:] -- the exact slice not yet typed -- and persists the
new count immediately after each verified type_text call succeeds. A block
is never counted as written on a guess, and a failed/partial write leaves
the count exactly where it was, so the next call resumes from the true
boundary instead of re-typing or skipping.
"""

from __future__ import annotations

import json
import time

from reyes_agent.tools import register

_NOTEPAD_TITLE = "Notepad"
_SETTLE_S = 0.4


def _ensure_notepad_foreground() -> tuple[bool, str]:
    """Reuse an already-open Notepad if there is one; only launch a new
    window when none exists, so a continuation never opens a second,
    blank Notepad on top of the one already being written into."""
    from reyes_agent.computer import window

    matches = window.find_by_title(_NOTEPAD_TITLE)
    if matches:
        handle, title = matches[0]
        if window.is_foreground(handle):
            return True, f"{title!r} already focused"
        ok, detail = window.activate(handle)
        return ok, f"{title!r}: {detail}"

    from reyes_agent.tools.system import open_app

    result = open_app("notepad")
    if not result.lower().startswith("opened"):
        return False, result
    time.sleep(_SETTLE_S)
    matches = window.find_by_title(_NOTEPAD_TITLE)
    if not matches:
        return False, "Notepad did not appear after launching it"
    handle, title = matches[0]
    ok, detail = window.activate(handle)
    return ok, f"{title!r}: {detail}"


def _format_block(block: dict) -> str:
    kind = str(block.get("kind", "")).strip().casefold()
    content = str(block.get("content", ""))
    if kind == "title":
        return f"\n{'=' * 60}\n{content}\n{'=' * 60}\n\n"
    heading = kind.replace("_", " ").upper() or "NOTE"
    return f"[{heading}]\n{content}\n\n"


@register(
    name="write_lesson_to_notepad",
    description=(
        "Type the current Teaching Whiteboard lesson's NOT-YET-WRITTEN blocks into Notepad, checkpointed and verified. "
        "Only call this for a lesson the owner explicitly asked to be taught IN NOTEPAD (teaching_board was started with "
        "target='notepad'). Reuses an already-open Notepad rather than opening a new one, always appends at the end, and "
        "sends only the blocks not yet written -- so calling it again after more push_block calls continues correctly "
        "without retyping anything. Stops and reports exactly how many blocks it wrote if Notepad loses focus or a block "
        "fails to type; never claims completion while blocks remain."
    ),
    input_schema={"type": "object", "properties": {
        "subject": {"type": "string", "description": "The lesson topic, exactly as passed to teaching_board."},
    }, "required": ["subject"]},
    light=True,
)
def write_lesson_to_notepad(subject: str) -> str:
    from reyes_agent import teaching
    from reyes_agent.tools.hands_tools import press_keys, type_text

    session = teaching.status(subject)
    if session is None:
        return "No active teaching session for that subject. Call teaching_board(action='start', ...) first."
    if session.get("target") != "notepad":
        return ("This session wasn't started for Notepad. Restart it with "
                "teaching_board(action='start', subject=..., syllabus=[...], target='notepad') to write into Notepad.")

    already = session.get("notepad_written", 0)
    pending = session["blocks"][already:]
    if not pending:
        return f"Nothing new to write -- Notepad is already caught up ({already} block(s) written for this lesson)."

    ok, detail = _ensure_notepad_foreground()
    if not ok:
        return f"Wrote 0 new block(s): could not bring Notepad to the foreground -- {detail}"

    written = 0
    for block in pending:
        press_keys("ctrl+end")  # always append, never overwrite what's there
        result = json.loads(type_text(_format_block(block)))
        if not result.get("ok"):
            teaching.set_notepad_written(subject, already + written)
            return (f"Stopped after writing {written} new block(s) ({already + written} total for this lesson): "
                    f"{result.get('detail', 'the type action was refused')}")
        written += 1

    teaching.set_notepad_written(subject, already + written)
    updated = teaching.status(subject)
    return f"Wrote {written} new block(s) to Notepad.\n" + teaching.format_status(updated)
