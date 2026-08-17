"""Regression coverage for bounded, noise-aware ZENO speech input."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reyes_agent import config, speech
from reyes_agent.voice import stt


def test_speech_settings_are_bounded_and_exposed_to_both_webviews() -> None:
    capabilities = speech.capabilities()
    settings = capabilities["settings"]
    assert 50 <= settings["min_speech_ms"] <= 500
    assert 400 <= settings["end_silence_ms"] <= 1500
    assert 4000 <= settings["max_utterance_ms"] <= 30000
    assert 5000 <= settings["transcribe_timeout_ms"] <= 45000

    dashboard = (ROOT / "reyes_agent" / "static" / "index.html").read_text(encoding="utf-8")
    mini = (ROOT / "reyes_agent" / "static" / "mini.html").read_text(encoding="utf-8")
    for source in (dashboard, mini):
        assert "loadSpeechSettings" in source
        assert "voiceVAD.configure(settings)" in source
        assert "TRANSCRIBE_TIMEOUT_MS" in source
        assert "controller.abort()" in source


def test_deepgram_request_has_a_real_network_timeout_and_no_retry() -> None:
    captured: dict = {}

    class Media:
        def transcribe_file(self, **kwargs):
            captured.update(kwargs)
            alternative = SimpleNamespace(transcript="heard clearly", confidence=0.91)
            return SimpleNamespace(results=SimpleNamespace(channels=[SimpleNamespace(alternatives=[alternative])]))

    fake = SimpleNamespace(listen=SimpleNamespace(v1=SimpleNamespace(media=Media())))
    original = stt._client
    stt._client = fake
    try:
        result = stt.transcribe_result(b"short processed audio")
    finally:
        stt._client = original

    assert result == {"transcript": "heard clearly", "confidence": 0.91}
    assert captured["language"] == config.DEEPGRAM_LANGUAGE
    assert set(config.DEEPGRAM_KEYTERMS).issubset(set(captured["keyterm"]))
    assert "ZENO" in captured["keyterm"]
    assert captured["request_options"] == {
        "timeout_in_seconds": max(1, config.TRANSCRIBE_TIMEOUT_SECONDS - 2),
        "max_retries": 0,
    }


def test_tiny_noise_and_timeout_always_leave_transcribing_state() -> None:
    dashboard = (ROOT / "reyes_agent" / "static" / "index.html").read_text(encoding="utf-8")
    function = dashboard.split("async function transcribeVADClip", 1)[1].split(
        "function startVADRecording", 1
    )[0]
    assert "blob.size < VAD_MIN_CLIP_BYTES" in function
    assert "ignored a short noise spike" in function
    assert "finally" in function
    assert "clearTimeout(timeout)" in function
    assert "transcriptionActive = false" in function
    assert "Transcription timed out. Listening again." in function


def _run_all() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001 - standalone project convention
            failures += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
