"""One composed authority for workspace state and Event Bus projections."""

from __future__ import annotations

import queue
import threading
from typing import Any

from reyes_agent.workspace.activity import ActivityProjector
from reyes_agent.workspace.defaults import default_command_registry, default_panel_registry
from reyes_agent.workspace.history import HistoryProjector
from reyes_agent.workspace.intent_router import PanelIntentRouter
from reyes_agent.workspace.manager import RevisionClock, WorkspaceManager
from reyes_agent.workspace.models import PresentationMode, PresentationPlan
from reyes_agent.workspace.search import WorkspaceSearch
from reyes_agent.workspace.tool_health import ToolHealthManager


class WorkspaceService:
    def __init__(self, *, bus: Any = None) -> None:
        self._bus_override = bus
        self.revisions = RevisionClock()
        self.panels = default_panel_registry()
        self.commands = default_command_registry()
        self.manager = WorkspaceManager(
            self.panels, publish=self._publish, revisions=self.revisions)
        self.router = PanelIntentRouter(self.panels)
        self.activities = ActivityProjector(self.revisions)
        self.history = HistoryProjector(self.revisions)
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
            "activity": activities[0] if activities else None,
            "active_count": len(activities),
            "primary_panel": panels[0].panel_id if panels else "",
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
