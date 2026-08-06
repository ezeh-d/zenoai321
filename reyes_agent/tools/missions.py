"""Long-running goals as first-class, trackable objects -- "graduate this
year," "launch the SaaS," "learn ML" -- rather than only living in
scattered conversation. Same shared-SQLite pattern as work.py/calendar.py
(one small table in the existing state.db, no new storage system).

Deliberately real and modest, not the full "Executive Brain"/"Mission
System" spec some sessions ask for: no fabricated risk scores, completion
forecasts, or confidence numbers -- nothing on this architecture actually
computes those honestly, and a fake number is worse than none. What's
here is what's real: a name, a status drawn from an actual state machine,
a progress percentage the user or an agent sets, a plain-text objectives
checklist, and a timestamped log of what happened. ZENO (or a delegated
specialist) updates these as work happens; the user can always ask
"what's my mission status" and get the real current state back.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from reyes_agent import config
from reyes_agent.tools import register

_DB_PATH = config.VAULT_PATH / "07-System" / "heartbeat" / "state.db"

# A real, bounded state machine (per the user's own Mission Mode spec),
# not free text -- so "list active missions" means something consistent.
_STATES = (
    "planning", "researching", "building", "testing", "reviewing",
    "paused", "blocked", "completed", "archived", "cancelled",
)
_OPEN_STATES = tuple(s for s in _STATES if s not in ("completed", "archived", "cancelled"))


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS missions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, description TEXT, "
        "mission_type TEXT, priority TEXT, status TEXT, progress INTEGER, "
        "deadline TEXT, objectives TEXT, log TEXT, created TEXT, updated TEXT)"
    )
    return conn


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


@register(
    name="create_mission",
    description=(
        "Start tracking a long-running goal as a real mission -- 'graduate "
        "with first class', 'launch the SaaS', 'complete SIWES', 'learn "
        "machine learning'. Use when the user describes an objective that "
        "spans more than one conversation, not a one-off task."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Short mission name."},
            "description": {"type": "string", "description": "What success looks like."},
            "mission_type": {"type": "string", "description": "e.g. career, business, learning, project (free text)."},
            "priority": {"type": "string", "enum": ["low", "medium", "high"], "description": "Default medium."},
            "deadline": {"type": "string", "description": "Optional target date, any readable format."},
            "objectives": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional initial checklist of objectives/milestones.",
            },
        },
        "required": ["name", "description"],
    },
    light=True,
)
def create_mission(
    name: str,
    description: str,
    mission_type: str = "",
    priority: str = "medium",
    deadline: str = "",
    objectives: list | None = None,
) -> str:
    priority = priority.strip().lower() or "medium"
    if priority not in ("low", "medium", "high"):
        priority = "medium"
    obj_text = "\n".join(f"[ ] {o.strip()}" for o in (objectives or []) if o.strip())
    now = _now()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO missions (name, description, mission_type, priority, status, progress, "
            "deadline, objectives, log, created, updated) VALUES (?, ?, ?, ?, 'planning', 0, ?, ?, ?, ?, ?)",
            (name.strip(), description.strip(), mission_type.strip(), priority, deadline.strip(),
             obj_text, f"{now} -- mission created", now, now),
        )
        new_id = cur.lastrowid
    try:
        from reyes_agent import intelligence

        intelligence.persist_mission_state(new_id, goal=description.strip(), plan=list(objectives or []),
                                           pending=list(objectives or []), completed=[])
        intelligence.update_situation(active_mission=new_id, current_task=name.strip(), current_step="planning")
    except Exception:  # noqa: BLE001 -- resilient mission creation never depends on telemetry
        pass
    return f"Mission #{new_id} '{name.strip()}' created (status: planning, priority: {priority})."


def list_missions_dicts(include_all: bool = False) -> list[dict]:
    """Structured form for the web panel (JSON, not the LLM-facing text
    block `list_missions` returns) -- same underlying data, different shape
    for a different consumer."""
    query = "SELECT id, name, status, priority, progress, deadline, mission_type FROM missions"
    params: list = []
    if not include_all:
        query += f" WHERE status IN ({','.join('?' for _ in _OPEN_STATES)})"
        params.extend(_OPEN_STATES)
    query += " ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, updated DESC"
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [
        {"id": r[0], "name": r[1], "status": r[2], "priority": r[3], "progress": r[4], "deadline": r[5], "mission_type": r[6]}
        for r in rows
    ]


@register(
    name="list_missions",
    description=(
        "List tracked missions -- by default only open/active ones. Use "
        "for 'what are my missions', 'mission status', 'what am I working "
        "toward'."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "Filter to one exact status (optional). Blank = all open (non completed/archived/cancelled) missions."},
            "include_all": {"type": "boolean", "description": "If true, include completed/archived/cancelled too."},
        },
    },
    light=True,
)
def list_missions(status: str = "", include_all: bool = False) -> str:
    query = "SELECT id, name, status, priority, progress, deadline FROM missions"
    clauses, params = [], []
    status = status.strip().lower()
    if status:
        clauses.append("status = ?")
        params.append(status)
    elif not include_all:
        clauses.append(f"status IN ({','.join('?' for _ in _OPEN_STATES)})")
        params.extend(_OPEN_STATES)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, updated DESC"
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    if not rows:
        return "No missions match." if (status or include_all) else "No active missions right now."
    lines = []
    for mid, name, st, pr, prog, deadline in rows:
        line = f"#{mid} {name} -- {st}, {prog}% done, priority {pr}"
        if deadline:
            line += f", due {deadline}"
        lines.append(line)
    return "\n".join(lines)


@register(
    name="get_mission",
    description="Get full detail on one mission by ID -- description, objectives checklist, and recent log entries.",
    input_schema={
        "type": "object",
        "properties": {"mission_id": {"type": "integer", "description": "The mission's ID (see list_missions)."}},
        "required": ["mission_id"],
    },
    light=True,
)
def get_mission(mission_id: int) -> str:
    with _connect() as conn:
        row = conn.execute(
            "SELECT name, description, mission_type, priority, status, progress, deadline, objectives, log "
            "FROM missions WHERE id = ?", (mission_id,),
        ).fetchone()
    if row is None:
        return f"No mission #{mission_id}."
    name, desc, mtype, pr, st, prog, deadline, objectives, log = row
    out = [f"#{mission_id} {name} ({st}, {prog}%, priority {pr})"]
    if mtype:
        out.append(f"Type: {mtype}")
    if deadline:
        out.append(f"Deadline: {deadline}")
    out.append(f"Description: {desc}")
    if objectives:
        out.append("Objectives:\n" + objectives)
    log_lines = (log or "").strip().split("\n")
    if log_lines:
        out.append("Recent activity:\n" + "\n".join(log_lines[-8:]))
    return "\n\n".join(out)


@register(
    name="update_mission",
    description=(
        "Update a mission's status and/or progress, with a short note logged to its history. "
        "Use as work happens on a mission -- don't let it go stale."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "mission_id": {"type": "integer", "description": "The mission's ID."},
            "status": {"type": "string", "enum": list(_STATES), "description": "New status (optional)."},
            "progress": {"type": "integer", "description": "New progress 0-100 (optional)."},
            "note": {"type": "string", "description": "What happened -- logged with a timestamp."},
        },
        "required": ["mission_id", "note"],
    },
    light=True,
)
def update_mission(mission_id: int, note: str, status: str = "", progress: int | None = None) -> str:
    with _connect() as conn:
        row = conn.execute("SELECT name, status, progress, log FROM missions WHERE id = ?", (mission_id,)).fetchone()
        if row is None:
            return f"No mission #{mission_id}."
        name, cur_status, cur_progress, log = row
        new_status = status.strip().lower() if status.strip() else cur_status
        if new_status not in _STATES:
            return f"status must be one of: {', '.join(_STATES)}."
        new_progress = cur_progress
        if progress is not None:
            new_progress = max(0, min(100, int(progress)))
        now = _now()
        new_log = (log or "") + f"\n{now} -- {note.strip()}"
        if status.strip() and new_status != cur_status:
            new_log += f" (status: {cur_status} -> {new_status})"
        conn.execute(
            "UPDATE missions SET status = ?, progress = ?, log = ?, updated = ? WHERE id = ?",
            (new_status, new_progress, new_log, now, mission_id),
        )
    try:
        from reyes_agent import intelligence

        prior = intelligence.load_mission_state(mission_id) or {}
        completed = list(prior.get("completed", []))
        pending = list(prior.get("pending", []))
        if new_status == "completed" and note.strip() not in completed:
            completed.append(note.strip())
            pending = []
        elif new_status in {"paused", "blocked"} and note.strip() not in pending:
            pending.append(note.strip())
        intelligence.persist_mission_state(mission_id, goal=prior.get("goal", ""), completed=completed,
                                           pending=pending, errors=[note.strip()] if new_status == "blocked" else prior.get("errors", []))
        intelligence.update_situation(active_mission=mission_id, current_task=name, current_step=new_status)
    except Exception:  # noqa: BLE001
        pass
    return f"Mission #{mission_id} '{name}' updated -- {new_status}, {new_progress}%."


@register(
    name="set_mission_objective_done",
    description="Mark one objective in a mission's checklist as done (or not done), matched by text.",
    input_schema={
        "type": "object",
        "properties": {
            "mission_id": {"type": "integer", "description": "The mission's ID."},
            "objective_text": {"type": "string", "description": "Text (or a distinctive substring) of the objective to mark."},
            "done": {"type": "boolean", "description": "True to check it off, false to uncheck. Default true."},
        },
        "required": ["mission_id", "objective_text"],
    },
    light=True,
)
def set_mission_objective_done(mission_id: int, objective_text: str, done: bool = True) -> str:
    with _connect() as conn:
        row = conn.execute("SELECT objectives FROM missions WHERE id = ?", (mission_id,)).fetchone()
        if row is None:
            return f"No mission #{mission_id}."
        objectives = (row[0] or "").split("\n")
        needle = objective_text.strip().lower()
        matched = False
        for i, line in enumerate(objectives):
            body = line[4:].strip() if line[:4] in ("[ ] ", "[x] ") else line.strip()
            if needle in body.lower():
                objectives[i] = f"[{'x' if done else ' '}] {body}"
                matched = True
                break
        if not matched:
            return f"No objective matching '{objective_text}' on mission #{mission_id}."
        now = _now()
        conn.execute(
            "UPDATE missions SET objectives = ?, updated = ? WHERE id = ?",
            ("\n".join(objectives), now, mission_id),
        )
    return f"Marked objective {'done' if done else 'not done'} on mission #{mission_id}."
