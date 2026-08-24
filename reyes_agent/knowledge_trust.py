"""Provenance and freshness records for important knowledge claims."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from reyes_agent import config
from reyes_agent.memory.privacy import redact

_DB = config.VAULT_PATH / "07-System" / "heartbeat" / (
    "test-state.db" if config.ZENO_ENV == "test" else "state.db")
BOUNDARIES = {"zeno_project", "t21_business", "personal", "meeting", "class", "temporary_session"}


@dataclass
class TrustedFact:
    fact_id: str
    value: str
    source: str
    confidence: float
    created: float
    last_verified: float
    freshness_s: float
    superseded_by: str = ""
    boundary: str = "temporary_session"

    def as_dict(self) -> dict[str, Any]:
        row = asdict(self)
        age = max(0.0, time.time() - self.last_verified)
        row["fresh"] = bool(self.freshness_s <= 0 or age <= self.freshness_s)
        return row


class KnowledgeTrustEngine:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _DB
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS trusted_facts(
              fact_id TEXT PRIMARY KEY,value TEXT,source TEXT,confidence REAL,
              created REAL,last_verified REAL,freshness_s REAL,superseded_by TEXT,boundary TEXT)""")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def remember(self, value: str, *, source: str, confidence: float,
                 freshness_s: float = 0.0, boundary: str = "temporary_session") -> TrustedFact:
        if boundary not in BOUNDARIES:
            raise ValueError("unknown context boundary")
        if not source.strip():
            raise ValueError("important facts require a source")
        now = time.time()
        fact = TrustedFact(uuid.uuid4().hex, redact(value, limit=4000),
                           redact(source, limit=500), max(0.0, min(1.0, float(confidence))),
                           now, now, max(0.0, float(freshness_s)), boundary=boundary)
        with self._connect() as conn:
            conn.execute("INSERT INTO trusted_facts VALUES(?,?,?,?,?,?,?,?,?)", tuple(asdict(fact).values()))
        return fact

    def verify(self, fact_id: str, *, confidence: float | None = None) -> bool:
        fields, args = ["last_verified=?"], [time.time()]
        if confidence is not None:
            fields.append("confidence=?")
            args.append(max(0.0, min(1.0, float(confidence))))
        args.append(fact_id)
        with self._connect() as conn:
            return bool(conn.execute(f"UPDATE trusted_facts SET {','.join(fields)} WHERE fact_id=?", args).rowcount)

    def supersede(self, fact_id: str, replacement_id: str) -> bool:
        with self._connect() as conn:
            return bool(conn.execute("UPDATE trusted_facts SET superseded_by=? WHERE fact_id=?",
                                     (replacement_id, fact_id)).rowcount)

    def query(self, *, boundary: str = "", include_stale: bool = False,
              limit: int = 100) -> list[dict[str, Any]]:
        clauses, args = ["superseded_by=''"], []
        if boundary:
            if boundary not in BOUNDARIES:
                raise ValueError("unknown context boundary")
            clauses.append("boundary=?")
            args.append(boundary)
        args.append(max(1, min(500, int(limit))))
        with self._connect() as conn:
            rows = conn.execute(f"SELECT * FROM trusted_facts WHERE {' AND '.join(clauses)} "
                                "ORDER BY last_verified DESC LIMIT ?", args).fetchall()
        result = [TrustedFact(**dict(row)).as_dict() for row in rows]
        return result if include_stale else [row for row in result if row["fresh"]]


_engine: KnowledgeTrustEngine | None = None


def get_knowledge_trust() -> KnowledgeTrustEngine:
    global _engine
    if _engine is None:
        _engine = KnowledgeTrustEngine()
    return _engine
