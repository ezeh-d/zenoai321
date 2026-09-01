from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reyes_agent.workspace.api import create_router
from reyes_agent.workspace.service import WorkspaceService


class _FakeSearch:
    def search(self, query: str, limit: int = 12):
        return [{"id": "panel:system", "kind": "panel", "title": "System",
                 "action": "show", "target": "system", "query": query, "limit": limit}]

    def health(self):
        return {"ok": True, "sources": ["panels"]}


class _FakeHealth:
    def check_many(self, names=None, force=False):
        return []


class _FakeService:
    def __init__(self) -> None:
        self.search = _FakeSearch()
        self.health = _FakeHealth()
        self.calls: list[tuple] = []

    def snapshot(self):
        return {"revision": 7, "panels": [], "panel_definitions": [],
                "commands": [], "activities": [], "history": [], "health": []}

    def panel_action(self, panel_id, action, context, correlation_id, position=""):
        self.calls.append(("panel", panel_id, action, context, correlation_id, position))
        return {"revision": 8, "panel_id": panel_id, "state": "ACTIVE"}

    def dismiss_activity(self, activity_id):
        self.calls.append(("dismiss", activity_id))
        return True

    def retry_task(self, task_id):
        self.calls.append(("retry", task_id))
        return {"accepted": True, "task_id": task_id}

    def resume_task(self, task_id):
        self.calls.append(("resume", task_id))
        return {"accepted": True, "task_id": task_id}


def _client(client=("127.0.0.1", 5000)):
    service = _FakeService()
    app = FastAPI()
    app.include_router(create_router(service=service))
    return TestClient(app, client=client), service


def test_workspace_api_is_loopback_only_and_revisioned() -> None:
    local, _ = _client()
    remote, _ = _client(("203.0.113.9", 5000))

    assert local.get("/api/workspace/state").json()["revision"] == 7
    assert remote.get("/api/workspace/state").status_code == 403


def test_panel_actions_are_allowlisted_and_delegate_bounded_context() -> None:
    client, service = _client()
    response = client.post("/api/workspace/panels/system/show", json={
        "context": {"query": "status"},
        "correlation_id": "turn-7",
        "position": "right",
    })

    assert response.status_code == 200
    assert response.json()["revision"] == 8
    assert service.calls == [("panel", "system", "show", {"query": "status"},
                              "turn-7", "right")]
    assert client.post("/api/workspace/panels/system/destroy", json={}).status_code == 400


def test_activity_search_health_retry_and_resume_routes_delegate() -> None:
    client, service = _client()

    assert client.get("/api/workspace/activities").status_code == 200
    assert client.post("/api/workspace/activities/a-1/dismiss").json()["dismissed"] is True
    searched = client.get("/api/workspace/search", params={"q": "system", "limit": 500}).json()
    assert searched["results"][0]["limit"] == 25
    assert client.post("/api/workspace/health/refresh", json={"names": ["files"]}).status_code == 200
    assert client.post("/api/workspace/history/t-1/retry").json()["accepted"] is True
    assert client.post("/api/workspace/history/t-2/resume").json()["accepted"] is True
    assert ("dismiss", "a-1") in service.calls
    assert ("retry", "t-1") in service.calls
    assert ("resume", "t-2") in service.calls


def test_real_service_panel_action_and_activity_dismissal() -> None:
    class _Bus:
        def publish(self, *args, **kwargs):
            return None

    service = WorkspaceService(bus=_Bus())
    try:
        shown = service.panel_action(
            "system", "show", {"query": "health"}, "turn-9", "")
        activity = service.activities.consume({
            "type": "tool.started",
            "source": "tools",
            "correlation_id": "turn-9",
            "payload": {"tool": "system_status"},
        })

        assert shown["state"] == "ACTIVE"
        assert activity is not None
        assert service.dismiss_activity(activity.activity_id) is True
        assert service.dismiss_activity(activity.activity_id) is False
    finally:
        service.health.close()


def test_main_web_app_registers_workspace_router_once() -> None:
    from reyes_agent import web

    paths = [getattr(route, "path", "") for route in web.app.routes]
    for route in web.app.routes:
        included = getattr(route, "original_router", None)
        paths.extend(getattr(child, "path", "") for child in getattr(included, "routes", ()))
    routes = [path for path in paths if path == "/api/workspace/state"]
    assert routes == ["/api/workspace/state"]


def test_open_turn_routes_the_assigned_turn_exactly_once(monkeypatch) -> None:
    from reyes_agent import conversation_state, latency, web, workspace

    calls = []

    class _Workspace:
        def route_request(self, message, correlation_id, source_surface):
            calls.append((message, correlation_id, source_surface))

    monkeypatch.setattr(conversation_state, "current", lambda: "IDLE")
    monkeypatch.setattr(conversation_state, "begin_turn", lambda requested="": "turn-22")
    monkeypatch.setattr(conversation_state, "enter", lambda *args, **kwargs: None)
    monkeypatch.setattr(latency, "begin", lambda *args, **kwargs: None)
    monkeypatch.setattr(latency, "mark", lambda *args, **kwargs: None)
    monkeypatch.setattr(workspace, "get_workspace_service", lambda **kwargs: _Workspace())

    assert web._open_turn("show system status", kind="typed") == "turn-22"
    assert calls == [("show system status", "turn-22", "desktop")]


def test_real_service_exposes_bounded_mini_snapshot() -> None:
    service = WorkspaceService(bus=object())
    try:
        compact = service.mini_snapshot()
    finally:
        service.health.close()

    assert set(compact) == {"revision", "activity", "active_count", "primary_panel"}
    assert compact["active_count"] == 0


def test_mini_status_includes_workspace_projection(monkeypatch) -> None:
    from reyes_agent import kernel, web, workspace

    class _Kernel:
        def diagnostics(self):
            return {"workers": {"active_tasks": [], "queue_depth": 0}}

    class _Workspace:
        def mini_snapshot(self):
            return {"revision": 4, "activity": None, "active_count": 0,
                    "primary_panel": ""}

    monkeypatch.setattr(kernel, "get_kernel", lambda: _Kernel())
    monkeypatch.setattr(workspace, "get_workspace_service", lambda **kwargs: _Workspace())

    assert web.mini_status()["workspace"]["revision"] == 4
