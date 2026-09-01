from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from reyes_agent.workspace import correlation, current_correlation
from reyes_agent.workspace.activity import ActivityProjector
from reyes_agent.workspace.history import HistoryProjector
from reyes_agent.workspace.manager import RevisionClock
from reyes_agent.workspace.models import ActivityStatus, PresentationMode
from reyes_agent.workspace.service import WorkspaceService


def test_tool_events_coalesce_redact_and_expire_success_without_timer() -> None:
    now = [100.0]
    projector = ActivityProjector(RevisionClock(), clock=lambda: now[0])

    first = projector.consume({
        "type": "tool.returned",
        "correlation_id": "t1",
        "ts": 90,
        "payload": {
            "tool": "search_files",
            "input": {"query": "CV", "token": "secret"},
            "result": "Found CV.pdf",
            "duration_ms": 12,
        },
    })
    second = projector.consume({
        "type": "tool.completed",
        "correlation_id": "t1",
        "ts": 91,
        "payload": {
            "tool": "search_files",
            "result": "Verified CV.pdf",
            "duration_ms": 18,
        },
    })

    assert first is not None and second is not None
    assert first.activity_id == second.activity_id
    assert second.status is ActivityStatus.SUCCEEDED
    assert "token" not in repr(second.as_dict()).casefold()
    assert len(projector.snapshot()) == 1

    now[0] = second.expires_at + 0.1
    assert projector.snapshot() == []


def test_real_task_progress_is_preserved_and_failures_do_not_auto_expire() -> None:
    projector = ActivityProjector(RevisionClock(), clock=lambda: 50.0)
    running = projector.consume({
        "type": "build.task",
        "correlation_id": "build-1",
        "payload": {"task": {
            "task_id": "build-1", "title": "Build dashboard", "state": "RUNNING",
            "progress_percent": 72, "current_step": {"label": "Run tests"},
        }},
    })
    failed = projector.consume({
        "type": "build.task",
        "correlation_id": "build-1",
        "payload": {"task": {
            "task_id": "build-1", "title": "Build dashboard", "state": "FAILED",
            "progress_percent": 72, "error_details": "Connection dropped",
        }},
    })

    assert running is not None and running.progress == 72
    assert failed is not None and failed.status is ActivityStatus.FAILED
    assert failed.expires_at == 0
    assert failed.safe_detail == "Connection dropped"


def test_workspace_output_unknown_and_malformed_events_are_not_projected() -> None:
    projector = ActivityProjector(RevisionClock())

    assert projector.consume({
        "type": "workspace.activity.changed", "source": "workspace", "payload": {}}) is None
    assert projector.consume({"type": "unrelated.internal", "payload": {}}) is None
    assert projector.consume(None) is None
    assert projector.consume({"type": 7, "payload": object()}) is None


def test_concurrent_event_projection_remains_bounded() -> None:
    projector = ActivityProjector(RevisionClock(), max_live=100)

    def project(index: int) -> None:
        projector.consume({
            "type": "tool.failed",
            "payload": {"tool": f"tool_{index}", "result": object()},
            "correlation_id": str(index),
        })

    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(project, range(300)))

    snapshot = projector.snapshot()
    assert len(snapshot) == 100
    assert all(row["status"] == "FAILED" for row in snapshot)


def test_history_uses_safe_event_facts_and_keeps_tool_order_unique() -> None:
    revisions = RevisionClock()
    history = HistoryProjector(revisions, clock=lambda: 20.0)
    started = history.record_request("turn-1", "find my CV token=secret")
    result = history.consume({
        "type": "tool.returned",
        "correlation_id": "turn-1",
        "payload": {"tool": "search_files", "result": "Found CV.pdf", "token": "x"},
    })
    history.consume({
        "type": "tool.completed",
        "correlation_id": "turn-1",
        "payload": {"tool": "search_files", "result": "Verified CV.pdf"},
    })

    assert started.request_summary == "find my CV [redacted]"
    assert result is not None
    row = history.snapshot()[0]
    assert row["tools"] == ["search_files"]
    assert row["safe_result"] == "Verified CV.pdf"
    assert "secret" not in repr(row).casefold()


def test_correlation_context_is_nested_and_resets_cleanly() -> None:
    assert current_correlation() == ""
    with correlation("outer", request_summary="one"):
        assert current_correlation() == "outer"
        with correlation("inner"):
            assert current_correlation() == "inner"
        assert current_correlation() == "outer"
    assert current_correlation() == ""


@dataclass
class _Event:
    type: str
    payload: dict
    correlation_id: str = ""
    source: str = "test"
    ts: float = 1.0
    id: str = "e1"

    def as_dict(self) -> dict:
        return self.__dict__.copy()


class _Bus:
    def __init__(self) -> None:
        self.feed: queue.Queue = queue.Queue(maxsize=20)
        self.subscribes = 0
        self.unsubscribes = 0
        self.published: list[tuple[str, dict, str, str]] = []

    def subscribe(self):
        self.subscribes += 1
        return self.feed

    def unsubscribe(self, feed) -> None:
        assert feed is self.feed
        self.unsubscribes += 1

    def publish(self, event_type, payload=None, source="", correlation_id=""):
        self.published.append((event_type, payload or {}, source, correlation_id))


def test_service_routes_request_consumes_one_feed_and_stops_cleanly() -> None:
    bus = _Bus()
    service = WorkspaceService(bus=bus)

    plan = service.route_request("find my CV", "turn-9", "desktop")
    assert plan.mode is PresentationMode.FULL
    assert any(panel["panel_id"] == "files" for panel in service.snapshot()["panels"])

    service.start()
    service.start()
    bus.feed.put(_Event("tool.returned", {
        "tool": "search_files", "result": "Found CV.pdf"}, "turn-9"))
    deadline = time.time() + 2
    while not service.snapshot()["activities"] and time.time() < deadline:
        time.sleep(0.01)
    service.stop()
    service.stop()

    snapshot = service.snapshot()
    assert bus.subscribes == 1 and bus.unsubscribes == 1
    assert snapshot["activities"][0]["correlation_id"] == "turn-9"
    assert any(kind == "workspace.activity.changed" for kind, *_ in bus.published)
    assert service.running is False


def test_request_tool_activity_panel_and_snapshot_share_revision_and_correlation() -> None:
    bus = _Bus()
    service = WorkspaceService(bus=bus)
    try:
        plan = service.route_request("find my CV", "turn-e2e", "desktop")
        service.consume_event({
            "type": "tool.returned", "source": "tools", "correlation_id": "turn-e2e",
            "payload": {"tool": "search_files", "result": "CV.pdf"},
        })
        snapshot = service.snapshot()
    finally:
        service.health.close()

    published_revisions = [payload["revision"] for _, payload, _, _ in bus.published
                           if isinstance(payload.get("revision"), int)]
    assert plan.primary_panel == "files"
    assert any(panel["panel_id"] == "files" and panel["correlation_id"] == "turn-e2e"
               for panel in snapshot["panels"])
    assert any(activity["correlation_id"] == "turn-e2e"
               for activity in snapshot["activities"])
    assert snapshot["revision"] == max(published_revisions)
