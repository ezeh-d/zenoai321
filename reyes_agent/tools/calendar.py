"""A lightweight personal calendar/timetable for REYES.

Not a synced Google/Outlook calendar -- REYES has no OAuth to either and
that wasn't asked for (and would mean a new account/consent flow). This
is a local, REYES-owned schedule: one-off dated events (appointments, a
timetable entry, "remind me at 3pm") stored in the same heartbeat
state.db and checked by the same background loop that already runs
schedule_check -- proven Tier 5 infrastructure, not a second scheduler.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime

from reyes_agent import config
from reyes_agent.tools import register

_DB_PATH = config.VAULT_PATH / "07-System" / "heartbeat" / "state.db"


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS calendar_events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, due_at REAL, "
        "notes TEXT, notified INTEGER DEFAULT 0)"
    )
    return conn


@register(
    name="add_calendar_event",
    description=(
        "Add a dated event/reminder to REYES's own calendar -- an "
        "appointment, a timetable entry, 'remind me at 3pm to call X'. "
        "REYES pushes a notice (and Telegram, if configured) when it's "
        "due. This is a local schedule, not a synced external calendar."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "What the event/reminder is."},
            "when": {
                "type": "string",
                "description": "When it's due, as 'YYYY-MM-DD HH:MM' in 24-hour time.",
            },
            "notes": {"type": "string", "description": "Optional extra detail."},
        },
        "required": ["title", "when"],
    },
)
def add_calendar_event(title: str, when: str, notes: str = "") -> str:
    try:
        due = datetime.strptime(when.strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        return f"Couldn't parse '{when}' -- use 'YYYY-MM-DD HH:MM', e.g. '2026-07-24 15:00'."
    with _connect() as conn:
        conn.execute(
            "INSERT INTO calendar_events (title, due_at, notes) VALUES (?, ?, ?)",
            (title.strip(), due.timestamp(), notes.strip()),
        )
    return f"Added '{title}' for {due.strftime('%a %b %d, %I:%M %p')}."


@register(
    name="list_calendar_events",
    description="List upcoming events on REYES's calendar, soonest first.",
    input_schema={"type": "object", "properties": {}},
)
def list_calendar_events() -> str:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, title, due_at, notes FROM calendar_events "
            "WHERE due_at >= ? ORDER BY due_at ASC",
            (time.time() - 3600,),  # keep anything up to an hour overdue visible
        ).fetchall()
    if not rows:
        return "Nothing on the calendar."
    lines = []
    for eid, title, due_at, notes in rows:
        when = datetime.fromtimestamp(due_at).strftime("%a %b %d, %I:%M %p")
        lines.append(f"#{eid} {when} -- {title}" + (f" ({notes})" if notes else ""))
    return "\n".join(lines)


@register(
    name="cancel_calendar_event",
    description="Remove an event from REYES's calendar by its ID (see list_calendar_events).",
    input_schema={
        "type": "object",
        "properties": {"event_id": {"type": "integer", "description": "The event's ID."}},
        "required": ["event_id"],
    },
)
def cancel_calendar_event(event_id: int) -> str:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM calendar_events WHERE id = ?", (event_id,))
        if cur.rowcount == 0:
            return f"No event #{event_id}."
    return f"Removed event #{event_id}."


def check_due_events() -> None:
    """Called once per heartbeat tick (see heartbeat.py's _tick) -- pushes
    a notice/Telegram push for anything whose time has arrived, then marks
    it notified so it doesn't repeat next tick.
    """
    from reyes_agent import heartbeat

    now = time.time()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, title, notes FROM calendar_events WHERE due_at <= ? AND notified = 0",
            (now,),
        ).fetchall()
        for eid, title, notes in rows:
            message = f"Reminder: {title}" + (f" -- {notes}" if notes else "")
            heartbeat._add_notice("calendar", message)
            if not heartbeat._in_quiet_hours():
                heartbeat._push_to_telegram("calendar", message)
            conn.execute("UPDATE calendar_events SET notified = 1 WHERE id = ?", (eid,))
