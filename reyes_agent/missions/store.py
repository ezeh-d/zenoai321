"""Durable mission state. The part that has to survive the process dying.

WHY A SEPARATE TABLE
--------------------
ZENO already has a `missions` table, used by `autonomy.py` and others as a
STATUS RECORD -- name, progress, a log. That is not what this needs. Durable
execution needs per-step checkpoints, an attempt count, and an idempotency
key, and bolting those onto a table other code already writes would break
that code. So this owns two new tables and leaves the existing one alone.

THE IDEMPOTENCY KEY IS THE WHOLE DESIGN
---------------------------------------
The brief's requirement is precise: if ZENO restarts halfway through, it
must understand the mission ALREADY EXISTS rather than starting a second
one. That cannot be solved by being careful at the call site -- the call
site is gone, it died with the process. It is solved by making creation
idempotent on a key derived from the request, enforced by a UNIQUE index in
the database. Two `ensure()` calls with the same key cannot produce two
missions even if they race, because SQLite refuses the second insert.

Every write commits immediately. An unflushed checkpoint is not a
checkpoint.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from reyes_agent import config

_lock = threading.RLock()
_ready = False

_SCHEMA = """
CREATE TABLE IF NOT EXISTS zeno_durable_missions (
    mission_id   TEXT PRIMARY KEY,
    key          TEXT NOT NULL,
    title        TEXT NOT NULL,
    description  TEXT DEFAULT '',
    state        TEXT NOT NULL,
    steps        TEXT NOT NULL,
    cursor       INTEGER DEFAULT 0,
    attempts     INTEGER DEFAULT 0,
    result       TEXT DEFAULT '',
    error        TEXT DEFAULT '',
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL,
    heartbeat_at REAL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_zeno_mission_key
    ON zeno_durable_missions(key);
CREATE TABLE IF NOT EXISTS zeno_mission_checkpoints (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    state      TEXT NOT NULL,
    detail     TEXT DEFAULT '',
    payload    TEXT DEFAULT '',
    at         REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_zeno_ckpt_mission
    ON zeno_mission_checkpoints(mission_id, step_index);
"""


def _path() -> Path:
    return Path(config.VAULT_PATH) / "07-System" / "heartbeat" / "state.db"


def _connect() -> sqlite3.Connection:
    global _ready
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=10)
    connection.row_factory = sqlite3.Row
    with _lock:
        if not _ready:
            connection.executescript(_SCHEMA)
            connection.commit()
            _ready = True
    return connection


def reset_schema_flag() -> None:
    """Test hook -- forces the schema to be re-applied on the next connect."""
    global _ready
    with _lock:
        _ready = False


def insert(row: dict[str, Any]) -> bool:
    """Create a mission. False means one with this key already exists."""
    connection = _connect()
    try:
        with connection:
            connection.execute(
                "INSERT INTO zeno_durable_missions "
                "(mission_id, key, title, description, state, steps, cursor, attempts,"
                " result, error, created_at, updated_at, heartbeat_at) "
                "VALUES (:mission_id,:key,:title,:description,:state,:steps,:cursor,"
                ":attempts,:result,:error,:created_at,:updated_at,:heartbeat_at)", row)
        return True
    except sqlite3.IntegrityError:
        # The UNIQUE index did its job. This is the expected path after a
        # restart, not an error.
        return False
    finally:
        connection.close()


def by_key(key: str) -> dict[str, Any] | None:
    connection = _connect()
    try:
        row = connection.execute(
            "SELECT * FROM zeno_durable_missions WHERE key = ?", (key,)).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


def by_id(mission_id: str) -> dict[str, Any] | None:
    connection = _connect()
    try:
        row = connection.execute(
            "SELECT * FROM zeno_durable_missions WHERE mission_id = ?",
            (mission_id,)).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


def update(mission_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = time.time()
    assignments = ", ".join(f"{name} = :{name}" for name in fields)
    connection = _connect()
    try:
        with connection:
            connection.execute(
                f"UPDATE zeno_durable_missions SET {assignments} WHERE mission_id = :mission_id",
                {**fields, "mission_id": mission_id})
    finally:
        connection.close()


def checkpoint(mission_id: str, step_index: int, state: str,
               detail: str = "", payload: Any = None) -> None:
    """Record that a step reached a state. Committed before returning."""
    connection = _connect()
    try:
        with connection:
            connection.execute(
                "INSERT INTO zeno_mission_checkpoints "
                "(mission_id, step_index, state, detail, payload, at) "
                "VALUES (?,?,?,?,?,?)",
                (mission_id, int(step_index), str(state), str(detail)[:1000],
                 json.dumps(payload, default=str)[:4000] if payload is not None else "",
                 time.time()))
            connection.execute(
                "UPDATE zeno_durable_missions SET heartbeat_at = ?, updated_at = ? "
                "WHERE mission_id = ?", (time.time(), time.time(), mission_id))
    finally:
        connection.close()


def checkpoints(mission_id: str) -> list[dict[str, Any]]:
    connection = _connect()
    try:
        rows = connection.execute(
            "SELECT * FROM zeno_mission_checkpoints WHERE mission_id = ? ORDER BY id",
            (mission_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        connection.close()


def list_missions(states: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    connection = _connect()
    try:
        if states:
            marks = ",".join("?" * len(states))
            rows = connection.execute(
                f"SELECT * FROM zeno_durable_missions WHERE state IN ({marks}) "
                "ORDER BY created_at DESC", states).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM zeno_durable_missions ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        connection.close()


def delete(mission_id: str) -> None:
    connection = _connect()
    try:
        with connection:
            connection.execute("DELETE FROM zeno_mission_checkpoints WHERE mission_id = ?",
                               (mission_id,))
            connection.execute("DELETE FROM zeno_durable_missions WHERE mission_id = ?",
                               (mission_id,))
    finally:
        connection.close()
