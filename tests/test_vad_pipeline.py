"""Offline regressions for ZENO's processed microphone command path."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_vad_requests_browser_audio_processing_and_bounds_its_work() -> None:
    source = (ROOT / "reyes_agent" / "static" / "vad.js").read_text(encoding="utf-8")
    assert "noiseSuppression: true" in source
    assert "echoCancellation: true" in source
    assert "autoGainControl: true" in source
    assert "const POLL_MS = 50" in source
    assert "endSilenceMs: 700" in source
    assert "minSpeechMs: 120" in source
    assert "const CALIBRATION_RATE = 0.16" in source
    assert "export function recalibrate()" in source
    assert "export function mediaStream()" in source
    assert "export function pauseDetection()" in source


def test_listener_records_the_processed_stream_not_web_speech() -> None:
    source = (ROOT / "reyes_agent" / "static" / "index.html").read_text(encoding="utf-8")
    active = source.split("function chooseRecorderOptions()", 1)[1]
    active = active.split("function stopAmbientListening()", 1)[0]
    assert 'import * as voiceVAD from "/static/vad.js?v=1"' in source
    assert "voiceVAD.mediaStream()" in active
    assert "new MediaRecorder(stream" in active
    assert "let VAD_MAX_CLIP_MS = 12_000" in source
    assert "TRANSCRIBE_TIMEOUT_MS = 7_000" in source
    assert "fetch('/api/transcribe'" in active
    assert "signal: controller.signal" in active
    assert "ignored a short noise spike" in active
    assert "SpeechRecognition" not in active


def test_mini_orb_uses_the_same_processed_wake_stream() -> None:
    source = (ROOT / "reyes_agent" / "static" / "mini.html").read_text(encoding="utf-8")
    assert 'import * as voiceVAD from \'/static/vad.js?v=1\'' in source
    assert "voiceVAD.mediaStream()" in source
    assert "fetch('/api/transcribe'" in source
    assert "WakeRecognition" not in source
    assert "SpeechRecognition" not in source


def test_transcription_endpoint_is_bounded_and_does_not_run_an_agent_turn() -> None:
    source = (ROOT / "reyes_agent" / "web.py").read_text(encoding="utf-8")
    endpoint = source.split('@app.post("/api/transcribe")', 1)[1].split('@app.post("/api/voice-turn")', 1)[0]
    assert "_read_audio_upload(audio)" in endpoint
    assert 'name="voice-transcribe"' in endpoint
    assert "priority=PRIORITY_VOICE" in endpoint
    assert "timeout=config.TRANSCRIBE_TIMEOUT_SECONDS + 2" in endpoint
    assert "_conversation_turn" not in endpoint


def test_speech_capabilities_report_the_real_runtime_seams() -> None:
    from reyes_agent import speech

    capabilities = speech.capabilities()
    assert capabilities["vad"]["implemented"] is True
    assert capabilities["vad"]["engine"] == "browser-energy-adaptive"
    assert capabilities["recognition"]["engine"] == "deepgram"
    assert capabilities["noise_suppression"]["implemented"] is True
    assert capabilities["echo_cancellation"]["implemented"] is True


def _run_all() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001 - standalone test runner
            failures += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
