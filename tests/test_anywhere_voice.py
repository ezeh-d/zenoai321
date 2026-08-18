from __future__ import annotations

from pathlib import Path

import pytest

from reyes_agent.remote_access import desktop_agent
from reyes_agent.remote_access.desktop_agent import AgentConfig, DesktopAgent
from reyes_agent.remote_access.media_store import (
    MAX_INPUT_BYTES,
    MediaAccessDenied,
    MediaCapacityExceeded,
    MediaNotFound,
    MediaStore,
)


def _store(tmp_path: Path, **kwargs) -> MediaStore:
    return MediaStore(tmp_path / "media.sqlite", key=b"k" * 32, **kwargs)


def test_media_is_encrypted_bound_and_raw_input_can_be_released(tmp_path):
    store = _store(tmp_path)
    raw = b"RIFF-owner-voice-that-must-not-appear-in-sqlite"
    response = b"ID3-zeno-answer-that-must-not-appear-in-sqlite"
    media_id = store.create_input(
        browser_device="browser_owner", target_device="dev_windows",
        data=raw, content_type="audio/webm;codecs=opus")
    assert store.bind_command(media_id, command_id="cmd_voice_1",
                              target_device="dev_windows")

    clip = store.read_input(media_id, target_device="dev_windows",
                            command_id="cmd_voice_1")
    assert clip.data == raw and clip.content_type == "audio/webm"

    store.write_output(
        media_id, target_device="dev_windows", command_id="cmd_voice_1",
        data=response, content_type="audio/mpeg")
    heard = store.read_output(media_id, browser_device="browser_owner")
    assert heard.data == response and heard.content_type == "audio/mpeg"

    # SQLite and its WAL may contain identifiers, but never plaintext audio.
    on_disk = b"".join(
        path.read_bytes() for path in tmp_path.iterdir() if path.is_file())
    assert raw not in on_disk and response not in on_disk

    assert store.release_input(media_id, target_device="dev_windows",
                               command_id="cmd_voice_1")
    with pytest.raises(MediaNotFound):
        store.read_input(media_id, target_device="dev_windows",
                         command_id="cmd_voice_1")
    assert store.read_output(media_id, browser_device="browser_owner").data == response


def test_media_rejects_cross_device_cross_command_and_cross_browser_access(tmp_path):
    store = _store(tmp_path)
    media_id = store.create_input(
        browser_device="browser_a", target_device="desktop_a",
        data=b"voice", content_type="audio/ogg")
    assert store.bind_command(media_id, command_id="cmd_a", target_device="desktop_a")

    with pytest.raises(MediaAccessDenied):
        store.read_input(media_id, target_device="desktop_b", command_id="cmd_a")
    with pytest.raises(MediaAccessDenied):
        store.read_input(media_id, target_device="desktop_a", command_id="cmd_b")
    store.write_output(media_id, target_device="desktop_a", command_id="cmd_a",
                       data=b"answer", content_type="audio/mpeg")
    with pytest.raises(MediaAccessDenied):
        store.read_output(media_id, browser_device="browser_b")


def test_media_store_enforces_mime_size_expiry_and_record_cap(tmp_path):
    clock = [1000.0]
    store = _store(tmp_path, now=lambda: clock[0], max_records=1)
    with pytest.raises(ValueError, match="Unsupported"):
        store.create_input(browser_device="browser", target_device="desktop",
                           data=b"x", content_type="text/plain")
    with pytest.raises(ValueError, match="exceeds"):
        store.create_input(browser_device="browser", target_device="desktop",
                           data=b"x" * (MAX_INPUT_BYTES + 1),
                           content_type="audio/webm")

    media_id = store.create_input(browser_device="browser", target_device="desktop",
                                  data=b"one", content_type="audio/webm", ttl_s=30)
    with pytest.raises(MediaCapacityExceeded):
        store.create_input(browser_device="browser", target_device="desktop",
                           data=b"two", content_type="audio/webm")
    clock[0] += 31
    with pytest.raises(MediaNotFound):
        store.read_output(media_id, browser_device="browser")
    # Expired rows are purged before capacity is checked.
    replacement = store.create_input(
        browser_device="browser", target_device="desktop",
        data=b"replacement", content_type="audio/webm")
    assert replacement != media_id


def _voice_dependencies(monkeypatch, transcript: str, *, answer: str = "Hello"):
    from reyes_agent.voice import stt
    from reyes_agent import voice_manager

    monkeypatch.setattr(stt, "transcribe_result",
                        lambda _audio: {"transcript": transcript, "confidence": 0.91})
    calls: list[str] = []

    def ask(payload):
        calls.append(payload["text"])
        return True, {"answer": answer, "tool_calls": []}

    monkeypatch.setattr(desktop_agent, "_exec_ask", ask)
    monkeypatch.setattr(voice_manager, "synthesize", lambda text, agent="zeno": b"ID3" + text.encode())
    return calls


@pytest.mark.parametrize("transcript", [
    "open Chrome please",
    "send 500 naira to my brother",
    "disable Windows Defender",
])
def test_remote_audio_control_finance_and_security_never_reach_the_brain(
        monkeypatch, transcript):
    calls = _voice_dependencies(monkeypatch, transcript)
    ok, result = desktop_agent._exec_voice_turn({"_audio_bytes": b"audio"})
    assert ok is True  # ZENO successfully returns the refusal to the speaker.
    assert result["blocked"] is True
    assert result["policy_category"] in {"CONTROL", "FINANCIAL", "SENSITIVE"}
    assert result["speaker_verification"] == "NOT_PERFORMED"
    assert calls == []


def test_safe_remote_voice_uses_existing_stt_conversation_and_tts(monkeypatch):
    calls = _voice_dependencies(monkeypatch, "what time is it", answer="It is noon.")
    ok, result = desktop_agent._exec_voice_turn({"_audio_bytes": b"audio"})
    assert ok is True and result["blocked"] is False
    assert calls == ["what time is it"]
    assert result["answer"] == "It is noon."
    assert result["_audio_bytes"].startswith(b"ID3")
    assert result["authentication"] == "TRUSTED_OWNER_BROWSER_SESSION"
    assert result["speaker_verification"] == "NOT_PERFORMED"


def test_ambiguous_audio_cannot_escape_the_read_only_capability_scope(monkeypatch):
    from reyes_agent.voice import stt
    from reyes_agent import voice_manager
    from reyes_agent.security.capabilities import current_profile

    monkeypatch.setattr(stt, "transcribe_result", lambda _audio: {
        "transcript": "bring Chrome to the front", "confidence": 0.88})
    monkeypatch.setattr(voice_manager, "synthesize",
                        lambda text, agent="zeno": b"ID3" + text.encode())

    observed = {}

    def ask(_payload):
        profile = current_profile()
        observed["agent"] = profile.agent
        observed["open_allowed"] = "open_app" in profile.allowed_tools
        return True, {"answer": "I cannot control apps from remote audio.",
                      "tool_calls": []}

    monkeypatch.setattr(desktop_agent, "_exec_ask", ask)
    ok, result = desktop_agent._exec_voice_turn({"_audio_bytes": b"audio"})
    assert ok is True and result["speaker_verification"] == "NOT_PERFORMED"
    assert observed == {"agent": "remote_voice", "open_allowed": False}


class _RecordingAgent(DesktopAgent):
    def __init__(self):
        super().__init__(AgentConfig("https://gateway.example", "desktop", "secret"))
        self.posts = []
        self.uploads = []

    def _post(self, path, body, timeout=30.0):
        self.posts.append((path, body))
        return {"ok": True}

    def _post_for_bytes(self, path, body, timeout=30.0):
        self.posts.append((path, body))
        return b"recorded-webm", "audio/webm"

    def _post_multipart(self, path, **kwargs):
        self.uploads.append((path, kwargs))
        return {"ok": True}


def test_desktop_voice_command_moves_binary_outside_command_result(monkeypatch):
    _voice_dependencies(monkeypatch, "tell me a joke", answer="A bounded joke.")
    agent = _RecordingAgent()
    agent._handle({
        "id": "cmd_voice", "action": "voice_turn",
        "payload": {"media_id": "med_voice"},
    })

    assert agent.uploads[0][0] == desktop_agent.VOICE_MEDIA_WRITE_PATH
    assert agent.uploads[0][1]["data"].startswith(b"ID3")
    completed = [body for path, body in agent.posts if path.endswith("/complete")][0]
    assert completed["success"] is True
    assert completed["result"]["audio_id"] == "med_voice"
    assert "_audio_bytes" not in completed["result"]
    assert completed["result"]["speaker_verification"] == "NOT_PERFORMED"


def test_binary_transport_refuses_cleartext_nonlocal_gateway():
    agent = DesktopAgent(AgentConfig("http://gateway.example", "desktop", "secret"))
    with pytest.raises(ValueError, match="must use HTTPS"):
        agent._post_for_bytes("/media", {"x": 1})
