from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reyes_agent.auth import owner as owner_auth
from reyes_agent.remote_access import cloud_api, desktop_agent, device_link, policy
from reyes_agent.remote_access.attachment_store import (
    MAX_ATTACHMENT_BYTES,
    AttachmentAccessDenied,
    AttachmentCapacityExceeded,
    AttachmentNotFound,
    AttachmentStore,
)
from reyes_agent.remote_access.desktop_agent import AgentConfig, DesktopAgent


def _store(tmp_path: Path, **kwargs) -> AttachmentStore:
    return AttachmentStore(
        tmp_path / "attachments.sqlite", key=b"a" * 32, **kwargs)


def _ooxml(member: str, *, extra: str = "") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(member, "<document/>")
        if extra:
            archive.writestr(extra, b"macro")
    return buffer.getvalue()


def test_attachment_is_encrypted_bound_and_released(tmp_path):
    store = _store(tmp_path)
    raw = b"\x89PNG\r\n\x1a\n-private-owner-camera-frame"
    attachment_id = store.create(
        browser_device="browser_owner", target_device="dev_windows",
        data=raw, content_type="image/png", filename="receipt.png",
        purpose="camera")
    assert store.bind_command(
        attachment_id, command_id="cmd_camera_1",
        target_device="dev_windows")

    blob = store.read(
        attachment_id, target_device="dev_windows",
        command_id="cmd_camera_1")
    assert blob.data == raw
    assert blob.content_type == "image/png"
    assert blob.filename == "receipt.png"
    assert blob.purpose == "camera"

    on_disk = b"".join(
        path.read_bytes() for path in tmp_path.iterdir() if path.is_file())
    assert raw not in on_disk
    assert b"receipt.png" not in on_disk

    assert store.release(
        attachment_id, target_device="dev_windows",
        command_id="cmd_camera_1")
    with pytest.raises(AttachmentNotFound):
        store.read(
            attachment_id, target_device="dev_windows",
            command_id="cmd_camera_1")


def test_attachment_rejects_cross_device_and_cross_command(tmp_path):
    store = _store(tmp_path)
    attachment_id = store.create(
        browser_device="browser_a", target_device="desktop_a",
        data=b"hello", content_type="text/plain", filename="note.txt",
        purpose="file")
    assert store.bind_command(
        attachment_id, command_id="cmd_a", target_device="desktop_a")

    with pytest.raises(AttachmentAccessDenied):
        store.read(
            attachment_id, target_device="desktop_b", command_id="cmd_a")
    with pytest.raises(AttachmentAccessDenied):
        store.read(
            attachment_id, target_device="desktop_a", command_id="cmd_b")
    with pytest.raises(AttachmentAccessDenied):
        store.release(
            attachment_id, target_device="desktop_b", command_id="cmd_a")


@pytest.mark.parametrize("filename", [
    "../secret.txt", "folder/file.txt", r"folder\file.txt", "..", "a\x00b.txt",
])
def test_attachment_rejects_paths_and_unsafe_filenames(tmp_path, filename):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="filename"):
        store.create(
            browser_device="browser", target_device="desktop", data=b"x",
            content_type="text/plain", filename=filename, purpose="file")


def test_attachment_enforces_mime_purpose_size_expiry_and_record_cap(tmp_path):
    clock = [1000.0]
    store = _store(tmp_path, now=lambda: clock[0], max_records=1)
    with pytest.raises(ValueError, match="Unsupported"):
        store.create(
            browser_device="browser", target_device="desktop", data=b"x",
            content_type="application/x-msdownload", filename="evil.exe",
            purpose="file")
    with pytest.raises(ValueError, match="Camera attachments"):
        store.create(
            browser_device="browser", target_device="desktop", data=b"x",
            content_type="text/plain", filename="camera.txt",
            purpose="camera")
    with pytest.raises(ValueError, match="exceeds"):
        store.create(
            browser_device="browser", target_device="desktop",
            data=b"x" * (MAX_ATTACHMENT_BYTES + 1),
            content_type="image/jpeg", filename="large.jpg", purpose="camera")

    first = store.create(
        browser_device="browser", target_device="desktop", data=b"%PDF-one",
        content_type="application/pdf", filename="one.pdf", purpose="file",
        ttl_s=30)
    with pytest.raises(AttachmentCapacityExceeded):
        store.create(
            browser_device="browser", target_device="desktop", data=b"two",
            content_type="text/plain", filename="two.txt", purpose="file")
    clock[0] += 31
    with pytest.raises(AttachmentNotFound):
        store.read(first, target_device="desktop", command_id="cmd_missing")
    replacement = store.create(
        browser_device="browser", target_device="desktop", data=b"new",
        content_type="text/csv", filename="new.csv", purpose="file")
    assert replacement != first


def test_attachment_binding_is_one_time(tmp_path):
    store = _store(tmp_path)
    attachment_id = store.create(
        browser_device="browser", target_device="desktop", data=b'{"ok":true}',
        content_type="application/json", filename="data.json", purpose="file")
    assert store.bind_command(
        attachment_id, command_id="cmd_one", target_device="desktop")
    assert not store.bind_command(
        attachment_id, command_id="cmd_two", target_device="desktop")


def test_attachment_rejects_spoofed_mime_and_macro_office_files(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="image type"):
        store.create(
            browser_device="browser", target_device="desktop", data=b"MZevil",
            content_type="image/png", filename="safe.png", purpose="file")
    with pytest.raises(ValueError, match="does not match"):
        store.create(
            browser_device="browser", target_device="desktop", data=b"hello",
            content_type="text/plain", filename="renamed.exe", purpose="file")
    with pytest.raises(ValueError, match="Macro"):
        store.create(
            browser_device="browser", target_device="desktop",
            data=_ooxml("word/document.xml", extra="word/vbaProject.bin"),
            content_type=("application/vnd.openxmlformats-officedocument."
                          "wordprocessingml.document"),
            filename="report.docx", purpose="file")


def test_attachment_accepts_structurally_valid_ooxml(tmp_path):
    store = _store(tmp_path)
    attachment_id = store.create(
        browser_device="browser", target_device="desktop",
        data=_ooxml("xl/workbook.xml"),
        content_type=("application/vnd.openxmlformats-officedocument."
                      "spreadsheetml.sheet"),
        filename="figures.xlsx", purpose="file")
    assert attachment_id.startswith("att_")


def test_full_owner_upload_device_read_and_terminal_cleanup(
        tmp_path, monkeypatch):
    policy.reset_rates()
    auth = owner_auth.reset_for_tests(tmp_path / "owner.sqlite")
    auth.provision("owner@example.com", "correct horse battery staple")
    link = device_link.reset_for_tests(tmp_path / "devices.sqlite")
    link.set_remote_control(True)
    target = link.register(label="Laptop")
    assert link.approve_device(target["device_id"])
    store = _store(tmp_path)

    monkeypatch.setattr(cloud_api, "get_owner_auth", lambda: auth)
    monkeypatch.setattr(cloud_api.device_link, "get_link", lambda: link)
    monkeypatch.setattr(
        cloud_api.attachment_store, "get_attachment_store", lambda: store)
    monkeypatch.setattr(
        cloud_api.web_push.get_service(), "enqueue", lambda *a, **k: None)

    app = FastAPI()
    cloud_api.register(app)
    with TestClient(app, base_url="https://testserver") as client:
        login = client.post("/api/owner/auth/login", json={
            "email": "owner@example.com",
            "password": "correct horse battery staple",
            "nonce": "attachment-login-nonce-xxxxxxxx",
            "device": "Owner phone",
            "device_id": "browser_attachment_owner_01",
        })
        assert login.status_code == 200, login.text
        session = login.json()
        assert auth.approve_browser_device(session["device_id"])
        headers = {"X-Zeno-CSRF": session["csrf"]}

        uploaded = client.post(
            "/api/owner/attachment", headers=headers,
            data={
                "device_id": target["device_id"], "purpose": "camera",
                "prompt": "What is visible in this image?",
            },
            files={
                "upload": ("camera.jpg", b"\xff\xd8\xffcamera", "image/jpeg")},
        )
        assert uploaded.status_code == 200, uploaded.text
        queued = uploaded.json()
        assert queued["ok"] is True
        assert queued["action"] == "analyze_attachment"
        assert "camera.jpg" not in str(queued)

        claimed = client.post("/api/owner/device/claim", json={
            "device_id": target["device_id"], "token": target["token"]})
        command = claimed.json()["commands"][0]
        assert command["id"] == queued["id"]
        read = client.post("/api/owner/device/attachment/read", json={
            "device_id": target["device_id"], "token": target["token"],
            "command_id": command["id"],
            "attachment_id": queued["attachment_id"],
        })
        assert read.status_code == 200
        assert read.content == b"\xff\xd8\xffcamera"
        assert read.headers["x-zeno-attachment-name"] == "camera.jpg"
        assert read.headers["cache-control"] == "no-store"

        assert client.post("/api/owner/device/complete", json={
            "device_id": target["device_id"], "token": target["token"],
            "command_id": command["id"], "success": True,
            "result": {"answer": "A verified camera result."},
        }).json()["ok"] is True
        with pytest.raises(AttachmentNotFound):
            store.read(
                queued["attachment_id"], target_device=target["device_id"],
                command_id=command["id"])


def test_document_analysis_uses_read_only_scope_and_removes_temp_file(
        monkeypatch):
    from reyes_agent import ocr
    from reyes_agent.security.capabilities import current_profile

    observed = {}

    def extract(path, max_chars=0):
        observed["path"] = path
        return ocr.OcrResult(
            text="Quarterly revenue is 42.", ok=True, engine="direct-read",
            confidence=1.0)

    def ask(payload):
        profile = current_profile()
        observed["open_allowed"] = "open_app" in profile.allowed_tools
        observed["prompt"] = payload["text"]
        return True, {"answer": "Revenue is 42.", "tool_calls": []}

    monkeypatch.setattr(ocr, "extract_document_text", extract)
    monkeypatch.setattr(desktop_agent, "_exec_ask", ask)
    ok, result = desktop_agent._exec_attachment({
        "_attachment_bytes": b"Quarterly revenue is 42.",
        "_attachment_content_type": "text/plain",
        "_attachment_filename": "report.txt",
        "_attachment_purpose": "file",
        "prompt": "Summarize the report.",
    })
    assert ok is True and result["answer"] == "Revenue is 42."
    assert observed["open_allowed"] is False
    assert "untrusted data" in observed["prompt"]
    assert not Path(observed["path"]).exists()


class _AttachmentAgent(DesktopAgent):
    def __init__(self):
        super().__init__(AgentConfig(
            "https://gateway.example", "desktop", "secret"))
        self.posts = []
        self.reads = []

    def _post(self, path, body, timeout=30.0):
        self.posts.append((path, body))
        return {"ok": True}

    def _post_for_attachment(self, path, body, timeout=45.0):
        self.reads.append((path, body))
        return b"\xff\xd8\xffcamera", "image/jpeg", "camera.jpg", "camera"

    def _execute_with_heartbeat(self, action, operation):
        return operation()


def test_desktop_attachment_command_keeps_binary_out_of_result(monkeypatch):
    monkeypatch.setattr(
        desktop_agent, "_exec_attachment",
        lambda payload: (True, {
            "answer": "A real result.",
            "saw_bytes": bool(payload.get("_attachment_bytes")),
        }))
    agent = _AttachmentAgent()
    agent._handle({
        "id": "cmd_attachment", "action": "analyze_attachment",
        "payload": {"attachment_id": "att_owner", "prompt": "Describe it"},
    })
    assert agent.reads[0][0] == desktop_agent.ATTACHMENT_READ_PATH
    completed = [
        body for path, body in agent.posts if path.endswith("/complete")][0]
    assert completed["success"] is True
    assert completed["result"]["saw_bytes"] is True
    assert "_attachment_bytes" not in str(completed)


def test_phone_pwa_exposes_only_user_initiated_capture_and_one_mini_orb():
    page = Path("reyes_agent/static/app.html").read_text(encoding="utf-8")
    assert page.count('id="mini-orb"') == 1
    assert 'capture="environment"' in page
    assert 'callForm("/api/owner/attachment"' in page
    assert "getCurrentPosition" in page
    assert "Use my current location once" in page
    assert "ZENO does not poll or track it" in page
    assert 'localStorage.setItem("zeno_mini_pos"' in page
    assert "Android browsers cannot place a web page over other apps" in page
    assert "setInterval(requestLocation" not in page
    assert "setInterval(submitAttachment" not in page


def test_gateway_allows_companion_features_only_on_the_pwa_shell():
    from reyes_agent.anywhere_gateway import create_app

    gateway = create_app(enabled=True)
    with TestClient(gateway, base_url="https://testserver") as client:
        shell = client.get("/app")
        assert shell.status_code == 200
        permissions = shell.headers["permissions-policy"]
        assert "camera=(self)" in permissions
        assert "microphone=(self)" in permissions
        assert "geolocation=(self)" in permissions
        assert "payment=()" in permissions
        assert "img-src 'self' data: blob:" in shell.headers[
            "content-security-policy"]

        health = client.get("/health")
        assert "camera=()" in health.headers["permissions-policy"]
        assert "geolocation=()" in health.headers["permissions-policy"]
