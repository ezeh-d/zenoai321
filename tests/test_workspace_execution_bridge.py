from __future__ import annotations

import queue
from dataclasses import dataclass

from reyes_agent import event_bus, workspace
from reyes_agent.tools import Tool, execute_tool
from reyes_agent.workspace import (
    bind_correlation,
    correlation,
    current_correlation,
    reset_correlation,
)
from reyes_agent.workspace.service import WorkspaceService


def _next_tool_event(subscription, wanted: str):
    for _ in range(30):
        event = subscription.get(timeout=1)
        if event.type == wanted:
            return event
    raise AssertionError(f"no {wanted} event")


def test_tool_event_and_observer_use_current_workspace_correlation(monkeypatch) -> None:
    subscription = event_bus.subscribe()
    observations = []

    class _Observer:
        def observe_tool_execution(self, name, raw_input, outcome, duration_ms):
            observations.append((name, raw_input, outcome["outcome"], current_correlation()))

    monkeypatch.setattr(workspace, "get_workspace_service", lambda **kwargs: _Observer())
    tool = Tool("read_workspace_fixture", "read", {"type": "object"},
                lambda query="": "ordinary data")
    try:
        with correlation("turn-77", request_summary="read status"):
            execute_tool(tool, {"query": "status"})
        event = _next_tool_event(subscription, "tool.returned")
    finally:
        event_bus.unsubscribe(subscription)

    assert event.correlation_id == "turn-77"
    assert observations == [
        ("read_workspace_fixture", {"query": "status"}, "returned", "turn-77")]


def test_explicit_correlation_tokens_reset_without_leaking() -> None:
    token = bind_correlation("turn-8")
    assert current_correlation() == "turn-8"
    reset_correlation(token)
    assert current_correlation() == ""


@dataclass
class _Handle:
    id: str = "retry-job-1"


class _InlinePool:
    def __init__(self) -> None:
        self.calls = []

    def submit(self, function, *args, **kwargs):
        self.calls.append((function, args, kwargs))
        function(*args)
        return _Handle()


class _Bus:
    def publish(self, *args, **kwargs):
        return None


def _service(*, clock=lambda: 100.0):
    pool = _InlinePool()
    executions = []

    def runner(name, raw_input):
        executions.append((name, raw_input, current_correlation()))
        return "ordinary data"

    service = WorkspaceService(
        bus=_Bus(), worker_pool=pool, tool_runner=runner, clock=clock)
    return service, pool, executions


def test_safe_read_failure_keeps_ephemeral_handle_and_retries_once() -> None:
    service, pool, executions = _service()
    try:
        with correlation("turn-safe"):
            service.observe_tool_execution(
                "read_status", {"query": "workspace-retry-fixture-4831"},
                {"outcome": "failed", "retryable": True}, 10)

        public = repr(service.snapshot())
        result = service.retry_task("turn-safe")
    finally:
        service.health.close()

    assert "workspace-retry-fixture-4831" not in public
    assert result == {"ok": True, "state": "QUEUED", "task_id": "turn-safe",
                      "execution_id": "retry-job-1"}
    assert executions == [
        ("read_status", {"query": "workspace-retry-fixture-4831"}, "turn-safe")]
    assert len(pool.calls) == 1
    assert pool.calls[0][2]["retries"] == 0


def test_irreversible_private_action_is_refused_without_retaining_input() -> None:
    service, _, executions = _service()
    try:
        with correlation("turn-private"):
            service.observe_tool_execution(
                "send_message", {"body": "private words"},
                {"outcome": "failed", "retryable": True}, 10)
        result = service.retry_task("turn-private")
        public = repr(service.snapshot())
    finally:
        service.health.close()

    assert result["ok"] is False
    assert result["state"] == "CONFIRMATION_REQUIRED"
    assert executions == []
    assert "private words" not in public


def test_secret_bearing_read_input_is_never_retained_for_retry() -> None:
    service, _, executions = _service()
    try:
        with correlation("turn-secret"):
            service.observe_tool_execution(
                "read_status", {"token": "supersecret"},
                {"outcome": "failed", "retryable": True}, 10)
        result = service.retry_task("turn-secret")
    finally:
        service.health.close()

    assert result["ok"] is False
    assert result["state"] == "NOT_RETRYABLE"
    assert executions == []


def test_retry_handle_expires_after_ten_minutes() -> None:
    now = [10.0]
    service, _, _ = _service(clock=lambda: now[0])
    try:
        with correlation("turn-old"):
            service.observe_tool_execution(
                "read_status", {}, {"outcome": "failed", "retryable": True}, 10)
        now[0] = 611.0
        result = service.retry_task("turn-old")
    finally:
        service.health.close()

    assert result["ok"] is False
    assert result["state"] == "NOT_RETRYABLE"


def test_resume_uses_same_safe_bounded_execution_bridge() -> None:
    service, _, executions = _service()
    try:
        with correlation("turn-wait"):
            service.observe_tool_execution(
                "check_job", {"job_id": "job-1"},
                {"outcome": "waiting", "retryable": True}, 2)
        result = service.resume_task("turn-wait")
    finally:
        service.health.close()

    assert result["ok"] is True and result["state"] == "QUEUED"
    assert executions == [("check_job", {"job_id": "job-1"}, "turn-wait")]
