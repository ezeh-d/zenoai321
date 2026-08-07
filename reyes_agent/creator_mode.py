"""Creator and Mastery state on ZENO's existing local state database.

This is deliberately not a second planner, memory vault, agent registry or
background runtime.  It records only owner-started creative projects and
observable practice evidence; the existing conversation/agent pipeline still
does the thinking and the existing project tools still create files.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any

from reyes_agent import config


_LOCK = threading.RLock()
_MAX_TEXT = 300
_STAGES = ("IDEA", "AUDIENCE", "POSITIONING", "IDENTITY", "CONCEPTS", "ASSETS", "LAUNCH")
_CREATOR_RE = re.compile(r"\b(creator mode|create something|i have an idea|build a brand|brand|portfolio|case study)\b", re.I)
_MASTERY_RE = re.compile(r"\b(master|mastery|professional level|assess my|review my work|critique my work)\b", re.I)


def _clean(value: object, limit: int = _MAX_TEXT) -> str:
    return " ".join(str(value or "").split())[:limit]


@contextmanager
def _connection():
    path = config.VAULT_PATH / "07-System" / "heartbeat" / "state.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS creator_projects (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, goal TEXT NOT NULL, stage TEXT NOT NULL,
            completed_json TEXT NOT NULL, files_json TEXT NOT NULL, decisions_json TEXT NOT NULL,
            open_tasks_json TEXT NOT NULL, updated_at REAL NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS mastery_progress (
            subject TEXT PRIMARY KEY, level TEXT NOT NULL, evidence_json TEXT NOT NULL,
            weak_areas_json TEXT NOT NULL, next_challenge TEXT NOT NULL, updated_at REAL NOT NULL)""")
        yield conn
        conn.commit()
    finally:
        conn.close()


def _publish(event_type: str, payload: dict[str, Any]) -> None:
    try:
        from reyes_agent import event_bus
        event_bus.publish(event_type, payload, source="creator_mode")
    except Exception:
        pass


def is_creator_request(message: str) -> bool:
    return bool(_CREATOR_RE.search(str(message or "")))


def is_mastery_request(message: str) -> bool:
    return bool(_MASTERY_RE.search(str(message or "")))


def directive(message: str) -> str:
    text = str(message or "")
    if is_mastery_request(text):
        return ("[Mastery Mode: use progressive, practical difficulty. Assess only evidence the learner supplied; scores are "
                "subjective guidance, not measurements. Do not promote a level just because a lesson ended. Name the most "
                "important fix and one next challenge.]")
    if is_creator_request(text):
        return ("[Creator Mode: keep related creative decisions in one owner project. Establish goal, audience and positioning "
                "before assets when missing. Track real decisions, completed stages, files and open tasks through creator_project; "
                "never claim a logo, mockup, website or launch asset exists without verified tool evidence.]")
    return ""


def _decode(value: str) -> list[str]:
    try:
        return [str(item) for item in json.loads(value) if str(item)][:32]
    except (TypeError, ValueError):
        return []


def _snapshot(row: tuple[Any, ...]) -> dict[str, Any]:
    return {"project_id": row[0], "project_name": row[1], "project_goal": row[2], "current_stage": row[3],
            "completed_stages": _decode(row[4]), "files": _decode(row[5]), "decisions": _decode(row[6]),
            "open_tasks": _decode(row[7]), "updated_at": row[8]}


def start_project(name: object, goal: object, *, project_id: object = "") -> dict[str, Any]:
    project_id = _clean(project_id, 80) or f"creator-{uuid.uuid4().hex[:12]}"
    snapshot = {"project_id": project_id, "project_name": _clean(name, 120) or "Untitled creative project",
                "project_goal": _clean(goal), "current_stage": _STAGES[0], "completed_stages": [], "files": [],
                "decisions": [], "open_tasks": [], "updated_at": time.time()}
    with _LOCK, _connection() as conn:
        conn.execute("INSERT OR REPLACE INTO creator_projects VALUES(?,?,?,?,?,?,?,?,?)", (
            snapshot["project_id"], snapshot["project_name"], snapshot["project_goal"], snapshot["current_stage"],
            "[]", "[]", "[]", "[]", snapshot["updated_at"]))
    _publish("creator.project_started", snapshot)
    return snapshot


def project_status(project_id: object) -> dict[str, Any] | None:
    with _LOCK, _connection() as conn:
        row = conn.execute("SELECT * FROM creator_projects WHERE id=?", (_clean(project_id, 80),)).fetchone()
    return _snapshot(row) if row else None


def update_project(project_id: object, *, stage: object = "", completed_stage: object = "", file: object = "",
                   decision: object = "", open_task: object = "") -> dict[str, Any] | None:
    snapshot = project_status(project_id)
    if snapshot is None:
        return None
    requested_stage = _clean(stage, 60).upper()
    if requested_stage in _STAGES:
        snapshot["current_stage"] = requested_stage
    for key, value in (("completed_stages", completed_stage), ("files", file), ("decisions", decision), ("open_tasks", open_task)):
        item = _clean(value)
        if item and item not in snapshot[key]:
            snapshot[key].append(item)
    snapshot["updated_at"] = time.time()
    with _LOCK, _connection() as conn:
        conn.execute("UPDATE creator_projects SET stage=?,completed_json=?,files_json=?,decisions_json=?,open_tasks_json=?,updated_at=? WHERE id=?", (
            snapshot["current_stage"], json.dumps(snapshot["completed_stages"]), json.dumps(snapshot["files"]),
            json.dumps(snapshot["decisions"]), json.dumps(snapshot["open_tasks"]), snapshot["updated_at"], snapshot["project_id"]))
    _publish("creator.project_updated", snapshot)
    return snapshot


def mastery_status(subject: object) -> dict[str, Any] | None:
    key = _clean(subject, 100).casefold()
    with _LOCK, _connection() as conn:
        row = conn.execute("SELECT subject,level,evidence_json,weak_areas_json,next_challenge,updated_at FROM mastery_progress WHERE subject=?", (key,)).fetchone()
    if not row:
        return None
    return {"subject": row[0], "level": row[1], "evidence": _decode(row[2]), "weak_areas": _decode(row[3]),
            "next_challenge": row[4], "updated_at": row[5]}


def update_mastery(subject: object, *, level: object = "BEGINNER", evidence: object = "", weak_area: object = "",
                   next_challenge: object = "") -> dict[str, Any]:
    key = _clean(subject, 100).casefold() or "general skill"
    snapshot = mastery_status(key) or {"subject": key, "level": "BEGINNER", "evidence": [], "weak_areas": [], "next_challenge": "", "updated_at": 0.0}
    requested_level = _clean(level, 30).upper()
    if requested_level in {"BEGINNER", "FOUNDATION", "PRACTICE", "INTERMEDIATE", "ADVANCED", "CLIENT_PROJECT", "ASSESSMENT"}:
        snapshot["level"] = requested_level
    for key_name, value in (("evidence", evidence), ("weak_areas", weak_area)):
        item = _clean(value)
        if item and item not in snapshot[key_name]:
            snapshot[key_name].append(item)
    if next_challenge:
        snapshot["next_challenge"] = _clean(next_challenge)
    snapshot["updated_at"] = time.time()
    with _LOCK, _connection() as conn:
        conn.execute("INSERT OR REPLACE INTO mastery_progress VALUES(?,?,?,?,?,?)", (
            snapshot["subject"], snapshot["level"], json.dumps(snapshot["evidence"]), json.dumps(snapshot["weak_areas"]),
            snapshot["next_challenge"], snapshot["updated_at"]))
    _publish("mastery.progress_updated", snapshot)
    return snapshot


def format_project(snapshot: dict[str, Any]) -> str:
    next_stage = next((stage for stage in _STAGES if stage not in snapshot["completed_stages"]), snapshot["current_stage"])
    return (f"{snapshot['project_name']} ({snapshot['project_id']})\nGoal: {snapshot['project_goal'] or 'not set'}\n"
            f"Current stage: {snapshot['current_stage']}\nNext stage: {next_stage}\nCompleted: {', '.join(snapshot['completed_stages']) or 'none'}\n"
            f"Open tasks: {', '.join(snapshot['open_tasks']) or 'none'}\nFiles: {', '.join(snapshot['files']) or 'none'}")


def portfolio_case_study(project_id: object) -> str | None:
    """Render an evidence-only case-study outline from a creator project."""
    snapshot = project_status(project_id)
    if snapshot is None:
        return None
    return (f"PROJECT: {snapshot['project_name']}\nBRIEF: {snapshot['project_goal'] or 'not recorded'}\n"
            f"PROCESS: {', '.join(snapshot['decisions']) or 'No decisions recorded yet.'}\n"
            f"FINAL RESULT: {', '.join(snapshot['files']) or 'No verified final file recorded yet.'}\n"
            f"SKILLS USED: {', '.join(snapshot['completed_stages']) or 'No completed stage recorded yet.'}\n"
            f"LESSONS / NEXT TASKS: {', '.join(snapshot['open_tasks']) or 'No open task recorded.'}")
