"""Small temporal fact graph with deduplication and contradiction history."""
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any


class KnowledgeGraph:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=3)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""CREATE TABLE IF NOT EXISTS facts(
            id INTEGER PRIMARY KEY, subject TEXT NOT NULL, predicate TEXT NOT NULL,
            object TEXT NOT NULL, valid_from REAL NOT NULL, valid_to REAL,
            confidence REAL NOT NULL, source TEXT NOT NULL,
            UNIQUE(subject,predicate,object,valid_from))""")
        return conn

    @staticmethod
    def _clean(value: str, field: str) -> str:
        text = " ".join(str(value or "").split())[:500]
        if not text:
            raise ValueError(f"{field} is required")
        return text

    def add(self, subject: str, predicate: str, object_: str, *, at: float | None = None,
            confidence: float = 1.0, source: str = "owner") -> dict[str, Any]:
        subject, predicate, object_ = (self._clean(subject, "subject"), self._clean(predicate, "predicate"), self._clean(object_, "object"))
        at = float(at or time.time())
        confidence = max(0.0, min(1.0, float(confidence)))
        source = self._clean(source, "source")
        with self._lock, closing(self._connect()) as conn:
            active = conn.execute("SELECT * FROM facts WHERE subject=? AND predicate=? AND valid_to IS NULL ORDER BY valid_from DESC", (subject, predicate)).fetchall()
            for row in active:
                if row["object"] == object_:
                    return {"ok": True, "deduplicated": True, **dict(row)}
                conn.execute("UPDATE facts SET valid_to=? WHERE id=?", (at, row["id"]))
            cursor = conn.execute("INSERT INTO facts(subject,predicate,object,valid_from,valid_to,confidence,source) VALUES(?,?,?,?,NULL,?,?)",
                                  (subject, predicate, object_, at, confidence, source))
            conn.commit()
            return {"ok": True, "deduplicated": False, "id": cursor.lastrowid,
                    "subject": subject, "predicate": predicate, "object": object_,
                    "valid_from": at, "valid_to": None, "confidence": confidence, "source": source}

    def query(self, text: str = "", *, include_history: bool = False, limit: int = 30) -> list[dict[str, Any]]:
        words = [word for word in " ".join(str(text or "").split()).casefold().split() if len(word) > 1][:10]
        where = "1=1" if include_history else "valid_to IS NULL"
        params: list[Any] = []
        if words:
            clauses = []
            for word in words:
                clauses.append("lower(subject||' '||predicate||' '||object) LIKE ?")
                params.append(f"%{word}%")
            where += " AND (" + " OR ".join(clauses) + ")"
        params.append(max(1, min(100, int(limit))))
        with self._lock, closing(self._connect()) as conn:
            rows = conn.execute(f"SELECT * FROM facts WHERE {where} ORDER BY valid_from DESC LIMIT ?", params).fetchall()
        return [dict(row) for row in rows]

    def status(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"state": "STANDBY", "facts": 0, "path": str(self.path), "polling": False}
        with self._lock, closing(self._connect()) as conn:
            total = conn.execute("SELECT count(*) FROM facts").fetchone()[0]
            active = conn.execute("SELECT count(*) FROM facts WHERE valid_to IS NULL").fetchone()[0]
        return {"state": "ONLINE", "facts": total, "active": active, "path": str(self.path), "polling": False}
