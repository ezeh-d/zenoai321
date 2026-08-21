from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reyes_agent.auth import owner as owner_auth
from reyes_agent.devices.android_device import AndroidDevice
from reyes_agent.devices.protocol import DeviceRequest
from reyes_agent.remote_access import (android_pairing, cloud_api, deployment,
                                       device_link, policy)


def test_android_pairing_is_hashed_six_digit_expiring_and_one_time(tmp_path):
    clock = [1000.0]
    store = android_pairing.AndroidPairingStore(
        tmp_path / "android-pairing.sqlite", now=lambda: clock[0])
    offer = store.create(
        browser_device="trusted_browser", gateway="https://zeno.example.com")
    assert offer["manual_code"].isdigit()
    assert len(offer["manual_code"]) == 6
    assert offer["pairing_uri"].startswith("zeno://pair?")
    assert offer["qr_png"].startswith("data:image/png;base64,")

    on_disk = b"".join(path.read_bytes() for path in tmp_path.iterdir())
    assert offer["credential"].encode() not in on_disk
    assert offer["manual_code"].encode() not in on_disk

    consumed = store.consume(offer["manual_code"])
    assert consumed["browser_device"] == "trusted_browser"
    with pytest.raises(android_pairing.PairingError):
        store.consume(offer["credential"])

    expired = store.create(
        browser_device="trusted_browser", gateway="https://zeno.example.com")
    clock[0] += android_pairing.PAIR_TTL_S + 1
    with pytest.raises(android_pairing.PairingError):
        store.consume(expired["credential"])


def test_a_new_pair_cancels_the_previous_browser_offer(tmp_path):
    store = android_pairing.AndroidPairingStore(tmp_path / "pair.sqlite")
    first = store.create(browser_device="browser", gateway="https://zeno.example.com")
    second = store.create(browser_device="browser", gateway="https://zeno.example.com")
    with pytest.raises(android_pairing.PairingError):
        store.consume(first["credential"])
    assert store.consume(second["credential"])["id"] == second["id"]


@pytest.mark.parametrize("operation", [
    "BACK", "HOME", "RECENTS", "NOTIFICATIONS", "QUICK_SETTINGS",
    "SCROLL_UP", "SCROLL_DOWN",
])
def test_android_action_allowlist_accepts_only_bounded_global_actions(operation):
    assert device_link.validate_android_action({
        "operation": operation, "target": ""})["operation"] == operation


@pytest.mark.parametrize("operation", [
    "TAP", "TYPE", "GESTURE", "PAY", "PURCHASE", "SEND", "DELETE",
    "INSTALL", "CHANGE_PERMISSION", "RUN_SHELL",
])
def test_android_action_allowlist_refuses_arbitrary_or_sensitive_actions(operation):
    with pytest.raises(ValueError, match="Unsupported"):
        device_link.validate_android_action({"operation": operation})


def test_android_open_app_rejects_security_and_malformed_packages():
    assert device_link.validate_android_action({
        "operation": "OPEN_APP", "target": "com.android.chrome",
    })["target"] == "com.android.chrome"
    for target in ("com.android.settings", "../settings", "com.zeno.companion"):
        with pytest.raises(ValueError):
            device_link.validate_android_action({
                "operation": "OPEN_APP", "target": target})


def test_device_link_requires_android_platform_and_android_scope(tmp_path):
    link = device_link.DeviceLink(tmp_path / "devices.sqlite")
    windows = link.register(
        label="Windows", platform="windows", approved=True,
        scopes=["android_control"])
    with pytest.raises(ValueError, match="Android target"):
        link.enqueue(windows["device_id"], "android_action", {"operation": "HOME"})

    phone = link.register(label="Phone", platform="android", approved=True)
    with pytest.raises(PermissionError, match="scope"):
        link.enqueue(phone["device_id"], "android_action", {"operation": "HOME"})

    assert link.approve_device(phone["device_id"], scopes=["android_control"])
    assert link.heartbeat(phone["device_id"])
    command = link.enqueue(
        phone["device_id"], "android_action", {"operation": "HOME"})
    assert command.action == "android_action"
    assert command.status == device_link.QUEUED
    with pytest.raises(ValueError, match="only bounded Android"):
        link.enqueue(phone["device_id"], "open_app", {"name": "chrome"})


def test_android_adapter_reports_success_only_after_device_completion(tmp_path):
    link = device_link.reset_for_tests(tmp_path / "devices.sqlite")
    phone = link.register(
        label="Phone", platform="android", approved=True,
        scopes=["android_control"])
    assert link.heartbeat(phone["device_id"])

    def device_worker():
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            claimed = link.claim(phone["device_id"])
            if claimed:
                command = claimed[0]
                assert link.acknowledge(command.id, phone["device_id"])
                assert link.complete(
                    command.id, phone["device_id"], ok=True,
                    result={"summary": "Android accepted HOME",
                            "evidence": {"android_api_accepted": True}})
                return
            time.sleep(0.02)
        raise AssertionError("Android command was not observed")

    worker = threading.Thread(target=device_worker)
    worker.start()
    response = AndroidDevice(phone["device_id"]).execute(DeviceRequest(
        goal="Go home", plan=[{"operation": "HOME", "target": ""}],
        approved=True))
    worker.join(timeout=2)
    assert response.ok is True
    assert response.evidence["state"] == device_link.DONE
    assert response.evidence["device_result"]["evidence"]["android_api_accepted"] is True


def _trusted_session(client: TestClient, auth) -> dict:
    login = client.post("/api/owner/auth/login", json={
        "email": "owner@example.com",
        "password": "correct horse battery staple",
        "nonce": "android-pairing-login-nonce",
        "device": "Owner browser",
        "device_id": "browser_android_owner",
    })
    assert login.status_code == 200, login.text
    body = login.json()
    assert auth.approve_browser_device(body["device_id"])
    return body


def test_authenticated_pairing_to_pending_android_device_lifecycle(tmp_path, monkeypatch):
    policy.reset_rates()
    auth = owner_auth.reset_for_tests(tmp_path / "owner.sqlite")
    auth.provision("owner@example.com", "correct horse battery staple")
    link = device_link.reset_for_tests(tmp_path / "devices.sqlite")
    store = android_pairing.reset_for_tests(tmp_path / "pair.sqlite")
    monkeypatch.setattr(cloud_api, "get_owner_auth", lambda: auth)
    monkeypatch.setattr(cloud_api.device_link, "get_link", lambda: link)
    monkeypatch.setattr(cloud_api.android_pairing, "get_store", lambda: store)
    monkeypatch.setattr(cloud_api.domains, "is_allowed_origin", lambda origin: origin == "https://testserver")
    monkeypatch.setattr(cloud_api.web_push.get_service(), "enqueue", lambda *a, **k: None)

    app = FastAPI()
    cloud_api.register(app)
    with TestClient(app, base_url="https://testserver") as client:
        session = _trusted_session(client, auth)
        headers = {"X-Zeno-CSRF": session["csrf"], "Origin": "https://testserver"}
        offer_response = client.post(
            "/api/owner/android/pairings", headers=headers, json={})
        assert offer_response.status_code == 200, offer_response.text
        offer = offer_response.json()
        assert "credential" not in offer
        assert "pairing_uri" not in offer

        claim = client.post("/api/owner/android/pairing/claim", json={
            "credential": offer["manual_code"], "label": "Divine's Android",
        })
        assert claim.status_code == 200, claim.text
        registered = claim.json()
        assert registered["approval_state"] == device_link.PENDING_DEVICE
        state = link.device_state(registered["device_id"])
        assert state["platform"] == "android"
        assert link.authenticate(registered["device_id"], registered["token"]) is False

        approved = client.post(
            "/api/owner/devices/approve", headers=headers,
            json={"device_id": registered["device_id"],
                  "scopes": ["standard_device"]})
        assert approved.status_code == 200 and approved.json()["ok"] is True
        state = link.device_state(registered["device_id"])
        assert state["scopes"] == ["android_control"]
        assert link.authenticate(registered["device_id"], registered["token"]) is True
        second = client.post("/api/owner/android/pairing/claim", json={
            "credential": offer["manual_code"], "label": "Attacker",
        })
        assert second.status_code == 403


def test_native_manifest_uses_visible_owner_granted_android_capabilities_only():
    root = Path("android/zeno-companion/app/src/main")
    manifest = (root / "AndroidManifest.xml").read_text(encoding="utf-8")
    overlay = (root / "java/com/zeno/companion/OverlayService.kt").read_text(encoding="utf-8")
    actions = (root / "java/com/zeno/companion/ActionPolicy.kt").read_text(encoding="utf-8")
    secure = (root / "java/com/zeno/companion/SecureStore.kt").read_text(encoding="utf-8")

    assert "SYSTEM_ALERT_WINDOW" in manifest
    assert "FOREGROUND_SERVICE_SPECIAL_USE" in manifest
    assert "BIND_ACCESSIBILITY_SERVICE" in manifest
    assert "TYPE_APPLICATION_OVERLAY" in overlay
    assert "startForeground(" in overlay
    assert "AndroidKeyStore" in secure and "AES/GCM/NoPadding" in secure
    assert "TAP" not in ActionPolicyOperations(actions)
    for forbidden in ("RECORD_AUDIO", "CAMERA", "READ_SMS", "SEND_SMS",
                      "REQUEST_INSTALL_PACKAGES", "MANAGE_EXTERNAL_STORAGE"):
        assert forbidden not in manifest


def ActionPolicyOperations(source: str) -> set[str]:
    start = source.index("allowedOperations")
    end = source.index(")", start)
    return {item.strip(' \n\t\r\"') for item in source[start:end].split(",")}


def test_phone_action_tool_is_registered_and_always_requires_confirmation():
    from reyes_agent.tools import TOOLS

    assert "phone_action" in TOOLS
    assert TOOLS["phone_action"].requires_confirmation is True


def test_production_preflight_requires_persistent_android_pairing_db(tmp_path, monkeypatch):
    monkeypatch.setattr(deployment.domains, "dev_mode", lambda: False)
    monkeypatch.setattr(deployment.domains, "public_domain", lambda: "zeno.example.com")
    monkeypatch.setattr(deployment.domains, "allowed_origins", lambda: ["https://zeno.example.com"])
    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    for key, filename in {
        "ZENO_OWNER_AUTH_DB": "owner.sqlite",
        "ZENO_DEVICE_LINK_DB": "devices.sqlite",
        "ZENO_MEDIA_STORE_DB": "media.sqlite",
        "ZENO_WEB_PUSH_DB": "push.sqlite",
    }.items():
        monkeypatch.setenv(key, str(tmp_path / filename))
    monkeypatch.delenv("ZENO_ANDROID_PAIRING_DB", raising=False)
    result = deployment.preflight()
    assert result["ok"] is False
    assert any("ZENO_ANDROID_PAIRING_DB" in error for error in result["errors"])

    monkeypatch.setenv("ZENO_ANDROID_PAIRING_DB", str(tmp_path / "android-pairing.sqlite"))
    assert deployment.preflight()["configured_paths"]["ZENO_ANDROID_PAIRING_DB"] is True
