"""End-to-end contracts for the completed Anywhere voice/push/deployment layer."""

from __future__ import annotations

import base64
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reyes_agent.auth.owner import OwnerAuthService
from reyes_agent.remote_access import cloud_api, deployment, media_store, policy, web_push
from reyes_agent.remote_access.desktop_agent import AgentConfig, DesktopAgent, _run_tool
from reyes_agent.remote_access.device_link import DeviceLink


def _key() -> str:
    return base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("=")


def _services(tmp_path: Path):
    owner = OwnerAuthService(tmp_path / "owner.sqlite")
    assert owner.provision("owner@example.com", "correct horse battery staple")[0]
    link = DeviceLink(tmp_path / "devices.sqlite")
    store = media_store.MediaStore(tmp_path / "media.sqlite", key=b"m" * 32)
    return owner, link, store


def _login_and_trust(client: TestClient, owner: OwnerAuthService) -> dict:
    response = client.post("/api/owner/auth/login", json={
        "email": "owner@example.com", "password": "correct horse battery staple",
        "nonce": "voice-route-login-nonce-0001", "device": "Owner phone",
        "device_id": "browser_voice_route_0001",
    })
    body = response.json()
    assert response.status_code == 200 and owner.approve_browser_device(body["device_id"])
    return body


def test_authenticated_voice_media_full_lifecycle(tmp_path, monkeypatch):
    owner, link, store = _services(tmp_path)
    policy.reset_rates()
    monkeypatch.setattr(cloud_api, "get_owner_auth", lambda: owner)
    monkeypatch.setattr(cloud_api.device_link, "get_link", lambda: link)
    monkeypatch.setattr(cloud_api.media_store, "get_media_store", lambda: store)
    monkeypatch.setattr(cloud_api.web_push, "get_service", lambda: type(
        "NoPush", (), {"enqueue": staticmethod(lambda *a, **k: False)})())
    app = FastAPI()
    cloud_api.register(app)
    with TestClient(app, base_url="https://testserver") as client:
        session = _login_and_trust(client, owner)
        registered = client.post("/api/owner/devices/register", json={"label": "Laptop"},
                                 headers={"X-Zeno-CSRF": session["csrf"]}).json()
        assert client.post("/api/owner/devices/approve",
                           json={"device_id": registered["device_id"]},
                           headers={"X-Zeno-CSRF": session["csrf"]}).json()["ok"]
        device_id, token = registered["device_id"], registered["token"]
        client.post("/api/owner/device/heartbeat", json={"device_id": device_id,
                                                         "token": token})

        uploaded = client.post(
            "/api/owner/voice", data={"device_id": device_id},
            files={"clip": ("voice.webm", b"fixture-opus-audio", "audio/webm")},
            headers={"X-Zeno-CSRF": session["csrf"]})
        assert uploaded.status_code == 200, uploaded.text
        command = uploaded.json()
        claimed = client.post("/api/owner/device/claim",
                              json={"device_id": device_id, "token": token}).json()["commands"]
        assert [row["id"] for row in claimed] == [command["id"]]

        source = client.post("/api/owner/device/media/read", json={
            "device_id": device_id, "token": token, "command_id": command["id"],
            "media_id": command["media_id"]})
        assert source.status_code == 200 and source.content == b"fixture-opus-audio"
        assert client.post("/api/owner/device/media/write", data={
            "device_id": device_id, "token": token, "command_id": command["id"],
            "media_id": command["media_id"]},
            files={"audio": ("answer.mp3", b"fixture-mp3", "audio/mpeg")}).json()["ok"]
        assert client.post("/api/owner/device/complete", json={
            "device_id": device_id, "token": token, "command_id": command["id"],
            "success": True, "result": {"answer": "Hello", "transcript": "ZENO hello",
                                          "audio_id": command["media_id"]}}).json()["ok"]

        answer = client.get("/api/owner/voice/" + command["media_id"])
        assert answer.status_code == 200 and answer.content == b"fixture-mp3"
        assert answer.headers["cache-control"] == "no-store"
        # Raw input is cryptographically discarded at terminal completion.
        try:
            store.read_input(command["media_id"], target_device=device_id,
                             command_id=command["id"])
        except media_store.MediaNotFound:
            pass
        else:
            raise AssertionError("raw input remained after voice completion")


def test_pending_browser_cannot_upload_voice(tmp_path, monkeypatch):
    owner, link, store = _services(tmp_path)
    policy.reset_rates()
    monkeypatch.setattr(cloud_api, "get_owner_auth", lambda: owner)
    monkeypatch.setattr(cloud_api.device_link, "get_link", lambda: link)
    monkeypatch.setattr(cloud_api.media_store, "get_media_store", lambda: store)
    app = FastAPI()
    cloud_api.register(app)
    with TestClient(app, base_url="https://testserver") as client:
        response = client.post("/api/owner/auth/login", json={
            "email": "owner@example.com", "password": "correct horse battery staple",
            "nonce": "pending-voice-nonce-000001", "device_id": "pending_voice_browser"})
        csrf = response.json()["csrf"]
        denied = client.post("/api/owner/voice", data={"device_id": "dev_x"},
                             files={"clip": ("v.webm", b"audio", "audio/webm")},
                             headers={"X-Zeno-CSRF": csrf})
        assert denied.status_code == 403


def test_push_subscriptions_are_encrypted_and_bound_to_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(web_push, "_safe_endpoint", lambda value: value)
    service = web_push.WebPushService(
        tmp_path / "push.sqlite", encryption_key=_key(), public_key="public-vapid",
        private_key="private-vapid", subject="mailto:owner@example.com")
    result = service.register("browser_1", {
        "endpoint": "https://fcm.googleapis.com/fcm/send/fixture",
        "keys": {"p256dh": "public-client-key", "auth": "client-auth-secret"}})
    assert result["ok"] and service.status()["subscriptions"] == 1
    blob = (tmp_path / "push.sqlite").read_bytes()
    assert b"client-auth-secret" not in blob and b"public-client-key" not in blob
    assert service.unregister_browser("browser_2") == 0
    assert service.unregister_browser("browser_1") == 1
    service.shutdown()


def test_permission_queue_is_never_reported_as_remote_success(monkeypatch):
    monkeypatch.setattr("reyes_agent.tools.run_tool", lambda *_args, **_kwargs:
                        "Queued as request #7 -- explicit approval required; has NOT run yet.")
    ok, result = _run_tool("open_app", {"name": "calculator"})
    assert not ok and "did not run" in result["error"]


def test_production_preflight_rejects_multiple_sqlite_workers(monkeypatch, tmp_path):
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    monkeypatch.setattr(deployment.domains, "dev_mode", lambda: True)
    assert deployment.preflight()["ok"] is False
    assert "WEB_CONCURRENCY=1" in " ".join(deployment.preflight()["errors"])


def test_slow_remote_work_keeps_desktop_heartbeat_alive(monkeypatch):
    waits = iter([False, True])

    class Handle:
        def wait(self, _timeout):
            return next(waits)

        def result(self):
            return (True, {"answer": "done"})

        def cancel(self):
            return True

    class Pool:
        @staticmethod
        def submit(*_args, **_kwargs):
            return Handle()

    monkeypatch.setattr("reyes_agent.worker_pool.get_worker_pool", lambda: Pool())
    agent = DesktopAgent(AgentConfig("https://gateway.example", "device_1", "token_1"))
    heartbeats = []
    monkeypatch.setattr(agent, "_post", lambda path, body, timeout=0:
                        heartbeats.append((path, body, timeout)) or {"ok": True})
    assert agent._execute_with_heartbeat("ask", lambda: None)[0] is True
    assert heartbeats and heartbeats[0][0].endswith("/heartbeat")
    assert heartbeats[0][1]["state"] == "BUSY"


def test_admin_generates_ignored_secret_bundle_without_printing_private_key(tmp_path, capsys):
    from tools.zeno_anywhere_admin import main

    target = tmp_path / ".env.anywhere.secrets"
    assert main(["generate-secrets", "--output", str(target)]) == 0
    content = target.read_text(encoding="utf-8")
    assert "ZENO_MEDIA_ENCRYPTION_KEY=" in content
    assert "ZENO_WEB_PUSH_PRIVATE_KEY=" in content
    private_value = next(line.split("=", 1)[1] for line in content.splitlines()
                         if line.startswith("ZENO_WEB_PUSH_PRIVATE_KEY="))
    assert private_value and private_value not in capsys.readouterr().out
    assert main(["generate-secrets", "--output", str(target)]) == 2
