"""Authoritative logical state machine for ZENO workspace panels."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import replace
from typing import Any, Callable

from reyes_agent.workspace.models import PanelDefinition, PanelInstance, PanelState
from reyes_agent.workspace.registry import PanelRegistry

Publish = Callable[[str, dict[str, Any], str], None]

_DISPLAY_STATES = {
    PanelState.ACTIVE,
    PanelState.MINIMIZED,
    PanelState.EXPANDED,
    PanelState.DOCKED,
    PanelState.BACKGROUND,
}
_TRANSITIONS: dict[PanelState, set[PanelState]] = {
    PanelState.CLOSED: {PanelState.OPENING},
    PanelState.OPENING: {PanelState.ACTIVE, PanelState.CLOSING},
    PanelState.CLOSING: {PanelState.CLOSED},
    **{state: (_DISPLAY_STATES - {state}) | {PanelState.CLOSING}
       for state in _DISPLAY_STATES},
}
_DOCKS = {"left", "right", "top", "bottom"}


class RevisionClock:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value = 0

    def current(self) -> int:
        with self._lock:
            return self._value

    def next(self) -> int:
        with self._lock:
            self._value += 1
            return self._value


class WorkspaceManager:
    def __init__(
        self,
        registry: PanelRegistry,
        publish: Publish | None = None,
        max_instances: int = 24,
        revisions: RevisionClock | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.registry = registry
        self.revisions = revisions or RevisionClock()
        self._publish_callback = publish
        self._max_instances = max(1, min(int(max_instances), 100))
        self._clock = clock
        self._lock = threading.RLock()
        self._instances: dict[str, PanelInstance] = {}

    def _definition(self, panel_id: str) -> PanelDefinition:
        definition = self.registry.get(panel_id)
        if definition is None:
            raise KeyError(f"panel '{panel_id}' is not registered")
        return definition

    def _resolve(self, panel_id_or_instance: str) -> PanelInstance | None:
        key = str(panel_id_or_instance or "").strip().casefold()
        exact = self._instances.get(key)
        if exact is not None:
            return exact
        candidates = [item for item in self._instances.values()
                      if item.panel_id == key and item.state is not PanelState.CLOSED]
        return max(candidates, key=lambda item: (item.updated_at, item.revision), default=None)

    def _publish(self, action: str, instance: PanelInstance) -> None:
        if self._publish_callback is None:
            return
        try:
            self._publish_callback(
                "workspace.panel.changed",
                {"revision": instance.revision, "action": action,
                 "panel": instance.as_dict()},
                instance.correlation_id,
            )
        except Exception:
            pass

    def _store(self, instance: PanelInstance, action: str) -> PanelInstance:
        self._instances[instance.instance_id] = instance
        self._publish(action, instance)
        return instance

    def _transition(self, instance: PanelInstance, state: PanelState,
                    action: str, **changes: Any) -> PanelInstance:
        if state not in _TRANSITIONS.get(instance.state, set()):
            raise ValueError(f"invalid panel transition {instance.state.value} -> {state.value}")
        now = self._clock()
        opened_at = now if state is PanelState.OPENING and not instance.opened_at else instance.opened_at
        current = replace(
            instance,
            state=state,
            revision=self.revisions.next(),
            opened_at=opened_at,
            updated_at=now,
            **changes,
        )
        return self._store(current, action)

    def _update(self, instance: PanelInstance, action: str, **changes: Any) -> PanelInstance:
        current = replace(
            instance,
            revision=self.revisions.next(),
            updated_at=self._clock(),
            **changes,
        )
        return self._store(current, action)

    def _make_room(self) -> None:
        while len(self._instances) >= self._max_instances:
            closed = [item for item in self._instances.values()
                      if item.state is PanelState.CLOSED]
            if not closed:
                raise RuntimeError("workspace panel instance limit reached")
            victim = min(closed, key=lambda item: (item.updated_at, item.revision))
            self._instances.pop(victim.instance_id, None)

    def show_panel(
        self,
        panel_id: str,
        context: dict[str, Any] | None = None,
        *,
        correlation_id: str = "",
    ) -> PanelInstance:
        definition = self._definition(panel_id)
        safe_context = definition.validate_context(context)
        correlation = str(correlation_id or "")[:80]
        with self._lock:
            if definition.singleton:
                current = self._instances.get(definition.id)
                if current is not None and current.state is not PanelState.CLOSED:
                    merged = {**current.context, **safe_context}
                    if current.state is PanelState.ACTIVE:
                        return self._update(current, "updated", context=merged,
                                            correlation_id=correlation or current.correlation_id)
                    return self._transition(
                        current, PanelState.ACTIVE, "shown", context=merged,
                        correlation_id=correlation or current.correlation_id)
                instance_id = definition.id
            else:
                siblings = [item for item in self._instances.values()
                            if item.panel_id == definition.id]
                if len(siblings) >= 4:
                    closed = [item for item in siblings if item.state is PanelState.CLOSED]
                    if not closed:
                        raise RuntimeError(f"panel '{definition.id}' instance limit reached")
                    victim = min(closed, key=lambda item: (item.updated_at, item.revision))
                    self._instances.pop(victim.instance_id, None)
                instance_id = f"{definition.id}:{uuid.uuid4().hex[:8]}"
            self._make_room()
            base = PanelInstance(
                panel_id=definition.id,
                instance_id=instance_id,
                context=safe_context,
                correlation_id=correlation,
                priority=definition.priority,
            )
            opening = self._transition(base, PanelState.OPENING, "opening")
            return self._transition(opening, PanelState.ACTIVE, "shown")

    def _display(self, panel_id_or_instance: str, state: PanelState,
                 action: str, **changes: Any) -> PanelInstance | None:
        with self._lock:
            current = self._resolve(panel_id_or_instance)
            if current is None or current.state is PanelState.CLOSED:
                return None
            if current.state is state:
                return current
            return self._transition(current, state, action, **changes)

    def hide_panel(self, panel_id_or_instance: str) -> PanelInstance | None:
        return self._display(panel_id_or_instance, PanelState.BACKGROUND, "hidden")

    def minimize_panel(self, panel_id_or_instance: str) -> PanelInstance | None:
        return self._display(panel_id_or_instance, PanelState.MINIMIZED, "minimized")

    def expand_panel(self, panel_id_or_instance: str) -> PanelInstance | None:
        return self._display(panel_id_or_instance, PanelState.EXPANDED, "expanded")

    def focus_panel(self, panel_id_or_instance: str) -> PanelInstance | None:
        with self._lock:
            current = self._resolve(panel_id_or_instance)
            if current is None:
                definition = self.registry.get(panel_id_or_instance)
                return self.show_panel(definition.id) if definition else None
            if current.state is PanelState.CLOSED:
                return self.show_panel(current.panel_id, current.context,
                                       correlation_id=current.correlation_id)
            if current.state is PanelState.ACTIVE:
                return self._update(current, "focused")
            return self._transition(current, PanelState.ACTIVE, "focused")

    def dock_panel(self, panel_id_or_instance: str, position: str) -> PanelInstance | None:
        dock = str(position or "").strip().casefold()
        if dock not in _DOCKS:
            raise ValueError("dock position must be left, right, top, or bottom")
        return self._display(panel_id_or_instance, PanelState.DOCKED, "docked",
                             dock_position=dock)

    def toggle_panel(self, panel_id_or_instance: str) -> PanelInstance | None:
        with self._lock:
            current = self._resolve(panel_id_or_instance)
            if current is None or current.state in {PanelState.CLOSED, PanelState.BACKGROUND}:
                definition = self.registry.get(panel_id_or_instance)
                if current is not None:
                    return self._transition(current, PanelState.ACTIVE, "shown")
                return self.show_panel(definition.id) if definition else None
            return self._transition(current, PanelState.BACKGROUND, "hidden")

    def close_panel(self, panel_id_or_instance: str) -> PanelInstance | None:
        with self._lock:
            current = self._resolve(panel_id_or_instance)
            if current is None:
                return None
            if current.state is PanelState.CLOSED:
                return current
            closing = (current if current.state is PanelState.CLOSING else
                       self._transition(current, PanelState.CLOSING, "closing"))
            return self._transition(closing, PanelState.CLOSED, "closed")

    def get_panel_state(self, panel_id_or_instance: str) -> PanelState:
        with self._lock:
            current = self._resolve(panel_id_or_instance)
            return current.state if current is not None else PanelState.CLOSED

    def get_active_panels(self) -> list[PanelInstance]:
        with self._lock:
            return sorted(
                (item for item in self._instances.values()
                 if item.state is not PanelState.CLOSED),
                key=lambda item: (-item.priority, -item.revision),
            )

    def snapshot(self) -> dict[str, Any]:
        return {
            "revision": self.revisions.current(),
            "definitions": [item.as_dict() for item in self.registry.all()],
            "panels": [item.as_dict() for item in self.get_active_panels()],
        }
