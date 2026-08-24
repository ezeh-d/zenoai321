"""Redacted durable action evidence and general side-effect idempotency."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from reyes_agent import config
from reyes_agent.memory.privacy import redact

_DB = config.VAULT_PATH / "07-System" / "heartbeat" / (
    "test-state.db" if config.ZENO_ENV == "test" else "state.db"
)


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k)[:80]: ("[REDACTED]" if any(x in str(k).casefold()
                for x in ("password", "secret", "token", "cookie", "api_key")) else _safe(v))
                for k, v in list(value.items())[:100]}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value[:100]]
    return redact(value, limit=2000) if isinstance(value, (str, bytes)) else value


@dataclass
class ActionEvidence:
    command_id: str
    source_device: str
    executing_device: str
    agent: str
    capability: str
    provider: str
    target: str
    result: str
    verification: str
    external_result_id: str = ""
    trace_id: str = ""
    timestamp: float = 0.0


class EvidenceLedger:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _DB
        self._lock = threading.RLock()
        self._schema()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def _schema(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS action_evidence(
                  id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL NOT NULL,
                  command_id TEXT, source_device TEXT, executing_device TEXT,
                  agent TEXT, capability TEXT, provider TEXT, target TEXT,
                  result TEXT, verification TEXT, external_result_id TEXT, trace_id TEXT);
                CREATE INDEX IF NOT EXISTS idx_action_evidence_time ON action_evidence(timestamp);
                CREATE INDEX IF NOT EXISTS idx_action_evidence_command ON action_evidence(command_id);
                CREATE TABLE IF NOT EXISTS side_effect_claims(
                  claim_key TEXT PRIMARY KEY, operation TEXT, target TEXT,
                  status TEXT, result_id TEXT, claimed_at REAL, updated_at REAL);
            """)

    def record(self, evidence: ActionEvidence | None = None, **fields: Any) -> str:
        item = evidence or ActionEvidence(**fields)
        item.timestamp = float(item.timestamp or time.time())
        values = asdict(item)
        for key in ("target", "result"):
            values[key] = str(_safe(values[key]))[:2000]
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO action_evidence(timestamp,command_id,source_device,executing_device,"
                "agent,capability,provider,target,result,verification,external_result_id,trace_id) "
                "VALUES(:timestamp,:command_id,:source_device,:executing_device,:agent,:capability,"
                ":provider,:target,:result,:verification,:external_result_id,:trace_id)", values)
            evidence_id = str(cursor.lastrowid)
        return evidence_id

    def history(self, *, command_id: str = "", agent: str = "", capability: str = "",
                since: float = 0.0, limit: int = 100) -> list[dict[str, Any]]:
        clauses, args = ["timestamp>=?"], [float(since)]
        for column, value in (("command_id", command_id), ("agent", agent),
                              ("capability", capability)):
            if value:
                clauses.append(f"{column}=?")
                args.append(value)
        args.append(max(1, min(500, int(limit))))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM action_evidence WHERE {' AND '.join(clauses)} "
                "ORDER BY timestamp DESC LIMIT ?", args).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) total, "
                               "SUM(verification='VERIFIED') verified, "
                               "SUM(verification='FAILED') failed FROM action_evidence").fetchone()
        total = int(row["total"] or 0)
        return {"total": total, "verified": int(row["verified"] or 0),
                "failed": int(row["failed"] or 0),
                "verification_rate": (round(int(row["verified"] or 0) / total, 4)
                                      if total else None)}


class SideEffectLedger:
    """Claim-before-execute guard. A completed claim is never executed twice."""

    def __init__(self, ledger: EvidenceLedger | None = None) -> None:
        self.ledger = ledger or get_evidence_ledger()

    @staticmethod
    def key(operation: str, target: str, idempotency_key: str = "") -> str:
        raw = idempotency_key or f"{operation}\0{target}"
        return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()

    def claim(self, operation: str, target: str, *, idempotency_key: str = "") -> dict[str, Any]:
        key = self.key(operation, target, idempotency_key)
        now = time.time()
        with self.ledger._lock, self.ledger._connect() as conn:
            try:
                conn.execute("INSERT INTO side_effect_claims VALUES(?,?,?,?,?,?,?)",
                             (key, operation, str(_safe(target))[:1000], "CLAIMED", "", now, now))
                return {"claimed": True, "claim_key": key, "status": "CLAIMED"}
            except sqlite3.IntegrityError:
                row = conn.execute("SELECT status,result_id FROM side_effect_claims WHERE claim_key=?",
                                   (key,)).fetchone()
                return {"claimed": False, "claim_key": key, "status": row["status"],
                        "result_id": row["result_id"]}

    def complete(self, claim_key: str, result_id: str = "") -> bool:
        with self.ledger._connect() as conn:
            changed = conn.execute("UPDATE side_effect_claims SET status='COMPLETED',result_id=?,"
                                   "updated_at=? WHERE claim_key=? AND status='CLAIMED'",
                                   (str(result_id)[:500], time.time(), claim_key)).rowcount
        return bool(changed)

    def fail(self, claim_key: str) -> bool:
        with self.ledger._connect() as conn:
            changed = conn.execute("UPDATE side_effect_claims SET status='FAILED',updated_at=? "
                                   "WHERE claim_key=? AND status='CLAIMED'",
                                   (time.time(), claim_key)).rowcount
        return bool(changed)


ActionHistory = EvidenceLedger
IdempotencyStore = SideEffectLedger
ExecutionClaim = dict[str, Any]

_ledger: EvidenceLedger | None = None
_ledger_lock = threading.Lock()


def get_evidence_ledger() -> EvidenceLedger:
    global _ledger
    with _ledger_lock:
        if _ledger is None:
            _ledger = EvidenceLedger()
        return _ledger
