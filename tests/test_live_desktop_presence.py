"""Security, media and shared-presence contracts for phone Live Desktop."""
from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from reyes_agent import agent_presence, agent_runtime
from reyes_agent.auth import owner as owner_auth
from reyes_agent.remote_access import device_link, live_desktop
from reyes_agent.remote_access.live_desktop_node import (
    END_PATH, SIGNAL_PATH, STATUS_PATH, LiveDesktopNode, NodeConfig,
    RemoteInputWorker, _ice_complete, capabilities,
)


EMAIL = "owner@example.com"
PASSWORD = "correct horse battery staple"


def _offer() -> dict[str, str]:
    return {"type": "offer", "sdp": "v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\n"}


def test_signalling_is_bounded_owned_and_replaces_duplicate_peers(monkeypatch):
    manager = live_desktop.LiveDesktopManager(maximum=1)
    first = manager.create(browser_device="browser-a", target_device="pc-a")
    manager.owner_signal(first.id, "browser-a", _offer())
    assert manager.claim("pc-a", wait_s=0)["id"] == first.id
    with pytest.raises(live_desktop.SessionAccessDenied):
        manager.session_for_owner(first.id, "browser-b")
    with pytest.raises(live_desktop.SessionAccessDenied):
        manager.device_signal(first.id, "pc-b", {"type": "answer", "sdp": _offer()["sdp"]})

    # Replacement is allowed even at capacity and leaves no hidden duplicate.
    second = manager.create(browser_device="browser-a", target_device="pc-a")
    assert second.id != first.id
    assert manager.session_for_owner(first.id, "browser-a").state == live_desktop.ENDED
    assert manager.stats()["active_sessions"] == 1

    with pytest.raises(live_desktop.SessionCapacityExceeded):
        manager.create(browser_device="browser-b", target_device="pc-b")
    with pytest.raises(ValueError):
        manager.owner_signal(second.id, "browser-a", {"type": "offer", "sdp": "not sdp"})

    future = second.expires + 1
    monkeypatch.setattr(live_desktop.time, "time", lambda: future)
    assert manager.session_for_owner(second.id, "browser-a").state == live_desktop.EXPIRED
    assert manager.device_status(second.id, "pc-a", state="CONNECTED")["terminate"] is True


def test_kill_switch_termination_can_target_mode_or_device():
    manager = live_desktop.LiveDesktopManager(maximum=4)
    view = manager.create(browser_device="browser-a", target_device="pc-a", mode="VIEW_ONLY")
    control = manager.create(browser_device="browser-b", target_device="pc-b", mode="REMOTE_CONTROL")
    assert manager.end_all("control disabled", modes={"REMOTE_CONTROL"}) == 1
    assert manager.session_for_owner(control.id, "browser-b").state == live_desktop.ENDED
    assert manager.session_for_owner(view.id, "browser-a").state == live_desktop.REQUESTED
    assert manager.end_all("device revoked", target_device="pc-a") == 1


def test_presence_projection_is_sanitized_and_stale_state_is_not_restored(monkeypatch):
    manager = live_desktop.LiveDesktopManager()
    projection = manager.update_presence("pc-a", {"active_agents": [
        {"id": "stark", "name": " STARK  ", "role": "security\nlead",
         "color": "javascript:red", "state": "thinking", "current_task": "x" * 500},
        {"id": "../bad", "name": "bad"},
    ], "current_speaker": "stark"})
    assert [row["id"] for row in projection["active_agents"]] == ["stark"]
    row = projection["active_agents"][0]
    assert row["color"] == "#719bff" and len(row["current_task"]) == 180
    assert manager.presence("pc-a")["state"] == "CURRENT"
    monkeypatch.setattr(live_desktop.time, "time", lambda: projection["at"] + 80)
    stale = manager.presence("pc-a")
    assert stale["state"] == "STALE" and stale["active_agents"] == []


def test_natural_summon_standby_and_council_never_start_workers(monkeypatch):
    manager = agent_presence.reset_for_tests()
    monkeypatch.setattr(agent_runtime, "ensure_worker",
                        lambda *_args, **_kwargs: pytest.fail("visual summon started a worker"))
    assert agent_presence.handle_command("ZENO, get the security guy.") == "STARK is here."
    assert manager.active_ids() == ["stark"]
    assert "already here" in agent_presence.handle_command("Call STARK again.").casefold()
    reply = agent_presence.handle_command("Bring KATE and ORACLE.")
    assert "KATE" in reply and "ORACLE" in reply
    assert manager.snapshot()["last_addressed"] == "oracle"
    assert "standing by" in agent_presence.handle_command("STARK, standby.").casefold()
    assert set(manager.active_ids()) == {"kate", "oracle"}
    assert agent_presence.handle_command("ZENO, standby.") is None
    assert "council" in agent_presence.handle_command("Call the council.").casefold()
    assert len(manager.active_ids()) <= manager.snapshot()["maximum"]
    assert "standing by" in agent_presence.handle_command("All agents standby.").casefold()
    assert manager.active_ids() == []


def test_presence_transitions_are_real_event_bus_events():
    from reyes_agent import event_bus

    agent_presence.reset_for_tests()
    feed = event_bus.subscribe()
    try:
        agent_presence.handle_command("Call STARK.")
        agent_presence.handle_command("STARK, standby.")
        observed = [feed.get(timeout=1).type for _ in range(3)]
    finally:
        event_bus.unsubscribe(feed)
    assert observed == ["agent.joined", "agent.standby", "agent.removed"]


def test_remote_input_schema_is_fixed_and_bounded(monkeypatch):
    calls: list[tuple] = []
    fake = SimpleNamespace(
        click=lambda *a, **k: calls.append(("click", a, k)),
        doubleClick=lambda *a, **k: calls.append(("double", a, k)),
        moveTo=lambda *a, **k: calls.append(("move", a, k)),
        mouseDown=lambda *a, **k: calls.append(("down", a, k)),
        mouseUp=lambda *a, **k: calls.append(("up", a, k)),
        scroll=lambda *a, **k: calls.append(("scroll", a, k)),
        press=lambda *a, **k: calls.append(("key", a, k)),
        keyDown=lambda *a, **k: calls.append(("keyDown", a, k)),
        keyUp=lambda *a, **k: calls.append(("keyUp", a, k)),
        write=lambda *a, **k: calls.append(("write", a, k)),
    )
    monkeypatch.setitem(sys.modules, "pyautogui", fake)
    worker = object.__new__(RemoteInputWorker)
    worker._monitor = {"left": 100, "top": 50, "width": 1000, "height": 500}
    worker._pressed_keys = set()
    worker._pressed_buttons = set()
    worker._apply({"type": "pointer", "action": "click", "x": 2, "y": -1})
    worker._apply({"type": "key", "action": "press", "key": "F12"})
    worker._apply({"type": "text", "text": "safe text"})
    worker._apply({"type": "shell", "command": "whoami"})
    assert calls[0][0] == "click" and calls[0][1] == (1099, 50)
    assert [call[0] for call in calls] == ["click", "write"]


@pytest.fixture()
def gateway_client(tmp_path: Path, monkeypatch):
    from reyes_agent import anywhere_gateway

    owner = owner_auth.reset_for_tests(tmp_path / "owner.sqlite")
    owner.provision(EMAIL, PASSWORD)
    link = device_link.reset_for_tests(tmp_path / "devices.sqlite")
    link.set_remote_control(True, requesting_device="pytest")
    live_desktop.reset_for_tests()
    app = anywhere_gateway.create_app(enabled=True)
    with TestClient(app, client=("127.0.0.1", 42345), base_url="https://testserver") as client:
        login = client.post("/api/owner/auth/login", json={
            "email": EMAIL, "password": PASSWORD, "nonce": "n" * 32,
            "device_id": "browser_test_device_0001",
        })
        assert login.status_code == 200, login.text
        session = login.json()
        owner.approve_browser_device(session["device_id"])
        registration = link.register(label="Main Laptop", platform="windows")
        link.approve_device(registration["device_id"], scopes=["standard_device"])
        link.heartbeat(registration["device_id"])
        live_desktop.get_live_desktop().register_capabilities(registration["device_id"], {
            "available": True, "streaming_enabled": True, "control_enabled": True,
            "audio_available": False, "active_display": "display-1",
            "monitors": [{"id": "display-1", "label": "Display 1",
                          "width": 1920, "height": 1080, "primary": True}],
        })
        yield client, owner, link, session, registration


def test_live_desktop_api_requires_trusted_owner_and_three_control_gates(
        gateway_client, monkeypatch):
    client, owner, link, session, registration = gateway_client
    target = registration["device_id"]
    anonymous = TestClient(client.app, base_url="https://testserver")
    assert anonymous.get(f"/api/owner/live-desktop/capabilities?device_id={target}").status_code == 401

    headers = {"X-Zeno-CSRF": session["csrf"]}
    view = client.post("/api/owner/live-desktop/sessions", headers=headers, json={
        "device_id": target, "mode": "VIEW_ONLY", "monitor": "display-1",
    })
    assert view.status_code == 200 and view.json()["media_transport"] == "WEBRTC_DTLS_SRTP"
    assert "sdp" not in json.dumps(view.json()).casefold()

    denied = client.post("/api/owner/live-desktop/sessions", headers=headers, json={
        "device_id": target, "mode": "REMOTE_CONTROL", "monitor": "display-1",
    })
    assert denied.status_code == 403 and "fingerprint" in denied.text.casefold()
    monkeypatch.setattr(owner, "session_elevated", lambda _token: True)
    allowed = client.post("/api/owner/live-desktop/sessions", headers=headers, json={
        "device_id": target, "mode": "REMOTE_CONTROL", "monitor": "display-1",
    })
    assert allowed.status_code == 200
    off = client.post("/api/owner/remote-control", headers=headers, json={"enabled": False})
    assert off.status_code == 200 and off.json()["live_sessions_ended"] == 1
    assert live_desktop.get_live_desktop().stats()["active_sessions"] == 0


def test_unpaired_device_cannot_claim_or_signal(gateway_client):
    client, _owner, _link, _session, registration = gateway_client
    bad = {"device_id": registration["device_id"], "token": "not-the-device-token", "wait_s": 0}
    assert client.post("/api/owner/device/live-desktop/claim", json=bad).status_code == 401
    assert client.post("/api/owner/device/live-desktop/signal", json={
        **bad, "session_id": "lds_missing", "signal": _offer(),
    }).status_code == 401


def test_real_loopback_webrtc_delivers_screen_frames():
    cap = capabilities(NodeConfig("", "", ""))
    if not cap["available"]:
        pytest.skip(cap["detail"])

    async def scenario() -> None:
        from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription

        phone = RTCPeerConnection(configuration=RTCConfiguration(iceServers=[]))
        phone.addTransceiver("video", direction="recvonly")
        phone.createDataChannel("zeno-session", ordered=False, maxRetransmits=1)
        offer = await phone.createOffer()
        await phone.setLocalDescription(offer)
        await _ice_complete(phone, 2.0)

        class FakeGateway:
            answer: dict | None = None

            @staticmethod
            def auth():
                return {"device_id": "pc-a", "token": "fixture"}

            def post(self, path, body, *, timeout=0):
                if path == SIGNAL_PATH:
                    self.answer = dict(body["signal"])
                if path == STATUS_PATH:
                    return {"terminate": False}
                if path == END_PATH:
                    return {"ok": True}
                return {}

        fake = FakeGateway()
        node = LiveDesktopNode(NodeConfig("https://example.invalid", "pc-a", "fixture"))
        node.client = fake
        stop = threading.Event()
        session = {"id": "lds_loopback", "mode": "VIEW_ONLY", "monitor": "display-1",
                   "quality": "LOW", "show_cursor": False, "control_allowed": False,
                   "offer": {"type": phone.localDescription.type,
                             "sdp": phone.localDescription.sdp}}
        task = asyncio.create_task(node._peer(session, [], stop))
        try:
            deadline = time.monotonic() + 8
            while fake.answer is None and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            assert fake.answer is not None
            await phone.setRemoteDescription(RTCSessionDescription(**fake.answer))
            deadline = time.monotonic() + 8
            receiver = next(trans.receiver for trans in phone.getTransceivers()
                            if trans.kind == "video")
            frame = await asyncio.wait_for(receiver.track.recv(), timeout=max(0.1, deadline-time.monotonic()))
            assert frame.width <= 960 and frame.height <= 540 and frame.format.name
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=7)
            await asyncio.wait_for(phone.close(), timeout=4)

    asyncio.run(scenario())


def test_phone_and_windows_surfaces_use_webrtc_and_dynamic_presence():
    root = Path(__file__).parents[1]
    phone = (root / "reyes_agent" / "static" / "app.html").read_text("utf-8")
    desktop = (root / "reyes_agent" / "static" / "index.html").read_text("utf-8")
    mini = (root / "reyes_agent" / "static" / "mini.html").read_text("utf-8")
    presence_js = (root / "reyes_agent" / "static" / "agent_presence.js").read_text("utf-8")
    assert "RTCPeerConnection" in phone and "View My PC" in phone
    assert "setInterval" in phone and "desktopFps" in phone
    assert "agent-presence" in phone and "renderPhoneAgents" in phone
    assert "agent.joined" in presence_js and "agent.removed" in presence_js
    assert "PHONE CONNECTED" in desktop and "/api/live-desktop/end" in desktop
    assert "PHONE LIVE VIEW" in mini
    # No screenshot-over-HTTP implementation and no browser-side Windows tool duplicate.
    assert "/screenshot" not in phone.casefold()
    assert "pyautogui" not in phone.casefold()
