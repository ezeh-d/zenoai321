"""Public, bounded record shapes for the ZENO live workspace."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from typing import Any

from reyes_agent.workspace.redaction import safe_text, sanitize_mapping


class PanelState(str, Enum):
    CLOSED = "CLOSED"
    OPENING = "OPENING"
    ACTIVE = "ACTIVE"
    MINIMIZED = "MINIMIZED"
    EXPANDED = "EXPANDED"
    DOCKED = "DOCKED"
    BACKGROUND = "BACKGROUND"
    CLOSING = "CLOSING"


class PresentationMode(str, Enum):
    NO_UI = "NO_UI"
    CARD = "CARD"
    MINI = "MINI"
    FULL = "FULL"
    BACKGROUND = "BACKGROUND"


class ActivityStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ToolHealthState(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    DISCONNECTED = "DISCONNECTED"
    ERROR = "ERROR"


def _public(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _public(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, dict):
        return sanitize_mapping(value)
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_public(item) for item in list(value)[:50]]
    if isinstance(value, str):
        return safe_text(value, 500)
    return value


class PublicRecord:
    def as_dict(self) -> dict[str, Any]:
        return _public(self)


@dataclass(frozen=True)
class PanelDefinition(PublicRecord):
    id: str
    title: str
    component: str
    supported_actions: tuple[str, ...] = (
        "show", "hide", "toggle", "minimize", "expand", "focus", "dock", "close")
    default_size: tuple[int, int] = (640, 480)
    preferred_position: str = "right"
    auto_open_policy: str = "contextual"
    priority: int = 50
    singleton: bool = True
    minimum_context: tuple[str, ...] = ()
    supported_surfaces: tuple[str, ...] = ("desktop", "mini", "phone")
    context_allowlist: tuple[str, ...] = (
        "query", "topic", "task_id", "activity_id", "location", "file",
        "project", "url", "agent", "category", "reason", "source", "surface",
        "reuse_existing")

    def validate_context(self, context: dict[str, Any] | None) -> dict[str, Any]:
        safe = sanitize_mapping(context or {})
        selected = {key: safe[key] for key in self.context_allowlist if key in safe}
        missing = [key for key in self.minimum_context if not selected.get(key)]
        if missing:
            raise ValueError("missing panel context: " + ", ".join(missing))
        return selected


@dataclass(frozen=True)
class CommandDefinition(PublicRecord):
    id: str
    title: str
    action: str
    target: str
    description: str = ""
    keywords: tuple[str, ...] = ()
    surfaces: tuple[str, ...] = ("desktop", "mini", "phone")


@dataclass(frozen=True)
class PanelInstance(PublicRecord):
    panel_id: str
    instance_id: str
    state: PanelState = PanelState.CLOSED
    context: dict[str, Any] = field(default_factory=dict)
    dock_position: str = ""
    correlation_id: str = ""
    priority: int = 50
    revision: int = 0
    opened_at: float = 0.0
    updated_at: float = 0.0


@dataclass(frozen=True)
class PresentationPlan(PublicRecord):
    mode: PresentationMode
    primary_panel: str = ""
    card_kind: str = ""
    reason_code: str = ""
    priority: int = 50
    context: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = ""


@dataclass(frozen=True)
class ActivityRecord(PublicRecord):
    activity_id: str
    correlation_id: str
    category: str
    status: ActivityStatus
    title: str
    safe_detail: str = ""
    progress: float | None = None
    progress_unit: str = ""
    importance: str = "normal"
    panel_target: str = ""
    result_reference: str = ""
    retryability: str = "none"
    started_at: float = 0.0
    updated_at: float = 0.0
    finished_at: float = 0.0
    expires_at: float = 0.0
    revision: int = 0


@dataclass(frozen=True)
class HistoryRecord(PublicRecord):
    task_id: str
    request_summary: str
    status: str
    tools: tuple[str, ...] = ()
    started_at: float = 0.0
    finished_at: float = 0.0
    safe_result: str = ""
    result_reference: str = ""
    retryability: str = "none"
    linked_attempts: tuple[str, ...] = ()
    revision: int = 0


@dataclass(frozen=True)
class HealthRecord(PublicRecord):
    name: str
    category: str
    status: ToolHealthState
    available: bool
    initialized: bool = False
    reason: str = ""
    dependencies: tuple[str, ...] = ()
    permissions_required: tuple[str, ...] = ()
    last_checked: float = 0.0
    last_success: float = 0.0
    last_failure: float = 0.0
    latency_ms: float = 0.0
    last_error_code: str = ""
    suggested_repair: str = ""
    supported_operations: tuple[str, ...] = ()
    evidence_source: str = ""
    revision: int = 0
