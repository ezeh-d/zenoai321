"""Teaching Whiteboard -- a persistent, checkpointed lesson engine.

Extends [[learning_mode]] rather than duplicating it: `learning_mode` remains
the light, casual "answer a question, remember one struggling point" nudge.
This module backs an explicit, structured lesson -- the model authors a real
syllabus for the requested topic (this is topic-independent by design: there
is no hardcoded subject table here, unlike learning_mode's small design-only
curriculum), then teaches it one lesson at a time, checkpointing progress in
the same state database every other subsystem uses so a request such as
"teach me everything about Python" never has to be answered -- or claimed
complete -- in a single model turn.

The whiteboard panel (static/panels/renderers.js, kind "teaching") renders
the live syllabus and the current lesson's blocks from the same events this
module publishes on the existing Event Bus. No new agent, scheduler, or
memory stream is created.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any

from reyes_agent import config
from reyes_agent.learning_mode import subject_key

_lock = threading.RLock()
_MAX_TITLE = 140
_MAX_CONTENT = 4000
_MAX_SYLLABUS = 60
_MAX_BLOCKS = 40

BLOCK_KINDS = (
    "title", "explanation", "diagram", "code", "output", "example",
    "key_point", "question", "quiz", "exercise", "answer", "summary", "progress",
)


def _db_path():
    # Same state.db every other subsystem already uses -- one local SQLite
    # file, not a database per feature.
    return config.VAULT_PATH / "07-System" / "heartbeat" / "state.db"


@contextmanager
def _connection():
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS teaching_sessions (
                subject TEXT PRIMARY KEY,
                syllabus_json TEXT NOT NULL DEFAULT '[]',
                lesson_index INTEGER NOT NULL DEFAULT 0,
                completed_json TEXT NOT NULL DEFAULT '[]',
                blocks_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'active',
                updated_at REAL NOT NULL
            )"""
        )
        yield conn
        conn.commit()
    finally:
        conn.close()


def _clean(value: object, *, limit: int = _MAX_CONTENT) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _row_to_snapshot(row: tuple) -> dict[str, Any]:
    try:
        syllabus = [str(item) for item in json.loads(row[1]) if str(item).strip()][:_MAX_SYLLABUS]
    except (TypeError, json.JSONDecodeError):
        syllabus = []
    try:
        completed = [str(item) for item in json.loads(row[3])]
    except (TypeError, json.JSONDecodeError):
        completed = []
    try:
        blocks = [b for b in json.loads(row[4]) if isinstance(b, dict)]
    except (TypeError, json.JSONDecodeError):
        blocks = []
    index = max(0, min(int(row[2] or 0), len(syllabus)))
    return {
        "subject": row[0], "syllabus": syllabus, "lesson_index": index,
        "lesson_title": syllabus[index] if index < len(syllabus) else "",
        "completed": completed, "blocks": blocks, "status": row[5], "updated_at": row[6],
    }


def _row(subject: str) -> dict[str, Any] | None:
    with _lock, _connection() as conn:
        row = conn.execute(
            "SELECT subject, syllabus_json, lesson_index, completed_json, blocks_json, status, updated_at "
            "FROM teaching_sessions WHERE subject = ?", (subject,)
        ).fetchone()
    return _row_to_snapshot(row) if row is not None else None


def _save(snapshot: dict[str, Any]) -> None:
    with _lock, _connection() as conn:
        conn.execute(
            """INSERT INTO teaching_sessions(subject, syllabus_json, lesson_index, completed_json, blocks_json, status, updated_at)
               VALUES(?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(subject) DO UPDATE SET syllabus_json=excluded.syllabus_json,
                   lesson_index=excluded.lesson_index, completed_json=excluded.completed_json,
                   blocks_json=excluded.blocks_json, status=excluded.status, updated_at=excluded.updated_at""",
            (snapshot["subject"], json.dumps(snapshot["syllabus"]), snapshot["lesson_index"],
             json.dumps(snapshot["completed"]), json.dumps(snapshot["blocks"]),
             snapshot["status"], snapshot["updated_at"]),
        )


def start(subject: object, syllabus: list[object]) -> dict[str, Any]:
    """Begin (or explicitly restart) a structured lesson for one subject.

    `syllabus` is authored by the calling model turn for THIS topic -- there
    is no hardcoded course table to fall back on, so it must be real and
    sized to the topic (a five-topic Python overview and a thirty-lesson deep
    dive are both valid; padding or truncating to fit one screen is not).
    """
    key = subject_key(subject)
    clean_syllabus = [_clean(item, limit=_MAX_TITLE) for item in (syllabus or [])]
    clean_syllabus = [item for item in clean_syllabus if item][:_MAX_SYLLABUS]
    if not clean_syllabus:
        clean_syllabus = ["Overview"]
    snapshot = {
        "subject": key, "syllabus": clean_syllabus, "lesson_index": 0,
        "lesson_title": clean_syllabus[0], "completed": [], "blocks": [],
        "status": "active", "updated_at": time.time(),
    }
    _save(snapshot)
    _publish("teaching.started", snapshot)
    return snapshot


def push_block(subject: object, kind: object, content: object) -> dict[str, Any] | None:
    """Append one whiteboard block to the CURRENT lesson. None if no session."""
    key = subject_key(subject)
    snapshot = _row(key)
    if snapshot is None:
        return None
    kind_value = str(kind or "").strip().casefold()
    if kind_value not in BLOCK_KINDS:
        kind_value = "explanation"
    block = {"kind": kind_value, "content": _clean(content), "at": time.time()}
    snapshot["blocks"] = (snapshot["blocks"] + [block])[-_MAX_BLOCKS:]
    snapshot["updated_at"] = time.time()
    _save(snapshot)
    _publish("teaching.block", {**snapshot, "block": block})
    return snapshot


def complete_lesson(subject: object) -> dict[str, Any] | None:
    """Mark the current lesson done and advance. None if no session."""
    key = subject_key(subject)
    snapshot = _row(key)
    if snapshot is None:
        return None
    if snapshot["status"] == "complete":
        return snapshot
    index = snapshot["lesson_index"]
    syllabus = snapshot["syllabus"]
    if index < len(syllabus):
        title = syllabus[index]
        if title not in snapshot["completed"]:
            snapshot["completed"] = snapshot["completed"] + [title]
    next_index = index + 1
    snapshot["lesson_index"] = next_index
    snapshot["lesson_title"] = syllabus[next_index] if next_index < len(syllabus) else ""
    if next_index >= len(syllabus):
        snapshot["status"] = "complete"
        event = "teaching.session_completed"
    else:
        snapshot["blocks"] = []
        snapshot["status"] = "active"
        event = "teaching.lesson_completed"
    snapshot["updated_at"] = time.time()
    _save(snapshot)
    _publish(event, snapshot)
    return snapshot


def _set_status(subject: object, status: str, event: str) -> dict[str, Any] | None:
    key = subject_key(subject)
    snapshot = _row(key)
    if snapshot is None or snapshot["status"] == "complete":
        return snapshot
    snapshot["status"] = status
    snapshot["updated_at"] = time.time()
    _save(snapshot)
    _publish(event, snapshot)
    return snapshot


def pause(subject: object) -> dict[str, Any] | None:
    return _set_status(subject, "paused", "teaching.paused")


def resume(subject: object) -> dict[str, Any] | None:
    return _set_status(subject, "active", "teaching.resumed")


def status(subject: object) -> dict[str, Any] | None:
    return _row(subject_key(subject))


def latest() -> dict[str, Any] | None:
    """Most recently touched session, so a reopened panel shows real state
    instead of an empty board while waiting for the next live event."""
    with _lock, _connection() as conn:
        row = conn.execute(
            "SELECT subject, syllabus_json, lesson_index, completed_json, blocks_json, status, updated_at "
            "FROM teaching_sessions ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    return _row_to_snapshot(row) if row is not None else None


def format_status(snapshot: dict[str, Any]) -> str:
    lines = [f"{snapshot['subject'].upper()} -- LESSON "
             f"{min(snapshot['lesson_index'] + 1, len(snapshot['syllabus']))}/{len(snapshot['syllabus'])} "
             f"({snapshot['status']})"]
    done = set(snapshot["completed"])
    for index, title in enumerate(snapshot["syllabus"]):
        marker = "[x]" if title in done else ("[>]" if index == snapshot["lesson_index"] else "[ ]")
        lines.append(f"{marker} {index + 1}. {title}")
    if snapshot["status"] != "complete":
        lines.append(f"Current lesson: {snapshot['lesson_title']} "
                     f"({len(snapshot['blocks'])} block(s) on the board so far)")
    else:
        lines.append("All lessons complete.")
    return "\n".join(lines)


def directive(message: str) -> str:
    """Bounded prompt aid appended to the existing agent turn -- never a new
    model call. Fixes the "stops after one screen" failure mode by making
    checkpoint-and-resume the default shape of an explicit lesson request."""
    text = _clean(message).casefold()
    if not re.search(r"\b(teach|lesson|lecture|course|syllabus|whiteboard)\b", text):
        return ""
    return (
        "[Teaching Whiteboard: this is an explicit lesson request. If this subject has no active session yet, call "
        "teaching_board(action='start', subject=<topic>, syllabus=[...]) with a real ordered list of lesson titles you "
        "construct for THIS topic -- as many as the topic genuinely needs, never padded or truncated to fit one reply. "
        "Then teach ONE lesson at a time: explain it in your normal reply, call teaching_board(action='push_block', "
        "subject=<topic>, kind=<title|explanation|diagram|code|output|example|key_point|question|quiz|exercise|answer|"
        "summary|progress>, content=<text>) for each meaningful board block as you go, and call "
        "teaching_board(action='complete_lesson', subject=<topic>) only once that lesson is actually taught. End your "
        "reply at the close of one lesson and wait rather than dumping the whole course in a single turn. If this is a "
        "continuation (a new turn on a subject already started, or the user says continue/keep going), call "
        "teaching_board(action='status', subject=<topic>) FIRST to see exactly what is already covered before teaching "
        "the next lesson -- never repeat a completed lesson, and never say the course is finished while lessons remain.]"
    )


def _publish(event_type: str, payload: dict[str, Any]) -> None:
    try:
        from reyes_agent import event_bus
        event_bus.publish(event_type, payload, source="teaching")
    except Exception:  # noqa: BLE001 -- board updates must never block the conversation
        pass
