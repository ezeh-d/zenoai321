"""A tracker for the user's income work -- job applications, freelance
leads/clients, and content pieces -- so nothing falls through the cracks
across all of them at once.

One flexible table rather than three: `kind` distinguishes job /
freelance / content, `status` is free text so each kind can use its own
pipeline (job: saved -> applied -> interview -> offer; freelance: lead ->
proposal -> won -> delivered; content: idea -> drafting -> posted).

REYES helps produce the actual CVs / cover letters / proposals / content
(that's conversation + write_note / write_project_file / generate_image);
this just keeps the running record of where each opportunity stands. The
user always does the real submit/send -- REYES never auto-applies.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime

from reyes_agent import config
from reyes_agent.tools import register

_DB_PATH = config.VAULT_PATH / "07-System" / "heartbeat" / "state.db"
_KINDS = ("job", "freelance", "content")


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS work_tracker ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, title TEXT, "
        "org TEXT, status TEXT, link TEXT, notes TEXT, "
        "created TEXT, updated TEXT)"
    )
    return conn


@register(
    name="track_work",
    description=(
        "Add an income opportunity to the tracker -- a job application, a "
        "freelance lead/client, or a content piece. Use when the user "
        "applies somewhere, lands a lead, or starts a piece of content, so "
        "there's a running record. Does NOT apply or send anything."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(_KINDS), "description": "job, freelance, or content."},
            "title": {"type": "string", "description": "Role title, gig name, or content topic."},
            "org": {"type": "string", "description": "Company, client, or platform (optional)."},
            "status": {"type": "string", "description": "e.g. saved/applied/interview, lead/proposal/won, idea/drafting/posted."},
            "link": {"type": "string", "description": "URL to the posting/gig/post (optional)."},
            "notes": {"type": "string", "description": "Any extra detail (optional)."},
        },
        "required": ["kind", "title"],
    },
    light=True,
)
def track_work(kind: str, title: str, org: str = "", status: str = "", link: str = "", notes: str = "") -> str:
    kind = kind.strip().lower()
    if kind not in _KINDS:
        return f"kind must be one of: {', '.join(_KINDS)}."
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO work_tracker (kind, title, org, status, link, notes, created, updated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (kind, title.strip(), org.strip(), status.strip() or "new", link.strip(), notes.strip(), now, now),
        )
        new_id = cur.lastrowid
    return f"Tracked #{new_id}: [{kind}] {title}" + (f" @ {org}" if org else "") + f" -- {status.strip() or 'new'}."


@register(
    name="list_work",
    description=(
        "List tracked income opportunities -- job applications, freelance "
        "leads, and content -- optionally filtered by kind or status. Use "
        "for 'what have I applied to', 'my freelance pipeline', 'what "
        "content is in progress', or a full overview."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(_KINDS), "description": "Filter to one kind (optional)."},
            "status": {"type": "string", "description": "Filter to a status substring (optional)."},
        },
    },
    light=True,
)
def list_work(kind: str = "", status: str = "") -> str:
    query = "SELECT id, kind, title, org, status, updated FROM work_tracker"
    clauses, params = [], []
    if kind.strip():
        clauses.append("kind = ?")
        params.append(kind.strip().lower())
    if status.strip():
        clauses.append("LOWER(status) LIKE ?")
        params.append(f"%{status.strip().lower()}%")
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY kind, updated DESC"
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    if not rows:
        return "Nothing tracked yet." if not (kind or status) else "Nothing matches that filter."
    lines = []
    current_kind = None
    for wid, k, title, org, st, updated in rows:
        if k != current_kind:
            lines.append(f"\n{k.upper()}:")
            current_kind = k
        lines.append(f"  #{wid} {title}" + (f" @ {org}" if org else "") + f" -- {st} (updated {updated})")
    return "\n".join(lines).strip()


@register(
    name="update_work_status",
    description="Update the status of a tracked opportunity by its ID (see list_work for IDs).",
    input_schema={
        "type": "object",
        "properties": {
            "work_id": {"type": "integer", "description": "The tracked item's ID."},
            "status": {"type": "string", "description": "The new status."},
        },
        "required": ["work_id", "status"],
    },
    light=True,
)
def update_work_status(work_id: int, status: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE work_tracker SET status = ?, updated = ? WHERE id = ?",
            (status.strip(), now, work_id),
        )
        if cur.rowcount == 0:
            return f"No tracked item #{work_id}."
        row = conn.execute("SELECT title FROM work_tracker WHERE id = ?", (work_id,)).fetchone()
    return f"Updated #{work_id} ({row[0]}) -> {status.strip()}."
