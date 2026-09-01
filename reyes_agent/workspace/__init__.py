"""Backend-authoritative live workspace contracts.

The package is intentionally lazy. Importing it starts no subscriber, probe,
frontend, or tool execution path.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
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
    correlation_token = bind_correlation(correlation_id)
    try:
        yield
    finally:
        reset_correlation(correlation_token)


def bind_correlation(correlation_id: str) -> Token[str]:
    return _correlation_id.set(str(correlation_id or "")[:80])


def reset_correlation(token: Token[str]) -> None:
    _correlation_id.reset(token)


def current_correlation() -> str:
    return _correlation_id.get()


def get_workspace_service(*, start: bool = False):
    from reyes_agent.workspace.service import get_workspace_service as get_service

    return get_service(start=start)

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
    "bind_correlation",
    "correlation",
    "current_correlation",
    "get_workspace_service",
    "reset_correlation",
]
