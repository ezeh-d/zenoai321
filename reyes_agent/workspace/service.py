"""One composed authority for workspace state and Event Bus projections."""

from __future__ import annotations

import queue
import threading
import time
from typing import Any

from reyes_agent.workspace.activity import ActivityProjector
from reyes_agent.workspace.defaults import default_command_registry, default_panel_registry
from reyes_agent.workspace.history import HistoryProjector, RetryStore
from reyes_agent.workspace.intent_router import PanelIntentRouter
from reyes_agent.workspace.manager import RevisionClock, WorkspaceManager
from reyes_agent.workspace.models import PresentationMode, PresentationPlan
from reyes_agent.workspace.redaction import redact_text, safe_text, secret_free
from reyes_agent.workspace.search import WorkspaceSearch
from reyes_agent.workspace.tool_health import ToolHealthManager


class WorkspaceService:
    def __init__(self, *, bus: Any = None, worker_pool: Any = None,
                 tool_runner: Any = None, clock: Any = time.time) -> None:
        self._bus_override = bus
        self._worker_pool_override = worker_pool
        self._tool_runner_override = tool_runner
        self._clock = clock
        self.revisions = RevisionClock()
        self.panels = default_panel_registry()
        self.commands = default_command_registry()
        self.manager = WorkspaceManager(
            self.panels, publish=self._publish, revisions=self.revisions)
        self.router = PanelIntentRouter(self.panels)
        self.activities = ActivityProjector(self.revisions)
        self.history = HistoryProjector(self.revisions)
        self._retries = RetryStore(clock=clock)
        self.health = ToolHealthManager(revisions=self.revisions)
        self.search = WorkspaceSearch(
            panels=self.panels,
            commands=self.commands,
            history_provider=lambda: self.history.snapshot(limit=100),
        )
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._feed: Any = None
        self._thread: threading.Thread | None = None

    def _bus(self):
        if self._bus_override is not None:
            return self._bus_override
        from reyes_agent import event_bus

        return event_bus

    def _publish(self, event_type: str, payload: dict[str, Any], correlation_id: str) -> None:
        try:
            self._bus().publish(
                event_type,
                payload=payload,
                source="workspace",
                correlation_id=correlation_id,
            )
        except Exception:
            pass

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    def route_request(self, message: str, correlation_id: str = "",
                      source_surface: str = "desktop") -> PresentationPlan:
        history = self.history.record_request(correlation_id, message)
        self._publish("workspace.history.changed", {
            "revision": history.revision, "history": history.as_dict()}, correlation_id)
        active = tuple(item.panel_id for item in self.manager.get_active_panels())
        plan = self.router.route(
            message,
            correlation_id=correlation_id,
            source_surface=source_surface,
            active_panels=active,
        )
        if plan.mode in {PresentationMode.FULL, PresentationMode.MINI} and plan.primary_panel:
            self.manager.show_panel(
                plan.primary_panel, plan.context, correlation_id=plan.correlation_id)
        return plan

    def consume_event(self, event: object) -> None:
        activity = self.activities.consume(event)
        if activity is not None:
            self._publish("workspace.activity.changed", {
                "revision": activity.revision, "activity": activity.as_dict()},
                activity.correlation_id)
        history = self.history.consume(event)
        if history is not None:
            self._publish("workspace.history.changed", {
                "revision": history.revision, "history": history.as_dict()}, history.task_id)
        raw = event if isinstance(event, dict) else (
            event.as_dict() if callable(getattr(event, "as_dict", None)) else {})
        event_type = str(raw.get("type") or "") if isinstance(raw, dict) else ""
        payload = raw.get("payload") if isinstance(raw, dict) else {}
        if event_type in {"tool.returned", "tool.completed", "tool.succeeded", "tool.failed"} and isinstance(payload, dict):
            name = str(payload.get("tool") or "")
            if name:
                record = self.health.observe_execution(
                    name,
                    event_type != "tool.failed",
                    float(payload.get("duration_ms") or 0.0),
                    str(payload.get("error_category") or ""),
                )
                self._publish("workspace.health.changed", {
                    "revision": record.revision, "health": record.as_dict()},
                    str(raw.get("correlation_id") or ""))

    def snapshot(self) -> dict[str, Any]:
        panel_state = self.manager.snapshot()
        return {
            "revision": self.revisions.current(),
            "panels": panel_state["panels"],
            "panel_definitions": panel_state["definitions"],
            "commands": [item.as_dict() for item in self.commands.all()],
            "activities": self.activities.snapshot(),
            "history": self.history.snapshot(),
            "health": self.health.snapshot(),
        }

    def mini_snapshot(self) -> dict[str, Any]:
        activities = self.activities.snapshot()
        panels = self.manager.get_active_panels()
        return {
            "revision": self.revisions.current(),
            "current_activity": activities[0] if activities else None,
            "active_count": len(activities),
            "primary_panel": panels[0].panel_id if panels else "",
        }

    def phone_snapshot(self) -> dict[str, Any]:
        activities = self.activities.snapshot()
        return {
            "revision": self.revisions.current(),
            "activities": [{
                "activity_id": item.get("activity_id", ""),
                "category": item.get("category", ""),
                "status": item.get("status", ""),
                "title": item.get("title", ""),
                "updated_at": item.get("updated_at", 0.0),
            } for item in activities[:25]],
        }

    def panel_action(self, panel_id: str, action: str,
                     context: dict[str, Any] | None = None,
                     correlation_id: str = "", position: str = "") -> dict[str, Any]:
        operations = {
            "show": lambda: self.manager.show_panel(
                panel_id, context, correlation_id=correlation_id),
            "hide": lambda: self.manager.hide_panel(panel_id),
            "toggle": lambda: self.manager.toggle_panel(panel_id),
            "minimize": lambda: self.manager.minimize_panel(panel_id),
            "expand": lambda: self.manager.expand_panel(panel_id),
            "focus": lambda: self.manager.focus_panel(panel_id),
            "dock": lambda: self.manager.dock_panel(panel_id, position),
            "close": lambda: self.manager.close_panel(panel_id),
        }
        operation = operations.get(str(action or "").casefold())
        if operation is None:
            raise ValueError("unsupported panel action")
        record = operation()
        if record is None:
            raise KeyError(f"unknown or inactive panel '{panel_id}'")
        return record.as_dict()

    def dismiss_activity(self, activity_id: str) -> bool:
        return self.activities.dismiss(activity_id)

    @staticmethod
    def _retry_input_is_safe(raw_input: object) -> bool:
        if not isinstance(raw_input, dict) or len(raw_input) > 50:
            return False
        private_keys = {"message", "body", "content", "text", "code", "value",
                        "prompt", "private_message", "message_body"}

        def has_private_key(value: object) -> bool:
            if isinstance(value, dict):
                return any(str(key).casefold().replace("-", "_") in private_keys or
                           has_private_key(item) for key, item in value.items())
            if isinstance(value, (list, tuple)):
                return any(has_private_key(item) for item in value)
            return False

        rendered = safe_text(repr(raw_input), 8_000)
        return (len(repr(raw_input)) <= 8_000 and not has_private_key(raw_input) and
                secret_free(raw_input) and redact_text(rendered, 8_000) == rendered)

    def observe_tool_execution(self, name: str, raw_input: dict[str, Any],
                               outcome: dict[str, Any], duration_ms: float) -> dict[str, Any]:
        from reyes_agent.workspace import current_correlation

        task_id = safe_text(current_correlation(), 80)
        tool_name = safe_text(name, 80)
        if not task_id or not tool_name:
            return {"stored": False, "state": "NO_CORRELATION"}
        outcome_name = safe_text((outcome or {}).get("outcome"), 40).casefold()
        retryable = bool((outcome or {}).get("retryable"))
        if outcome_name not in {"failed", "timed_out", "waiting"} or not retryable:
            self._retries.remove(task_id)
            return {"stored": False, "state": "NOT_RETRYABLE"}

        try:
            from reyes_agent import autonomy
            from reyes_agent.tools import TOOLS

            tool = TOOLS.get(tool_name)
            decision = autonomy.classify_tool(
                tool_name,
                requires_confirmation=bool(tool and tool.requires_confirmation),
            )
            safe_automatic = (decision.level is autonomy.AutonomyLevel.SAFE_AUTOMATION and
                              decision.allowed and not decision.requires_confirmation)
        except Exception:
            safe_automatic = False
        if not safe_automatic:
            self._retries.refuse(task_id, "CONFIRMATION_REQUIRED")
            return {"stored": False, "state": "CONFIRMATION_REQUIRED"}
        if not self._retry_input_is_safe(raw_input):
            self._retries.refuse(task_id, "NOT_RETRYABLE")
            return {"stored": False, "state": "NOT_RETRYABLE"}
        self._retries.put(task_id, tool_name, raw_input)
        return {"stored": True, "state": "RETRY_AVAILABLE", "task_id": task_id}

    def _worker_pool(self):
        if self._worker_pool_override is not None:
            return self._worker_pool_override
        from reyes_agent.worker_pool import get_worker_pool

        return get_worker_pool()

    def _tool_runner(self):
        if self._tool_runner_override is not None:
            return self._tool_runner_override
        from reyes_agent.tools import run_tool

        return run_tool

    def _execute_retry(self, task_id: str, tool_name: str,
                       raw_input: dict[str, Any]) -> str:
        from reyes_agent.tools import classify_tool_result
        from reyes_agent.workspace import correlation

        with correlation(task_id):
            result = self._tool_runner()(tool_name, dict(raw_input))
        outcome = classify_tool_result(result)
        if outcome.get("outcome") not in {"failed", "timed_out", "waiting"}:
            self._retries.remove(task_id)
        return result

    def _submit_retry(self, task_id: str) -> dict[str, Any]:
        handle = self._retries.get(safe_text(task_id, 80))
        if handle is None:
            state = self._retries.refusal(safe_text(task_id, 80)) or "NOT_RETRYABLE"
            return {"ok": False, "state": state, "task_id": safe_text(task_id, 80)}
        try:
            from reyes_agent.worker_pool import PRIORITY_BACKGROUND

            execution = self._worker_pool().submit(
                self._execute_retry,
                handle.task_id,
                handle.tool_name,
                dict(handle.raw_input),
                name=f"workspace-retry-{handle.tool_name}",
                priority=PRIORITY_BACKGROUND,
                timeout=60,
                retries=0,
            )
        except Exception as exc:
            return {"ok": False, "state": "QUEUE_REJECTED", "task_id": handle.task_id,
                    "reason": type(exc).__name__}
        return {"ok": True, "state": "QUEUED", "task_id": handle.task_id,
                "execution_id": safe_text(getattr(execution, "id", ""), 80)}

    def retry_task(self, task_id: str) -> dict[str, Any]:
        return self._submit_retry(task_id)

    def resume_task(self, task_id: str) -> dict[str, Any]:
        return self._submit_retry(task_id)

    def _consume_loop(self) -> None:
        while not self._stop.is_set():
            try:
                event = self._feed.get(timeout=0.25)
            except queue.Empty:
                continue
            except Exception:
                break
            try:
                self.consume_event(event)
            except Exception:
                continue

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._feed = self._bus().subscribe()
            self._thread = threading.Thread(
                target=self._consume_loop,
                name="zeno-workspace-events",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            feed = self._feed
            if thread is None and feed is None:
                return
            self._stop.set()
        if thread is not None:
            thread.join(timeout=1.0)
        if feed is not None:
            try:
                self._bus().unsubscribe(feed)
            except Exception:
                pass
        with self._lock:
            self._thread = None
            self._feed = None


_service: WorkspaceService | None = None
_service_lock = threading.Lock()


def get_workspace_service(*, start: bool = False) -> WorkspaceService:
    global _service
    with _service_lock:
        if _service is None:
            _service = WorkspaceService()
        service = _service
    if start:
        service.start()
    return service
