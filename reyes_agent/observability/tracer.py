"""Local-first, redacted tracing with optional single external exporter."""
from __future__ import annotations

import os
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from typing import Any, Iterator

from reyes_agent.memory.privacy import redact

_MAX_TRACES = 500


class Tracer:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: deque[dict[str, Any]] = deque(maxlen=_MAX_TRACES)

    @contextmanager
    def span(self, name: str, *, request_id: str = "", attributes: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        record = {"id": uuid.uuid4().hex, "request_id": request_id, "name": name,
                  "started_at": time.time(), "status": "RUNNING",
                  "attributes": self._safe(attributes or {})}
        try:
            yield record
        except Exception as exc:
            record.update(status="ERROR", error=redact(exc, limit=500))
            raise
        else:
            record["status"] = "OK"
        finally:
            record["duration_ms"] = round((time.time() - record["started_at"]) * 1000, 2)
            with self._lock:
                self._records.append(dict(record))
            try:
                from reyes_agent import event_bus
                event_bus.publish("trace.completed", record, source="observability")
            except Exception:
                pass

    @staticmethod
    def _safe(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(k)[:80]: ("[REDACTED]" if any(x in str(k).casefold() for x in ("key", "token", "password", "secret", "cookie")) else Tracer._safe(v))
                    for k, v in list(value.items())[:80]}
        if isinstance(value, (list, tuple)):
            return [Tracer._safe(item) for item in value[:80]]
        return redact(value, limit=2000) if isinstance(value, (str, bytes)) else value

    def snapshot(self, limit: int = 50) -> dict[str, Any]:
        provider = os.environ.get("ZENO_OBSERVABILITY_PROVIDER", "local").strip().casefold() or "local"
        if provider not in {"local", "langfuse", "phoenix"}:
            provider = "local"
        with self._lock:
            records = list(self._records)[-max(1, min(100, limit)):]
        return {"provider": provider, "local_records": records, "capacity": _MAX_TRACES,
                "external_export_started": False,
                "note": "External exporters are lazy and mutually exclusive."}


_tracer = Tracer()


def get_tracer() -> Tracer:
    return _tracer


@contextmanager
def span(name: str, **kwargs: Any):
    with _tracer.span(name, **kwargs) as record:
        yield record
