"""What the owner is reading and watching -- a small local shelf.

So "where was I in Solo Leveling?" has an answer, and "what am I in the
middle of?" lists it. Local SQLite, same idiom as ZENO's other stores. It
records progress the owner tells it; it does not track them anywhere.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reyes_agent import config

_DB = Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT))) / "ZENO" / "anime" / "shelf.sqlite"

STATUSES = ("watching", "reading", "completed", "on_hold", "dropped", "planned")


@dataclass
class Entry:
    title: str
    kind: str
    status: str
    progress: int
    total: int | None
    note: str
    updated: float

    def as_dict(self) -> dict[str, Any]:
        unit = "ep" if self.kind == "anime" else "ch"
        where = f"{self.progress}" + (f"/{self.total}" if self.total else "")
        return {"title": self.title, "type": self.kind, "status": self.status,
                "progress": f"{where} {unit}", "note": self.note,
                "updated": self.updated}


class Shelf:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db = db_path or _DB
        self._db.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(self._db, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS shelf(
                    title TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'planned',
                    progress INTEGER NOT NULL DEFAULT 0,
                    total INTEGER,
                    note TEXT NOT NULL DEFAULT '',
                    updated REAL NOT NULL,
                    PRIMARY KEY (title, kind))""")

    def track(self, title: str, kind: str, *, status: str = "", progress: int | None = None,
              total: int | None = None, note: str = "") -> bool:
        title = str(title or "").strip()
        kind = "anime" if str(kind).lower().startswith("a") else "manga"
        if not title:
            return False
        status = status if status in STATUSES else ""
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM shelf WHERE title=? AND kind=?",
                               (title, kind)).fetchone()
            new = {
                "status": status or (row["status"] if row else ("watching" if kind == "anime" else "reading")),
                "progress": progress if progress is not None else (row["progress"] if row else 0),
                "total": total if total is not None else (row["total"] if row else None),
                "note": note or (row["note"] if row else ""),
            }
            conn.execute(
                "INSERT INTO shelf(title,kind,status,progress,total,note,updated) "
                "VALUES(?,?,?,?,?,?,?) ON CONFLICT(title,kind) DO UPDATE SET "
                "status=excluded.status, progress=excluded.progress, "
                "total=excluded.total, note=excluded.note, updated=excluded.updated",
                (title, kind, new["status"], new["progress"], new["total"],
                 str(new["note"])[:300], time.time()))
        return True

    def get(self, title: str, kind: str = "") -> Entry | None:
        with self._connection() as conn:
            if kind:
                kind = "anime" if str(kind).lower().startswith("a") else "manga"
                row = conn.execute("SELECT * FROM shelf WHERE title=? AND kind=?",
                                   (title.strip(), kind)).fetchone()
            else:
                row = conn.execute("SELECT * FROM shelf WHERE title=? ORDER BY updated DESC",
                                   (title.strip(),)).fetchone()
        return _entry(row) if row else None

    def shelf(self, *, status: str = "", kind: str = "", limit: int = 50) -> list[Entry]:
        clauses, args = [], []
        if status in STATUSES:
            clauses.append("status=?"); args.append(status)
        if kind:
            clauses.append("kind=?"); args.append("anime" if str(kind).lower().startswith("a") else "manga")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM shelf{where} ORDER BY updated DESC LIMIT ?",
                (*args, max(1, min(limit, 200)))).fetchall()
        return [_entry(r) for r in rows]

    def remove(self, title: str, kind: str = "") -> bool:
        with self._connection() as conn:
            if kind:
                kind = "anime" if str(kind).lower().startswith("a") else "manga"
                n = conn.execute("DELETE FROM shelf WHERE title=? AND kind=?",
                                 (title.strip(), kind)).rowcount
            else:
                n = conn.execute("DELETE FROM shelf WHERE title=?", (title.strip(),)).rowcount
        return bool(n)


def _entry(row: sqlite3.Row) -> Entry:
    return Entry(title=row["title"], kind=row["kind"], status=row["status"],
                 progress=row["progress"], total=row["total"], note=row["note"],
                 updated=row["updated"])


_shelf: Shelf | None = None
_lock = threading.Lock()


def get_shelf() -> Shelf:
    global _shelf
    with _lock:
        if _shelf is None:
            _shelf = Shelf()
        return _shelf


def reset_for_tests(db_path: Path | None = None) -> Shelf:
    global _shelf
    with _lock:
        _shelf = Shelf(db_path)
        return _shelf
