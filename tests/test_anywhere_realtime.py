"""Focused contracts for the bounded ZENO Anywhere realtime feed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reyes_agent.auth.owner import OwnerAuthService
from reyes_agent.remote_access import cloud_api, device_link, policy, realtime
from reyes_agent.remote_access.device_link import DeviceLink


@pytest.fixture(autouse=True)
def clean_realtime():
    realtime.reset_for_tests()
    yield
    realtime.reset_for_tests()


def test_hub_bounds_subscribers_and_stalled_queue():
    hub = realtime.reset_for_tests(max_subscribers=2, queue_size=2)
    first = hub.subscribe()
    second = hub.subscribe()
    with pytest.raises(realtime.SubscriberLimitError):
        hub.subscribe()

    hub.publish({"type": "one", "command_id": "cmd_1"})
    hub.publish({"type": "two", "command_id": "cmd_2"})
    hub.publish({"type": "three", "command_id": "cmd_3"})
    assert first.depth == 2
    assert first.get(0.01)["type"] == "two"
    assert first.get(0.01)["type"] == "three"
    hub.unsubscribe(first)
    hub.unsubscribe(second)
    assert hub.stats()["subscribers"] == 0


def test_event_shape_is_allowlisted_and_never_exposes_payload_or_failure_text():
    subscription = realtime.subscribe()
    assert realtime.publish({
        "type": "command_failed\nforged",
        "command_id": "cmd_123",
        "target_device": "dev_456",
        "execution_result": "FAILED",
        "payload": {"password": "fixture-secret"},
        "result": {"answer": "private answer"},
        "failure_reason": "Authorization: Bearer fixture-token",
        "summary": "private summary",
    })
    event = subscription.get(0.1)
    rendered = json.dumps(event)
    assert set(event) == {"sequence", "type", "at", "command_id", "device_id", "status"}
    assert event["type"] == "command_failedforged"
    assert "fixture-secret" not in rendered
    assert "fixture-token" not in rendered
    assert "private answer" not in rendered
    realtime.unsubscribe(subscription)


def test_device_activity_publishes_only_sanitized_invalidation(tmp_path: Path):
    link = DeviceLink(tmp_path / "device.sqlite")
    subscription = realtime.subscribe()
    link._activity(
        "command_completed", target_device="dev_test", command_id="cmd_test",
        execution_result="DONE", summary="private result that must not stream")
    event = subscription.get(0.1)
    assert event["type"] == "command_completed"
    assert event["command_id"] == "cmd_test"
    assert event["device_id"] == "dev_test"
    assert event["status"] == "DONE"
    assert "private" not in json.dumps(event)
    realtime.unsubscribe(subscription)


def test_stream_revalidates_session_and_unsubscribes_when_revoked():
    hub = realtime.reset_for_tests(max_subscribers=1, queue_size=2)
    subscription = hub.subscribe()
    stream = realtime.iter_sse(subscription, lambda: False, heartbeat_s=0.01)
    assert "connected" in next(stream)
    assert "session_closed" in next(stream)
    with pytest.raises(StopIteration):
        next(stream)
    assert hub.stats()["subscribers"] == 0


def test_stream_sends_keepalive_after_successful_revalidation():
    subscription = realtime.subscribe()
    stream = realtime.iter_sse(subscription, lambda: True, heartbeat_s=0.01)
    assert "connected" in next(stream)
    assert next(stream) == ": keepalive\n\n"
    stream.close()
    assert realtime.stats()["subscribers"] == 0


def test_events_route_refuses_missing_and_pending_owner_sessions(
        tmp_path: Path, monkeypatch):
    policy.reset_rates()
    owner = OwnerAuthService(tmp_path / "owner.sqlite")
    ok, _ = owner.provision("owner@example.com", "correct horse battery staple")
    assert ok
    link = DeviceLink(tmp_path / "devices.sqlite")
    monkeypatch.setattr(cloud_api, "get_owner_auth", lambda: owner)
    monkeypatch.setattr(cloud_api.device_link, "get_link", lambda: link)

    app = FastAPI()
    cloud_api.register(app)
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/api/owner/events").status_code == 401
        login = client.post("/api/owner/auth/login", json={
            "email": "owner@example.com",
            "password": "correct horse battery staple",
            "nonce": "realtime-login-nonce-0001",
            "device": "Pending browser",
            "device_id": "browser_realtime_pending_01",
        })
        assert login.status_code == 200
        assert login.json()["trusted"] is False
        assert client.get("/api/owner/events").status_code == 403
