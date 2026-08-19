"""Piper offline voice: wired in, and it can never make ZENO mute."""

from __future__ import annotations

import os
import threading

import pytest

os.environ.setdefault("ZENO_ENV", "test")

from reyes_agent.voice import tts  # noqa: E402

_HAS_MODEL = tts.piper_ready()


def test_piper_is_installed():
    from importlib.util import find_spec
    assert find_spec("piper") is not None, "piper-tts should be installed"


@pytest.mark.skipif(not _HAS_MODEL, reason="no Piper model downloaded")
def test_piper_synthesises_real_audio():
    data = tts.synthesize_wav_bytes("ZENO speaks offline.")
    assert data[:4] == b"RIFF"        # a real WAV header
    assert len(data) > 5000


def test_a_missing_model_raises_rather_than_silently_failing(monkeypatch):
    """The fallback to SAPI depends on _get_piper_voice RAISING, not returning
    something broken. If it stopped raising, ZENO would go mute on a bad
    config instead of falling back."""
    monkeypatch.setattr(tts.config, "PIPER_MODEL", "definitely-not-here.onnx")
    monkeypatch.setattr(tts, "_piper_voice", None)
    with pytest.raises(tts.TTSError):
        tts._get_piper_voice()


def test_speak_falls_back_to_sapi_when_piper_model_is_missing(monkeypatch):
    monkeypatch.setattr(tts.config, "TTS_PROVIDER", "piper")
    monkeypatch.setattr(tts.config, "PIPER_MODEL", "definitely-not-here.onnx")
    monkeypatch.setattr(tts, "_piper_voice", None)
    called = {}

    def fake_fallback(text, stop_event):
        called["fallback"] = text

    import reyes_agent.voice.tts_router as router
    monkeypatch.setattr(router, "speak_fallback", fake_fallback)
    tts.speak("hello", threading.Event())
    assert called.get("fallback") == "hello"
