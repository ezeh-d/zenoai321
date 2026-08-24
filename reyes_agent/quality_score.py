"""Measured quality aggregates; absence of evidence is reported as None."""
from __future__ import annotations

import threading
import sqlite3
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from reyes_agent import config

_DB = config.VAULT_PATH / "07-System" / "heartbeat" / (
    "test-state.db" if config.ZENO_ENV == "test" else "state.db")


@dataclass
class QualityDimension:
    name: str
    score: float | None
    samples: int
    weight: float
    source: str

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class _Reputation:
    def __init__(self, capacity: int = 500) -> None:
        self._lock = threading.RLock()
        self._values: dict[tuple[str, str], deque[bool]] = defaultdict(lambda: deque(maxlen=capacity))

    def record(self, subject: str, task: str, ok: bool) -> None:
        with self._lock:
            self._values[(str(subject), str(task))].append(bool(ok))

    def score(self, subject: str, task: str = "") -> dict[str, Any]:
        with self._lock:
            groups = [list(values) for (name, kind), values in self._values.items()
                      if name == subject and (not task or kind == task)]
        values = [value for group in groups for value in group]
        return {"subject": subject, "task": task, "samples": len(values),
                "score": round(100 * sum(values) / len(values), 2) if values else None}


class ModelReputationService(_Reputation):
    pass


class AgentQualityService(_Reputation):
    pass


class QualityScoreEngine:
    WEIGHTS = {
        "Tool Execution": 2.0, "Verification": 2.0, "Recovery": 1.5,
        "Agents": 1.5, "Conversation": 2.0, "Voice": 2.0,
        "Browser": 1.5, "Desktop": 1.5, "Phone Routing": 1.5,
        "Memory": 1.5, "Cross-device": 1.5,
    }

    def _connect(self) -> sqlite3.Connection:
        _DB.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(_DB, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE IF NOT EXISTS quality_measurements(
          dimension TEXT PRIMARY KEY, passed INTEGER, total INTEGER,
          weight REAL, source TEXT, measured_at REAL)""")
        return conn

    def record_measurement(self, dimension: str, *, passed: int, total: int,
                           source: str, weight: float = 1.0) -> dict[str, Any]:
        passed, total = max(0, int(passed)), max(0, int(total))
        if not dimension.strip() or not source.strip() or total <= 0 or passed > total:
            raise ValueError("quality measurements require a name, source and 0 <= passed <= total")
        with self._connect() as conn:
            conn.execute("INSERT INTO quality_measurements VALUES(?,?,?,?,?,?) "
                         "ON CONFLICT(dimension) DO UPDATE SET passed=excluded.passed,total=excluded.total,"
                         "weight=excluded.weight,source=excluded.source,measured_at=excluded.measured_at",
                         (dimension, passed, total, max(0.1, float(weight)), source, time.time()))
        return {"dimension": dimension, "passed": passed, "total": total,
                "score": round(100 * passed / total, 2), "source": source}

    def _persisted_dimensions(self) -> list[QualityDimension]:
        try:
            with self._connect() as conn:
                rows = conn.execute("SELECT * FROM quality_measurements ORDER BY dimension").fetchall()
            return [QualityDimension(row["dimension"], round(100 * row["passed"] / row["total"], 2),
                                     int(row["total"]), float(row["weight"]), row["source"])
                    for row in rows if row["total"] > 0]
        except Exception:
            return []

    def dimensions(self) -> list[QualityDimension]:
        rows: list[QualityDimension] = []
        try:
            from reyes_agent.tool_reputation import get_reputation
            snapshot = get_reputation().all_reputations()
            samples = sum(int(row.get("samples", 0)) for row in snapshot)
            successes = sum(float(row.get("success_rate", 0)) * int(row.get("samples", 0))
                            for row in snapshot)
            score = round(100 * successes / samples, 2) if samples else None
            rows.append(QualityDimension("Tool Execution", score, samples, 2.0, "tool_reputation"))
        except Exception:
            rows.append(QualityDimension("Tool Execution", None, 0, 2.0, "unavailable"))
        try:
            from reyes_agent.evidence_ledger import get_evidence_ledger
            stats = get_evidence_ledger().stats()
            rate = stats["verification_rate"]
            rows.append(QualityDimension("Verification", round(rate * 100, 2) if rate is not None else None,
                                         stats["total"], 2.0, "evidence_ledger"))
        except Exception:
            rows.append(QualityDimension("Verification", None, 0, 2.0, "unavailable"))
        rows.extend(self._persisted_dimensions())
        return rows

    def score(self) -> dict[str, Any]:
        dimensions = self.dimensions()
        measured = [d for d in dimensions if d.score is not None and d.samples > 0]
        total_weight = sum(d.weight for d in measured)
        score = (round(sum(float(d.score) * d.weight for d in measured) / total_weight, 2)
                 if total_weight else None)
        return {"score": score, "measured_dimensions": len(measured),
                "unmeasured_dimensions": [d.name for d in dimensions if d.score is None],
                "dimensions": [d.as_dict() for d in dimensions],
                "promotable": score is not None and score >= 90 and len(measured) >= 2}

    def release_gate(self, baseline: float | None, maximum_drop: float = 2.0) -> dict[str, Any]:
        current = self.score()["score"]
        if baseline is None or current is None:
            return {"promote": False, "reason": "insufficient measured baseline", "current": current}
        drop = round(float(baseline) - float(current), 2)
        return {"promote": drop <= maximum_drop, "baseline": baseline, "current": current,
                "drop": drop, "maximum_drop": maximum_drop}


_quality = QualityScoreEngine()
_model_reputation = ModelReputationService()
_agent_quality = AgentQualityService()


def get_quality_score() -> QualityScoreEngine:
    return _quality


def get_model_reputation() -> ModelReputationService:
    return _model_reputation


def get_agent_quality() -> AgentQualityService:
    return _agent_quality
