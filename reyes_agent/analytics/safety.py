"""Read-only SQL and dataset path policy."""
from __future__ import annotations

import re
from pathlib import Path

_FORBIDDEN = re.compile(
    r"\b(attach|detach|copy|export|install|load|pragma|call|create|drop|alter|insert|update|delete|"
    r"truncate|merge|replace|vacuum|checkpoint|set|reset|force|secret)\b",
    re.I,
)
_EXTERNAL = re.compile(r"\b(read_csv|read_json|read_parquet|httpfs|sqlite_scan|postgres_scan|glob)\s*\(", re.I)


def validate_query(sql: str) -> tuple[bool, str]:
    text = str(sql or "").strip()
    if not text:
        return False, "query is empty"
    if ";" in text.rstrip(";"):
        return False, "multiple SQL statements are not allowed"
    if not re.match(r"^(select|with|describe|summarize)\b", text, re.I):
        return False, "only read-only SELECT/WITH/DESCRIBE/SUMMARIZE queries are allowed"
    if _FORBIDDEN.search(text) or _EXTERNAL.search(text):
        return False, "query contains a blocked statement or external file/network function"
    return True, "read-only query accepted"


def resolve_dataset(path: str | Path, allowed_roots: tuple[Path, ...]) -> Path:
    target = Path(path).expanduser().resolve(strict=True)
    if target.suffix.casefold() not in {".csv", ".json", ".jsonl", ".parquet"}:
        raise ValueError("Supported datasets are CSV, JSON/JSONL and Parquet files.")
    if not any(target == root or root in target.parents for root in allowed_roots):
        raise PermissionError("Dataset is outside the configured analytics roots.")
    if target.stat().st_size > 2 * 1024 * 1024 * 1024:
        raise ValueError("Dataset exceeds the 2 GiB local analysis limit.")
    return target
