"""Bounded attributed research records, never executable strategy source."""
from contextlib import closing
import json
import sqlite3
import time


def notes(path, record=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=5)) as conn, conn:
        conn.execute("CREATE TABLE IF NOT EXISTS hx_research (id INTEGER PRIMARY KEY, data TEXT)")
        if record is not None:
            allowed = {"hypothesis", "source", "source_quality", "classification", "test_plan", "contradictions"}
            if set(record) - allowed or not record.get("hypothesis") or not record.get("source"):
                raise ValueError("Hypothesis and source required; unsupported fields rejected")
            if record.get("classification") not in {"FACT", "PRINCIPLE", "OBSERVATION", "HYPOTHESIS", "OPINION", "UNVERIFIED"}:
                raise ValueError("Explicit knowledge classification required")
            if record.get("source_quality") not in {"HIGH", "MEDIUM", "LOW"}:
                raise ValueError("Source quality label required")
            encoded = json.dumps(record, allow_nan=False)
            if len(encoded) > 12000:
                raise ValueError("Research note too large")
            record = {**record, "created_at": time.time(), "status": "RESEARCHING",
                      "source_verified": False, "strategy_promoted": False}
            conn.execute("INSERT INTO hx_research(data) VALUES (?)", (json.dumps(record),))
        return [{"id": f"HX-{i:05d}", **json.loads(data)} for i, data in conn.execute(
            "SELECT id,data FROM hx_research ORDER BY id DESC LIMIT 100")]
