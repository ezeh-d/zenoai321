"""Second brain: durable notes & knowledge REYES can save and recall.

Uses plain SQLite so it works out of the box. Search is keyword-based
(ranked by how many query words match). For semantic search later, this
class can be swapped for a ChromaDB-backed one without touching the rest
of the app.
"""
from __future__ import annotations

import os
import re
import sqlite3
import time


class SecondBrain:
    def __init__(self, data_dir: str = "./data"):
        os.makedirs(data_dir, exist_ok=True)
        self.path = os.path.join(data_dir, "reyes.db")
        self.conn = sqlite3.connect(self.path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                tags TEXT DEFAULT '',
                ts   REAL NOT NULL
            )
            """
        )
        self.conn.commit()

    def remember(self, text: str, tags: str = "") -> str:
        cur = self.conn.execute(
            "INSERT INTO notes (text, tags, ts) VALUES (?, ?, ?)",
            (text, tags, time.time()),
        )
        self.conn.commit()
        return f"Saved to your second brain (note #{cur.lastrowid})."

    def recall(self, query: str, k: int = 5) -> str:
        words = [w.lower() for w in re.findall(r"\w+", query) if len(w) > 2]
        rows = self.conn.execute("SELECT id, text, tags FROM notes").fetchall()
        if not rows:
            return "Your second brain is empty so far."

        scored = []
        for nid, text, tags in rows:
            blob = (text + " " + tags).lower()
            score = sum(blob.count(w) for w in words) if words else 0
            if score > 0 or not words:
                scored.append((score, nid, text, tags))

        scored.sort(reverse=True)
        top = scored[:k]
        if not top:
            return f"Nothing in your second brain matches '{query}'."

        out = []
        for score, nid, text, tags in top:
            tag_str = f"  [{tags}]" if tags else ""
            out.append(f"#{nid}{tag_str}: {text}")
        return "\n".join(out)

    def list_notes(self, limit: int = 20) -> str:
        rows = self.conn.execute(
            "SELECT id, text, tags FROM notes ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        if not rows:
            return "No notes yet."
        return "\n".join(
            f"#{nid}" + (f" [{tags}]" if tags else "") + f": {text}"
            for nid, text, tags in rows
        )

    def close(self) -> None:
        self.conn.close()
