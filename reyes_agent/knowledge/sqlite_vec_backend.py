"""Pre-v1 sqlite-vec adapter isolated from ZENO's memory schema.

This backend stores and queries caller-supplied numeric embeddings.  It does
not pretend a lexical hash is a semantic model; embedding generation remains
the responsibility of a configured local/provider embedding backend.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable


class SQLiteVecBackend:
    def __init__(self, path: str | Path, dimensions: int):
        self.path = Path(path)
        self.dimensions = max(1, min(int(dimensions), 4096))

    def _connect(self) -> sqlite3.Connection:
        import sqlite_vec
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute("CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, text TEXT NOT NULL, metadata TEXT NOT NULL)")
        conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS vectors USING vec0(embedding float[{self.dimensions}])")
        return conn

    def upsert(self, document_id: str, text: str, embedding: Iterable[float], metadata: dict | None = None) -> dict:
        vector = [float(value) for value in embedding]
        if len(vector) != self.dimensions:
            raise ValueError(f"Expected {self.dimensions} embedding values, received {len(vector)}.")
        conn = self._connect()
        try:
            row = conn.execute("SELECT rowid FROM documents WHERE id = ?", (document_id,)).fetchone()
            if row:
                rowid = int(row[0])
                conn.execute("UPDATE documents SET text = ?, metadata = ? WHERE rowid = ?",
                             (text, json.dumps(metadata or {}, sort_keys=True), rowid))
                conn.execute("DELETE FROM vectors WHERE rowid = ?", (rowid,))
            else:
                cursor = conn.execute("INSERT INTO documents (id, text, metadata) VALUES (?, ?, ?)",
                                      (document_id, text, json.dumps(metadata or {}, sort_keys=True)))
                rowid = int(cursor.lastrowid)
            conn.execute("INSERT INTO vectors(rowid, embedding) VALUES (?, ?)", (rowid, json.dumps(vector)))
            conn.commit()
        finally:
            conn.close()
        return {"ok": True, "verified": True, "evidence": {"document_id": document_id, "dimensions": self.dimensions}}

    def search(self, embedding: Iterable[float], limit: int = 5) -> list[dict]:
        vector = [float(value) for value in embedding]
        if len(vector) != self.dimensions:
            raise ValueError(f"Expected {self.dimensions} embedding values, received {len(vector)}.")
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT d.id, d.text, d.metadata, v.distance FROM vectors v "
                "JOIN documents d ON d.rowid = v.rowid WHERE v.embedding MATCH ? AND k = ? "
                "ORDER BY v.distance",
                (json.dumps(vector), max(1, min(int(limit), 100))),
            ).fetchall()
        finally:
            conn.close()
        return [{"id": row[0], "text": row[1], "metadata": json.loads(row[2]), "distance": float(row[3])}
                for row in rows]
