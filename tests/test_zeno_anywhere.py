"""Security and continuity contracts for ZENO Anywhere v1."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reyes_agent.auth.owner import OwnerAuthService
from reyes_agent.remote_access import cloud_api, device_link, policy
from reyes_agent.remote_access.desktop_agent import (
    ACTION_TOOLS, AgentConfig, DesktopAgent, _args_open_app, _exec_ask, _run_tool,
)
from reyes_agent.remote_access.device_link import (
    APPROVED_DEVICE, CANCELLED, EXPIRED, PENDING_APPROVAL, WAITING_FOR_DEVICE,
    DeviceLink,
)


@pytest.fixture
def owner(tmp_path: Path) -> OwnerAuthService:
    service = OwnerAuthService(tmp_path / "owner.sqlite")
    ok, _message = service.provision(
        "owner@example.com", "correct horse battery staple")
    assert ok
    return service


@pytest.fixture
def link(tmp_path: Path) -> DeviceLink:
    return DeviceLink(tmp_path / "devices.sqlite")


def _login(owner: OwnerAuthService, *, nonce: str = "n" * 32,
           device_id: str = "browser_test_device_0001"):
    return owner.login(
        "owner@example.com", "correct horse battery staple", identity="127.0.0.1",
        device_label="Owner browser", user_agent="pytest", nonce=nonce,
        device_id=device_id)


def _approved_windows(link: DeviceLink) -> dict[str, str]:
    registration = link.register(label="Main Laptop", platform="windows")
    assert registration["approval_state"] == "PENDING"
    assert not link.authenticate(registration["device_id"], registration["token"])
    assert link.approve_device(registration["device_id"], scopes=["standard_device"])
    assert link.authenticate(registration["device_id"], registration["token"])
    return registration


def test_owner_password_session_replay_csrf_refresh_and_revocation(owner):
    login = _login(owner)
    assert login.ok and login.session and login.session.device_state == "PENDING"
    assert owner.verify(login.session.token) == (True, "")
    assert owner.verify(login.session.token, csrf="wrong", require_csrf=True)[0] is False
    assert owner.login(
        "owner@example.com", "correct horse battery staple", identity="127.0.0.1",
        nonce="n" * 32, device_id="browser_test_device_0001").reason == (
            "This request was already used.")
    assert owner.approve_browser_device(login.session.device_id)
    assert owner.session_info(login.session.token)["trusted"] is True
    refreshed = owner.refresh_session(login.session.refresh, identity="127.0.0.1")
    assert refreshed.ok and refreshed.session
    assert owner.verify(login.session.token)[0] is False
    assert owner.verify(refreshed.session.token)[0] is True
    assert owner.logout(refreshed.session.token)
    assert owner.verify(refreshed.session.token)[0] is False


def test_new_browser_is_pending_and_blocking_it_invalidates_sessions(owner):
    login = _login(owner, nonce="p" * 32, device_id="browser_pending_device_01")
    assert login.ok and owner.session_info(login.session.token)["trusted"] is False
    assert owner.set_browser_device_state(login.session.device_id, "BLOCKED")
    assert owner.verify(login.session.token)[0] is False


def test_password_login_requires_a_real_nonce_and_locks_repeated_failures(owner):
    no_nonce = owner.login("owner@example.com", "correct horse battery staple",
                           identity="nonce-test")
    assert not no_nonce.ok and "nonce" in no_nonce.reason.casefold()
    last = None
    for index in range(5):
        last = owner.login("owner@example.com", "wrong password", identity="attacker",
                           nonce=f"bad-attempt-{index:02d}-xxxxxxxx")
    assert last and not last.ok
    locked = owner.login("owner@example.com", "correct horse battery staple",
                         identity="attacker", nonce="correct-attempt-xxxxxxxx")
    assert not locked.ok and locked.retry_after > 0


def test_passkey_cannot_be_inserted_without_webauthn_verification(owner):
    assert owner.register_passkey("attacker", "attacker-key") is False
    options = owner.passkey_registration_options(rp_id="localhost")
    challenge = options["challenge"]
    assert owner._take_challenge(challenge, "passkey-registration") == challenge
    with pytest.raises(PermissionError):
        owner._take_challenge(challenge, "passkey-registration")


def test_device_store_rejects_unknown_unapproved_revoked_and_arbitrary_work(link):
    with pytest.raises(KeyError):
        link.enqueue("missing", "open_app", {"name": "calculator"})
    registration = link.register(label="Main Laptop")
    with pytest.raises(PermissionError):
        link.enqueue(registration["device_id"], "open_app", {"name": "calculator"})
    assert link.approve_device(registration["device_id"])
    with pytest.raises(ValueError):
        link.enqueue(registration["device_id"], "run_shell", {"command": "whoami"})
    assert link.revoke_device(registration["device_id"])
    with pytest.raises(PermissionError):
        link.enqueue(registration["device_id"], "open_app", {"name": "chrome"})


def test_command_payload_cannot_carry_credentials(link):
    registration = _approved_windows(link)
    with pytest.raises(ValueError):
        link.enqueue(registration["device_id"], "ask",
                     {"text": "hello", "api_key": "fixture-secret"})
    with pytest.raises(ValueError):
        link.enqueue(registration["device_id"], "ask",
                     {"text": "Authorization: Bearer fixture-token"})


def test_queue_waits_for_offline_device_deduplicates_and_expires(link, monkeypatch):
    registration = _approved_windows(link)
    command = link.enqueue(
        registration["device_id"], "open_app", {"name": "calculator"},
        idempotency_key="same-request", expires_in_s=30)
    assert command.status == WAITING_FOR_DEVICE
    duplicate = link.enqueue(
        registration["device_id"], "open_app", {"name": "calculator"},
        idempotency_key="same-request", expires_in_s=30)
    assert duplicate.id == command.id
    future = command.expires + 1
    monkeypatch.setattr(device_link.time, "time", lambda: future)
    assert link.command(command.id).status != EXPIRED
    link.stats()
    assert link.command(command.id).status == EXPIRED


def test_sensitive_command_cannot_be_claimed_before_owner_approval(link):
    registration = _approved_windows(link)
    assert link.heartbeat(registration["device_id"])
    command = link.enqueue(
        registration["device_id"], "close_app", {"name": "word"},
        requires_approval=True, requesting_device="owner-phone")
    assert command.status == PENDING_APPROVAL and command.approval_id
    assert link.claim(registration["device_id"]) == []
    assert link.decide_approval(command.approval_id, approve=True,
                                requesting_device="owner-phone", evidence="owner passkey")
    claimed = link.claim(registration["device_id"])
    assert [item.id for item in claimed] == [command.id]


def test_kill_switch_cancels_queued_work_and_blocks_new_commands(link):
    registration = _approved_windows(link)
    command = link.enqueue(registration["device_id"], "open_app", {"name": "chrome"})
    result = link.set_remote_control(False, requesting_device="owner-phone")
    assert result["enabled"] is False and result["cancelled_commands"] == 1
    assert link.command(command.id).status == CANCELLED
    assert link.claim(registration["device_id"]) == []
    with pytest.raises(PermissionError):
        link.enqueue(registration["device_id"], "open_app", {"name": "chrome"})


def test_activity_is_human_readable_and_redacts_secret_shaped_values(link):
    registration = _approved_windows(link)
    link._activity("test", target_device=registration["device_id"],
                   summary="Authorization: Bearer fixture-secret")
    row = link.activity(limit=1)[0]
    assert row["summary"] == "[REDACTED]"
    assert "fixture-secret" not in str(row)


def test_cloud_owner_routes_use_httponly_cookies_csrf_and_device_approval(
        owner, link, monkeypatch):
    policy.reset_rates()
    monkeypatch.setattr(cloud_api, "get_owner_auth", lambda: owner)
    monkeypatch.setattr(cloud_api.device_link, "get_link", lambda: link)
    app = FastAPI()
    cloud_api.register(app)
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/api/owner/auth/status").status_code == 200
        assert client.get("/api/owner/status").status_code == 401
        response = client.post("/api/owner/auth/login", json={
            "email": "owner@example.com", "password": "correct horse battery staple",
            "nonce": "api-login-nonce-xxxxxxxx", "device": "Test browser",
            "device_id": "browser_cloud_test_0001",
        })
        assert response.status_code == 200
        body = response.json()
        assert "session" not in body and "refresh" not in body
        assert body["device_state"] == "PENDING" and body["trusted"] is False
        assert "httponly" in response.headers["set-cookie"].casefold()
        assert client.get("/api/owner/status").status_code == 403
        assert owner.approve_browser_device(body["device_id"])
        assert client.get("/api/owner/status").status_code == 200
        assert client.post("/api/owner/devices/register", json={"label": "Laptop"}).status_code == 401
        registered = client.post(
            "/api/owner/devices/register", json={"label": "Laptop"},
            headers={"X-Zeno-CSRF": body["csrf"]})
        assert registered.status_code == 200
        target = registered.json()
        assert target["approval_state"] == "PENDING"
        approved = client.post(
            "/api/owner/devices/approve",
            json={"device_id": target["device_id"], "scopes": ["standard_device"]},
            headers={"X-Zeno-CSRF": body["csrf"]})
        assert approved.json()["ok"] is True
        bad = client.post(
            "/api/owner/command",
            json={"device_id": target["device_id"], "action": "run_shell"},
            headers={"X-Zeno-CSRF": body["csrf"]})
        assert bad.status_code == 400


def test_desktop_executor_uses_permission_gated_tool_and_app_allowlist(monkeypatch):
    calls = []
    monkeypatch.setattr("reyes_agent.tools.run_tool",
                        lambda name, args: calls.append((name, args)) or
                        "Opened 'calculator'; postcondition verified: Calculator window.")
    ok, result = _run_tool("open_app", {"name": "calculator"})
    assert ok and result["tool"] == "open_app"
    assert calls == [("open_app", {"name_or_path": "calculator"})]
    with pytest.raises(ValueError):
        _args_open_app({"name": "..\\cmd.exe & whoami"})
    assert "close_app" not in ACTION_TOOLS and "run_automation" not in ACTION_TOOLS


def test_desktop_chat_uses_the_shared_web_conversation(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "reyes_agent.web._conversation_turn",
        lambda context, message: calls.append(message) or {"reply": "same ZENO", "tool_calls": []})
    ok, result = _exec_ask({"text": "hello ZENO"})
    assert ok and result["answer"] == "same ZENO" and calls == ["hello ZENO"]


def test_nonlocal_connector_refuses_plain_http_before_network_access():
    agent = DesktopAgent(AgentConfig(
        gateway="http://public.example", device_id="dev", token="fixture"))
    with pytest.raises(ValueError, match="HTTPS"):
        agent._post("/api/owner/device/heartbeat", {})


def test_standalone_gateway_isolated_health_and_security_headers(owner, link, monkeypatch):
    from reyes_agent.anywhere_gateway import create_app

    policy.reset_rates()
    monkeypatch.setattr(cloud_api, "get_owner_auth", lambda: owner)
    monkeypatch.setattr(cloud_api.device_link, "get_link", lambda: link)
    gateway = create_app(enabled=True)
    with TestClient(gateway, base_url="https://testserver") as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["service"] == "zeno-anywhere-gateway"
        assert "devices" not in response.json() and "auth" not in response.json()
        assert response.headers["x-frame-options"] == "DENY"
        assert "max-age=" in response.headers["strict-transport-security"]
        assert client.get("/api/owner/status").status_code == 401


def test_gateway_fails_closed_when_remote_access_disabled():
    from reyes_agent.anywhere_gateway import create_app

    gateway = create_app(enabled=False)
    with TestClient(gateway, base_url="https://testserver") as client:
        assert client.get("/health").json()["state"] == "DISABLED"
        assert client.get("/api/owner/auth/status").status_code == 503
