"""Short/long-term conversation memory backed by SQLite."""
from __future__ import annotations

import os
import sqlite3
import time


class ConversationMemory:
    def __init__(self, data_dir: str = "./data"):
        os.makedirs(data_dir, exist_ok=True)
        self.path = os.path.join(data_dir, "reyes.db")
        self.conn = sqlite3.connect(self.path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                role    TEXT NOT NULL,
                content TEXT NOT NULL,
                ts      REAL NOT NULL
            )
            """
        )
        self.conn.commit()

    def add(self, role: str, content: str) -> None:
        self.conn.execute(
            "INSERT INTO messages (role, content, ts) VALUES (?, ?, ?)",
            (role, content, time.time()),
        )
        self.conn.commit()

    def recent(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    def clear(self) -> None:
        self.conn.execute("DELETE FROM messages")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
