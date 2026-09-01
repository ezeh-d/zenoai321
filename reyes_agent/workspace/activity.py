"""Truthful, bounded user-facing activity projection."""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from typing import Any, Callable

from reyes_agent.workspace.manager import RevisionClock
from reyes_agent.workspace.models import ActivityRecord, ActivityStatus
from reyes_agent.workspace.redaction import redact_text, safe_text, sanitize_mapping

_KNOWN_PREFIXES = {
    "tool", "build", "project", "execution", "website", "agent", "mission",
    "file", "browser", "download", "system", "panel", "app", "message",
}
_DONE = {"COMPLETED", "SUCCEEDED", "SUCCESS", "RETURNED", "VERIFIED"}
_FAILED = {"FAILED", "ERROR", "TIMED_OUT", "TIMEOUT", "BROKEN"}
_WAITING = {"WAITING", "PENDING", "WAITING_FOR_APPROVAL", "AUTH_REQUIRED"}


def _status(value: object, event_type: str) -> ActivityStatus:
    state = safe_text(value, 40).upper()
    suffix = event_type.rsplit(".", 1)[-1].upper()
    current = state or suffix
    if current in _FAILED or suffix in _FAILED:
        return ActivityStatus.FAILED
    if current in {"CANCELLED", "CANCELED"} or suffix in {"CANCELLED", "CANCELED"}:
        return ActivityStatus.CANCELLED
    if current in _WAITING or suffix in _WAITING:
        return ActivityStatus.WAITING
    if current in _DONE or suffix in _DONE:
        return ActivityStatus.SUCCEEDED
    if current in {"PLANNING", "STARTED", "STARTING"}:
        return ActivityStatus.PENDING
    return ActivityStatus.RUNNING


def _category(operation: str, prefix: str) -> str:
    folded = operation.casefold()
    for marker, category in (
        ("file", "files"), ("document", "documents"), ("browser", "browser"),
        ("download", "downloads"), ("message", "messages"), ("agent", "agents"),
        ("system", "system"), ("media", "media"), ("spotify", "media"),
        ("code", "coding"), ("terminal", "terminal"),
    ):
        if marker in folded:
            return category
    return "coding" if prefix in {"build", "project", "website"} else prefix


def _panel_for(category: str) -> str:
    return category if category in {
        "files", "documents", "browser", "downloads", "messages", "agents",
        "system", "media", "coding", "terminal",
    } else "activity"


class ActivityProjector:
    def __init__(self, revisions: RevisionClock, *, max_live: int = 100,
                 clock: Callable[[], float] = time.time) -> None:
        self.revisions = revisions
        self._max_live = max(1, min(int(max_live), 500))
        self._clock = clock
        self._lock = threading.RLock()
        self._records: OrderedDict[str, ActivityRecord] = OrderedDict()
        self._keys: dict[str, str] = {}

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

    def consume(self, event: object) -> ActivityRecord | None:
        raw = self._event(event)
        event_type = safe_text(raw.get("type"), 80)
        source = safe_text(raw.get("source"), 40).casefold()
        if not event_type or event_type.startswith("workspace.") or source == "workspace":
            return None
        prefix = event_type.split(".", 1)[0].casefold()
        payload = sanitize_mapping(raw.get("payload") or {})
        if prefix not in _KNOWN_PREFIXES and payload.get("user_visible") is not True:
            return None

        task = payload.get("task") if isinstance(payload.get("task"), dict) else {}
        project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
        body = task or project or payload
        correlation = safe_text(
            raw.get("correlation_id") or body.get("task_id") or body.get("id") or raw.get("id"),
            80,
        )
        operation = safe_text(
            payload.get("tool") or payload.get("action") or body.get("title") or
            body.get("name") or event_type,
            100,
        )
        category = _category(operation, prefix)
        current_status = _status(
            body.get("state") or body.get("current_status") or payload.get("status"),
            event_type,
        )
        detail = redact_text(
            body.get("error_details") or body.get("error") or payload.get("result") or
            payload.get("detail") or ((body.get("current_step") or {}).get("label")
                                      if isinstance(body.get("current_step"), dict) else ""),
            500,
        )
        progress_value = body.get("progress_percent", payload.get("progress"))
        progress: float | None = None
        if isinstance(progress_value, (int, float)) and not isinstance(progress_value, bool):
            progress = max(0.0, min(float(progress_value), 100.0))
        title = safe_text(body.get("title") or body.get("name") or operation.replace("_", " "), 300)
        key = f"{correlation}:{prefix}:{operation.casefold()}"
        activity_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        now = self._clock()
        event_time = raw.get("ts") if isinstance(raw.get("ts"), (int, float)) else now

        with self._lock:
            previous_id = self._keys.get(key)
            previous = self._records.get(previous_id or "")
            finished = now if current_status in {
                ActivityStatus.SUCCEEDED, ActivityStatus.FAILED, ActivityStatus.CANCELLED} else 0.0
            expires = now + 5.0 if current_status is ActivityStatus.SUCCEEDED else 0.0
            record = ActivityRecord(
                activity_id=previous.activity_id if previous else activity_id,
                correlation_id=correlation,
                category=category,
                status=current_status,
                title=title,
                safe_detail=detail,
                progress=progress,
                progress_unit="percent" if progress is not None else "",
                importance="high" if current_status is ActivityStatus.FAILED else "normal",
                panel_target=_panel_for(category),
                result_reference=redact_text(
                    body.get("output_path") or body.get("preview_url") or
                    payload.get("file") or payload.get("url"), 300),
                retryability="safe" if payload.get("retryable") is True else "none",
                started_at=previous.started_at if previous else float(event_time),
                updated_at=now,
                finished_at=finished,
                expires_at=expires,
                revision=self.revisions.next(),
            )
            self._records[record.activity_id] = record
            self._records.move_to_end(record.activity_id)
            self._keys[key] = record.activity_id
            while len(self._records) > self._max_live:
                removed_id, _ = self._records.popitem(last=False)
                self._keys = {item_key: item_id for item_key, item_id in self._keys.items()
                              if item_id != removed_id}
            return record

    def _expire(self) -> None:
        now = self._clock()
        expired = [item_id for item_id, item in self._records.items()
                   if item.expires_at and item.expires_at <= now]
        for item_id in expired:
            self._records.pop(item_id, None)
        if expired:
            removed = set(expired)
            self._keys = {key: item_id for key, item_id in self._keys.items()
                          if item_id not in removed}

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            self._expire()
            return [item.as_dict() for item in sorted(
                self._records.values(), key=lambda value: (-value.updated_at, -value.revision))]
