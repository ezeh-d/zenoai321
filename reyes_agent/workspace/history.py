"""Bounded, redacted execution history projected from real runtime events."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import replace
from typing import Any, Callable

from reyes_agent.workspace.manager import RevisionClock
from reyes_agent.workspace.models import HistoryRecord
from reyes_agent.workspace.redaction import redact_text, safe_text, sanitize_mapping


class HistoryProjector:
    def __init__(self, revisions: RevisionClock, *, max_records: int = 200,
                 clock: Callable[[], float] = time.time) -> None:
        self.revisions = revisions
        self._max_records = max(1, min(int(max_records), 500))
        self._clock = clock
        self._lock = threading.RLock()
        self._records: OrderedDict[str, HistoryRecord] = OrderedDict()

    def record_request(self, correlation_id: str, summary: str) -> HistoryRecord:
        task_id = safe_text(correlation_id, 80)
        now = self._clock()
        with self._lock:
            previous = self._records.get(task_id)
            record = HistoryRecord(
                task_id=task_id,
                request_summary=redact_text(summary, 300),
                status=previous.status if previous else "RUNNING",
                tools=previous.tools if previous else (),
                started_at=previous.started_at if previous else now,
                finished_at=previous.finished_at if previous else 0.0,
                safe_result=previous.safe_result if previous else "",
                result_reference=previous.result_reference if previous else "",
                retryability=previous.retryability if previous else "none",
                linked_attempts=previous.linked_attempts if previous else (),
                revision=self.revisions.next(),
            )
            self._put(record)
            return record

    @staticmethod
    def _event(event: object) -> dict[str, Any]:
        if isinstance(event, dict):
            return event
        converter = getattr(event, "as_dict", None)
        if callable(converter):
            try:
                value = converter()
                return value if isinstance(value, dict) else {}
            except Exception:
                return {}
        return {}

    def consume(self, event: object) -> HistoryRecord | None:
        raw = self._event(event)
        event_type = safe_text(raw.get("type"), 80)
        if not event_type or event_type.startswith("workspace."):
            return None
        payload = sanitize_mapping(raw.get("payload") or {})
        task = payload.get("task") if isinstance(payload.get("task"), dict) else {}
        task_id = safe_text(raw.get("correlation_id") or task.get("task_id") or raw.get("id"), 80)
        if not task_id:
            return None
        with self._lock:
            previous = self._records.get(task_id) or HistoryRecord(
                task_id=task_id,
                request_summary="Recorded runtime activity",
                status="RUNNING",
                started_at=self._clock(),
            )
            tools = list(previous.tools)
            tool = safe_text(payload.get("tool"), 80)
            if tool and tool not in tools:
                tools.append(tool)
            suffix = event_type.rsplit(".", 1)[-1].upper()
            task_state = safe_text(task.get("state") or task.get("current_status"), 40).upper()
            status = task_state or suffix
            if status in {"RETURNED", "COMPLETED", "SUCCEEDED", "VERIFIED"}:
                status = "COMPLETED"
            elif status in {"FAILED", "ERROR", "TIMED_OUT"}:
                status = "FAILED"
            elif status in {"CANCELLED", "CANCELED"}:
                status = "CANCELLED"
            elif status in {"WAITING", "PENDING", "WAITING_FOR_APPROVAL"}:
                status = "WAITING"
            else:
                status = "RUNNING"
            finished = self._clock() if status in {"COMPLETED", "FAILED", "CANCELLED"} else 0.0
            result = redact_text(
                task.get("error_details") or payload.get("result") or payload.get("detail"), 500)
            record = replace(
                previous,
                status=status,
                tools=tuple(tools[:50]),
                finished_at=finished,
                safe_result=result or previous.safe_result,
                result_reference=redact_text(
                    task.get("output_path") or task.get("preview_url") or
                    payload.get("file") or payload.get("url"), 300) or previous.result_reference,
                retryability="safe" if payload.get("retryable") is True else previous.retryability,
                revision=self.revisions.next(),
            )
            self._put(record)
            return record

    def _put(self, record: HistoryRecord) -> None:
        self._records[record.task_id] = record
        self._records.move_to_end(record.task_id)
        while len(self._records) > self._max_records:
            self._records.popitem(last=False)

    def snapshot(self, limit: int = 50) -> list[dict[str, Any]]:
        count = max(1, min(int(limit), self._max_records))
        with self._lock:
            rows = list(self._records.values())[-count:]
            rows.reverse()
            return [item.as_dict() for item in rows]
