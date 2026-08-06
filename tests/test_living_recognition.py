"""Regression tests for Divine voice identity, audio recognition and awareness."""

from __future__ import annotations

import io
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _tone(hz: float, seconds: float = 4.5, rate: int = 16_000) -> bytes:
    timeline = np.arange(int(seconds * rate), dtype=np.float32) / rate
    # Modulation produces speech-like non-stationarity without a recording.
    signal = (0.22 * np.sin(2 * np.pi * hz * timeline) * (0.65 + 0.35 * np.sin(2 * np.pi * 2.1 * timeline)))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes((signal * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def test_speaker_profile_keeps_no_raw_audio_and_scopes_private_access() -> None:
    from reyes_agent import speaker_identity

    original = speaker_identity._PROFILE_PATH
    with tempfile.TemporaryDirectory() as temp_dir:
        speaker_identity._PROFILE_PATH = Path(temp_dir) / "divine-profile.dat"
        try:
            status = speaker_identity.enroll([_tone(180), _tone(182), _tone(179)])
            assert status["enrolled"] is True
            assert status["stored_audio"] is False
            raw = speaker_identity._PROFILE_PATH.read_bytes()
            assert b"RIFF" not in raw
            match = speaker_identity.identify(_tone(181))
            assert match["status"] in {speaker_identity.OWNER_CONFIRMED, speaker_identity.LIKELY_OWNER}
            assert match["stored_audio"] is False
            with speaker_identity.use_context({"status": speaker_identity.UNKNOWN_SPEAKER}, source="voice"):
                assert speaker_identity.privacy_denial("list_memories")
                assert speaker_identity.requires_strong_confirmation("delete_file")
            assert speaker_identity.delete_profile()["deleted"] is True
        finally:
            speaker_identity._PROFILE_PATH = original


def test_audio_recognition_never_invents_a_title_without_a_provider() -> None:
    from reyes_agent import audio_recognition

    original = audio_recognition._CACHE_PATH
    original_providers = audio_recognition.providers
    with tempfile.TemporaryDirectory() as temp_dir:
        audio_recognition._CACHE_PATH = Path(temp_dir) / "audio-cache.json"
        audio_recognition.providers = lambda: []
        try:
            result = audio_recognition.recognize(_tone(440), source="test")
            assert result["matched"] is False
            assert result["provider"] is None
            assert "did not guess" in result["reason"]
        finally:
            audio_recognition._CACHE_PATH = original
            audio_recognition.providers = original_providers


def test_awareness_defaults_private_and_buffers_are_clearable() -> None:
    from reyes_agent import visual_awareness

    original = visual_awareness._SETTINGS_PATH
    with tempfile.TemporaryDirectory() as temp_dir:
        visual_awareness._SETTINGS_PATH = Path(temp_dir) / "settings.json"
        try:
            state = visual_awareness.settings()
            assert state["visual_awareness"] is False
            assert state["rolling_buffer"] is False
            assert state["camera_active"] is False
            assert visual_awareness.clear_visual_history()["ok"] is True
            assert visual_awareness.clear_audio_history()["ok"] is True
        finally:
            visual_awareness._SETTINGS_PATH = original


def test_voice_identity_is_server_signed_before_chat_context_is_trusted() -> None:
    from reyes_agent import web

    identity, proof = web._issue_voice_identity({"status": "OWNER_CONFIRMED", "confidence": 0.95})
    assert web._validated_voice_identity(identity, proof) == identity
    assert web._validated_voice_identity({**identity, "status": "OWNER_CONFIRMED", "confidence": 1.0}, proof) is None


def test_static_voice_and_privacy_paths_are_wired() -> None:
    vad = (ROOT / "reyes_agent" / "static" / "vad.js").read_text(encoding="utf-8")
    dashboard = (ROOT / "reyes_agent" / "static" / "index.html").read_text(encoding="utf-8")
    web_source = (ROOT / "reyes_agent" / "web.py").read_text(encoding="utf-8")
    assert "export function beginPcmCapture()" in vad
    assert "export function endPcmCapture()" in vad
    assert "speaker_audio" in dashboard
    assert "voice_identity_proof" in dashboard
    assert '@app.get("/api/awareness/settings")' in web_source
    assert '@app.post("/api/visual/analyze")' in web_source


def _run_all() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
