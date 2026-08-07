"""Small, persistent Learning Mode built on ZENO's existing state database.

It stores only the learning state the owner explicitly starts or updates:
subject, level, completed topics, an optional difficulty note, and the next
exercise.  It is not a second agent, scheduler, or memory stream.
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


_lock = threading.RLock()
_MAX_TEXT = 240
_MAX_ITEMS = 32

_DESIGN_SUBJECTS = {
    "graphic design": (
        "Design fundamentals", "Typography", "Colour", "Layout and composition",
        "Logo design", "Brand identity", "Real projects", "Portfolio",
    ),
    "logo design": (
        "What makes a mark work", "Logo structures", "Black-and-white concepts",
        "Typography", "Colour systems", "Refinement and testing", "Brand application",
        "Case study portfolio",
    ),
    "ui ux": (
        "Users and problems", "Information architecture", "Wireframes", "Flows and interaction",
        "Components and design systems", "Accessibility", "Responsive interfaces", "Case study portfolio",
    ),
    "branding": (
        "Positioning", "Audience and personality", "Visual direction", "Logo system",
        "Typography and colour", "Voice and imagery", "Brand guidelines", "Identity case study",
    ),
}


def _db_path():
    return config.VAULT_PATH / "07-System" / "heartbeat" / "state.db"


@contextmanager
def _connection():
    """Open one short-lived state-db connection and always release it.

    Learning updates run on a conversation/worker path. Leaving even an idle
    SQLite handle open can block another subsystem or prevent shutdown on
    Windows, so connection lifetime is deliberately one operation.
    """
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS learning_progress (
                subject TEXT PRIMARY KEY,
                level TEXT NOT NULL,
                goal TEXT NOT NULL DEFAULT '',
                completed_json TEXT NOT NULL DEFAULT '[]',
                struggle TEXT NOT NULL DEFAULT '',
                current_exercise TEXT NOT NULL DEFAULT '',
                next_lesson TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL
            )"""
        )
        yield conn
        conn.commit()
    finally:
        conn.close()


def _clean(value: object, *, limit: int = _MAX_TEXT) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def subject_key(subject: object) -> str:
    value = _clean(subject, limit=80).casefold()
    value = re.sub(r"[^a-z0-9+/#. -]", "", value)
    return value or "general learning"


def curriculum(subject: object) -> tuple[str, ...]:
    key = subject_key(subject)
    aliases = {
        "graphic": "graphic design", "design": "graphic design", "graphic-design": "graphic design",
        "logos": "logo design", "ui/ux": "ui ux", "ux ui": "ui ux", "brand identity": "branding",
    }
    key = aliases.get(key, key)
    if key in _DESIGN_SUBJECTS:
        return _DESIGN_SUBJECTS[key]
    # A deliberately small generic path covers other difficult skills without
    # pretending a new specialist or verified course exists for every topic.
    return ("Foundations", "Core concepts", "Guided practice", "Small project", "Review and next goal")


def _row(subject: str) -> dict[str, Any] | None:
    with _lock, _connection() as conn:
        row = conn.execute(
            "SELECT subject, level, goal, completed_json, struggle, current_exercise, next_lesson, updated_at "
            "FROM learning_progress WHERE subject = ?", (subject,)
        ).fetchone()
    if row is None:
        return None
    try:
        completed = json.loads(row[3])
    except (TypeError, json.JSONDecodeError):
        completed = []
    return {
        "subject": row[0], "level": row[1], "goal": row[2],
        "completed": [str(item) for item in completed if str(item)][: _MAX_ITEMS],
        "struggle": row[4], "current_exercise": row[5], "next_lesson": row[6], "updated_at": row[7],
    }


def _next(subject: str, completed: list[str]) -> str:
    known = {item.casefold() for item in completed}
    return next((item for item in curriculum(subject) if item.casefold() not in known), "Portfolio / independent practice")


def start(subject: object, *, level: object = "beginner", goal: object = "") -> dict[str, Any]:
    """Create or deliberately restart a named learning path."""
    key = subject_key(subject)
    level_value = _clean(level, limit=40).casefold() or "beginner"
    if level_value not in {"beginner", "intermediate", "advanced", "unsure"}:
        level_value = "unsure"
    goal_value = _clean(goal)
    existing = _row(key)
    completed = existing["completed"] if existing else []
    snapshot = {
        "subject": key, "level": level_value, "goal": goal_value or (existing or {}).get("goal", ""),
        "completed": completed, "struggle": (existing or {}).get("struggle", ""),
        "current_exercise": (existing or {}).get("current_exercise", ""),
        "next_lesson": _next(key, completed), "updated_at": time.time(),
    }
    with _lock, _connection() as conn:
        conn.execute(
            """INSERT INTO learning_progress(subject, level, goal, completed_json, struggle, current_exercise, next_lesson, updated_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(subject) DO UPDATE SET level=excluded.level, goal=excluded.goal,
                   next_lesson=excluded.next_lesson, updated_at=excluded.updated_at""",
            (snapshot["subject"], snapshot["level"], snapshot["goal"], json.dumps(completed),
             snapshot["struggle"], snapshot["current_exercise"], snapshot["next_lesson"], snapshot["updated_at"]),
        )
    _publish("learning.started", snapshot)
    return snapshot


def update(subject: object, *, completed_topic: object = "", struggle: object = "",
           exercise: object = "", level: object = "") -> dict[str, Any]:
    key = subject_key(subject)
    snapshot = _row(key) or start(key, level=level or "beginner")
    topic = _clean(completed_topic)
    if topic and topic.casefold() not in {item.casefold() for item in snapshot["completed"]}:
        snapshot["completed"] = (snapshot["completed"] + [topic])[-_MAX_ITEMS:]
    if struggle:
        snapshot["struggle"] = _clean(struggle)
    if exercise:
        snapshot["current_exercise"] = _clean(exercise)
    if level:
        requested = _clean(level, limit=40).casefold()
        if requested in {"beginner", "intermediate", "advanced", "unsure"}:
            snapshot["level"] = requested
    snapshot["next_lesson"] = _next(key, snapshot["completed"])
    snapshot["updated_at"] = time.time()
    with _lock, _connection() as conn:
        conn.execute(
            "UPDATE learning_progress SET level=?, completed_json=?, struggle=?, current_exercise=?, next_lesson=?, updated_at=? WHERE subject=?",
            (snapshot["level"], json.dumps(snapshot["completed"]), snapshot["struggle"],
             snapshot["current_exercise"], snapshot["next_lesson"], snapshot["updated_at"], key),
        )
    _publish("learning.progress_updated", snapshot)
    return snapshot


def status(subject: object) -> dict[str, Any] | None:
    return _row(subject_key(subject))


def format_path(snapshot: dict[str, Any]) -> str:
    levels = curriculum(snapshot["subject"])
    done = {item.casefold() for item in snapshot.get("completed", [])}
    lines = [f"{snapshot['subject'].upper()} — {snapshot['level'].upper()} PATH"]
    for index, item in enumerate(levels, 1):
        marker = "✓" if item.casefold() in done else ("●" if item == snapshot["next_lesson"] else "○")
        lines.append(f"{marker} Level {index}: {item}")
    if snapshot.get("current_exercise"):
        lines.append(f"Current exercise: {snapshot['current_exercise']}")
    if snapshot.get("struggle"):
        lines.append(f"Adapt for: {snapshot['struggle']}")
    return "\n".join(lines)


def directive(message: str) -> str:
    """Bounded prompt aid for the existing agent turn, never a new model call."""
    text = _clean(message).casefold()
    if not re.search(r"\b(teach|learn|lesson|continue|beginner|from zero)\b", text):
        return ""
    return (
        "[Learning Mode: establish the learner's level only if it is genuinely unknown; then teach one useful "
        "concept in plain language, give one small practical exercise, and say what evidence you will review next. "
        "Do not dump a textbook. For a formal new/continued path, call the learning_mode tool so explicit progress "
        "is saved locally. Adapt after the learner reports difficulty; do not claim progress that they did not report.]"
    )


def _publish(event_type: str, payload: dict[str, Any]) -> None:
    try:
        from reyes_agent import event_bus

        event_bus.publish(event_type, payload, source="learning_mode")
    except Exception:  # noqa: BLE001 -- progress recording must never block conversation
        pass
