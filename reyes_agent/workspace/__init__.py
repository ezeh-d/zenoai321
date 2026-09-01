"""Backend-authoritative live workspace contracts.

The package is intentionally lazy. Importing it starts no subscriber, probe,
frontend, or tool execution path.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from reyes_agent.workspace.models import (
    ActivityRecord,
    ActivityStatus,
    CommandDefinition,
    HealthRecord,
    HistoryRecord,
    PanelDefinition,
    PanelInstance,
    PanelState,
    PresentationMode,
    PresentationPlan,
    ToolHealthState,
)

_correlation_id: ContextVar[str] = ContextVar("zeno_workspace_correlation", default="")


@contextmanager
def correlation(correlation_id: str, request_summary: str = "") -> Iterator[None]:
    correlation_token = _correlation_id.set(str(correlation_id or "")[:80])
    try:
        yield
    finally:
        _correlation_id.reset(correlation_token)


def current_correlation() -> str:
    return _correlation_id.get()

__all__ = [
    "ActivityRecord",
    "ActivityStatus",
    "CommandDefinition",
    "HealthRecord",
    "HistoryRecord",
    "PanelDefinition",
    "PanelInstance",
    "PanelState",
    "PresentationMode",
    "PresentationPlan",
    "ToolHealthState",
    "correlation",
    "current_correlation",
]
