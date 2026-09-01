"""Dynamic registries for workspace panels and commands."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any, Callable

from reyes_agent.workspace.models import CommandDefinition, PanelDefinition

_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
_COMPONENT_PREFIXES = ("builtin:", "dom:", "module:")


def _valid_id(value: str, kind: str) -> str:
    identifier = str(value or "").strip().casefold()
    if not _ID.fullmatch(identifier):
        raise ValueError(f"invalid {kind} id '{value}'")
    return identifier


class PanelRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._definitions: dict[str, PanelDefinition] = {}

    def register(self, definition: PanelDefinition) -> PanelDefinition:
        if not isinstance(definition, PanelDefinition):
            raise TypeError("panel definition required")
        panel_id = _valid_id(definition.id, "panel")
        if not str(definition.component).startswith(_COMPONENT_PREFIXES):
            raise ValueError("panel component must use builtin:, dom:, or module:")
        with self._lock:
            existing = self._definitions.get(panel_id)
            if existing is not None and existing != definition:
                raise ValueError(f"duplicate panel id '{panel_id}'")
            self._definitions[panel_id] = definition
        return definition

    def get(self, panel_id: str) -> PanelDefinition | None:
        with self._lock:
            return self._definitions.get(str(panel_id or "").strip().casefold())

    def all(self) -> list[PanelDefinition]:
        with self._lock:
            return sorted(self._definitions.values(), key=lambda item: item.id)

    def unregister(self, panel_id: str) -> bool:
        with self._lock:
            return self._definitions.pop(str(panel_id or "").strip().casefold(), None) is not None


class CommandRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._definitions: dict[str, CommandDefinition] = {}

    def register(self, definition: CommandDefinition) -> CommandDefinition:
        if not isinstance(definition, CommandDefinition):
            raise TypeError("command definition required")
        command_id = _valid_id(definition.id, "command")
        with self._lock:
            existing = self._definitions.get(command_id)
            if existing is not None and existing != definition:
                raise ValueError(f"duplicate command id '{command_id}'")
            self._definitions[command_id] = definition
        return definition

    def get(self, command_id: str) -> CommandDefinition | None:
        with self._lock:
            return self._definitions.get(str(command_id or "").strip().casefold())

    def all(self) -> list[CommandDefinition]:
        with self._lock:
            return sorted(self._definitions.values(), key=lambda item: item.id)

    def unregister(self, command_id: str) -> bool:
        with self._lock:
            return self._definitions.pop(str(command_id or "").strip().casefold(), None) is not None


@dataclass(frozen=True)
class HealthProbe:
    name: str
    category: str
    check: Callable[[], dict[str, Any]]
    supported_operations: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    permissions_required: tuple[str, ...] = ()
    timeout_s: float = 2.0
    recover: Callable[[], dict[str, Any]] | None = None


class HealthProbeRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._probes: dict[str, HealthProbe] = {}

    def register(self, probe: HealthProbe) -> HealthProbe:
        if not isinstance(probe, HealthProbe):
            raise TypeError("health probe required")
        name = str(probe.name or "").strip().casefold()
        if not name or not callable(probe.check):
            raise ValueError("health probe needs a name and callable check")
        with self._lock:
            existing = self._probes.get(name)
            if existing is not None and existing != probe:
                raise ValueError(f"duplicate health probe '{name}'")
            self._probes[name] = probe
        return probe

    def get(self, name: str) -> HealthProbe | None:
        with self._lock:
            return self._probes.get(str(name or "").strip().casefold())

    def all(self) -> list[HealthProbe]:
        with self._lock:
            return sorted(self._probes.values(), key=lambda item: item.name)
