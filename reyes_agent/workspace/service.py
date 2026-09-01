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

    def snapshot(self) -> dict[str, Any]:
        panel_state = self.manager.snapshot()
        return {
            "revision": self.revisions.current(),
            "panels": panel_state["panels"],
            "panel_definitions": panel_state["definitions"],
            "commands": [item.as_dict() for item in self.commands.all()],
            "activities": self.activities.snapshot(),
            "history": self.history.snapshot(),
            "health": [],
        }

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
