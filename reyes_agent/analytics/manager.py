"""DuckDB analysis where numbers come from SQL, not an LLM."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Any

from .safety import resolve_dataset, validate_query


def _default_roots() -> tuple[Path, ...]:
    configured = [Path(item).expanduser().resolve() for item in os.environ.get("ZENO_ANALYTICS_ROOTS", "").split(os.pathsep) if item.strip()]
    if configured:
        return tuple(configured)
    home = Path.home()
    roots = [home / "Desktop", home / "Documents", home / "Downloads", home / "ZENO Projects"]
    return tuple(path.resolve() for path in roots)


class AnalyticsManager:
    def __init__(self, allowed_roots: tuple[Path, ...] | None = None):
        self.allowed_roots = tuple(path.resolve() for path in (allowed_roots or _default_roots()))

    @staticmethod
    def status() -> dict[str, Any]:
        installed = importlib.util.find_spec("duckdb") is not None
        version = ""
        if installed:
            import duckdb
            version = duckdb.__version__
        return {"state": "WORKING" if installed else "NOT_CONFIGURED", "installed": installed,
                "version": version, "read_only_default": True, "polling": False,
                "calculated_results_separate_from_interpretation": True}

    @staticmethod
    def _source_sql(path: Path) -> str:
        escaped = str(path).replace("'", "''")
        suffix = path.suffix.casefold()
        if suffix == ".csv":
            return f"read_csv_auto('{escaped}', sample_size=20000)"
        if suffix == ".parquet":
            return f"read_parquet('{escaped}')"
        return f"read_json_auto('{escaped}', maximum_object_size=16777216)"

    def _connection(self, path: Path):
        import duckdb
        connection = duckdb.connect(":memory:", config={"threads": "2", "memory_limit": "256MB",
                                                          "allow_unsigned_extensions": "false"})
        connection.execute(f"CREATE VIEW dataset AS SELECT * FROM {self._source_sql(path)}")
        return connection

    def inspect(self, path: str | Path) -> dict[str, Any]:
        target = resolve_dataset(path, self.allowed_roots)
        with self._connection(target) as connection:
            schema_rows = connection.execute("DESCRIBE dataset").fetchall()
            row_count = int(connection.execute("SELECT count(*) FROM dataset").fetchone()[0])
            sample = connection.execute("SELECT * FROM dataset LIMIT 5").fetchall()
            columns = [row[0] for row in schema_rows]
        return {"ok": True, "state": "COMPLETED", "verified": True,
                "evidence": {"path": str(target), "bytes": target.stat().st_size, "rows": row_count},
                "schema": [{"name": row[0], "type": row[1], "nullable": row[2]} for row in schema_rows],
                "sample": [dict(zip(columns, row)) for row in sample]}

    def query(self, path: str | Path, sql: str, limit: int = 200) -> dict[str, Any]:
        ok, reason = validate_query(sql)
        if not ok:
            return {"ok": False, "state": "DENIED", "reason": reason}
        target = resolve_dataset(path, self.allowed_roots)
        bounded = max(1, min(int(limit), 1000))
        with self._connection(target) as connection:
            result = connection.execute(f"SELECT * FROM ({sql.rstrip(';')}) AS zeno_result LIMIT {bounded + 1}")
            columns = [item[0] for item in result.description]
            rows = result.fetchall()
        truncated = len(rows) > bounded
        rows = rows[:bounded]
        return {"ok": True, "state": "COMPLETED", "verified": True,
                "evidence": {"engine": "DuckDB", "path": str(target), "returned_rows": len(rows),
                             "truncated": truncated, "query": sql[:1000]},
                "columns": columns, "rows": [dict(zip(columns, row)) for row in rows]}


_MANAGER = AnalyticsManager()


def get_manager() -> AnalyticsManager:
    return _MANAGER
