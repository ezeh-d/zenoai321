"""Selective integrations studied from github_research (silero-vad, pipecat):
neural VAD adapter + faster-whisper VAD/thread tuning. Additive and config-
gated -- EnergyVAD stays the default, and these tests never load a real model.
"""

from __future__ import annotations

from reyes_agent.wake.silero_vad import SileroVAD, make_vad


# --- neural VAD adapter (silero) ----------------------------------------
def test_silero_falls_back_gracefully_when_unavailable():
    sv = SileroVAD()
    sv._tried = True          # pretend the optional import already failed
    sv._model = None
    assert sv.available() is False
    # Must degrade to "no speech", never raise -- the mic keeps working.
    assert sv.voiced(b"\x00\x01" * 512) == (False, 0.0)


def test_silero_windows_and_scores_with_mocked_model():
    sv = SileroVAD(threshold=0.5)
    sv._model = object()               # pretend the model is loaded
    sv._infer = lambda window: 0.9     # mock inference -> high speech prob
    is_speech, peak = sv.voiced(b"\x10\x27" * 512)   # exactly one 512 window
    assert is_speech is True and abs(peak - 0.9) < 1e-6


def test_silero_buffers_partial_windows():
    sv = SileroVAD(threshold=0.5)
    sv._model = object()
    seen = []
    sv._infer = lambda window: (seen.append(len(window)) or 0.8)
    # 300 samples < one 512 window -> nothing scored yet
    assert sv.voiced(b"\x01\x00" * 300) == (False, 0.0)
    assert seen == []
    # 300 more -> 600 buffered -> exactly one 512 window is analysed
    is_speech, _peak = sv.voiced(b"\x01\x00" * 300)
    assert seen == [512] and is_speech is True


def test_silero_reset_is_safe_without_a_model():
    sv = SileroVAD()
    sv.reset()   # must not raise even though nothing is loaded
    assert sv.status()["backend"] == "silero"


# --- the factory keeps EnergyVAD the default ----------------------------
def test_make_vad_defaults_to_energy(monkeypatch):
    monkeypatch.delenv("ZENO_VAD_BACKEND", raising=False)
    from reyes_agent.wake.vad import EnergyVAD
    vad = make_vad()
    assert isinstance(vad, EnergyVAD)
    ok, level = vad.voiced(b"\x00\x10" * 100)
    assert isinstance(ok, bool) and isinstance(level, float)


def test_make_vad_silero_never_leaves_zeno_without_a_vad(monkeypatch):
    # Selecting silero must return a working VAD whether or not it is installed
    # (silero if available, else a transparent EnergyVAD fallback).
    monkeypatch.setenv("ZENO_VAD_BACKEND", "silero")
    vad = make_vad()
    ok, level = vad.voiced(b"\x00\x10" * 512)
    assert isinstance(ok, bool) and isinstance(level, float)


# --- faster-whisper VAD/thread tuning -----------------------------------
def test_stt_vad_filter_on_by_default():
    from reyes_agent.voice.stt import faster_whisper as fw
    on, params = fw._vad_settings()
    assert on is True
    assert params["min_silence_duration_ms"] == 200
    assert 0.0 < params["threshold"] <= 1.0
    assert params["speech_pad_ms"] >= 0


def test_stt_vad_filter_can_be_disabled(monkeypatch):
    from reyes_agent.voice.stt import faster_whisper as fw
    monkeypatch.setenv("ZENO_STT_VAD_FILTER", "off")
    on, _ = fw._vad_settings()
    assert on is False


def test_stt_cpu_threads_are_bounded(monkeypatch):
    from reyes_agent.voice.stt import faster_whisper as fw
    monkeypatch.setenv("ZENO_FASTER_WHISPER_CPU_THREADS", "999")
    assert fw._cpu_threads() <= 16
    monkeypatch.setenv("ZENO_FASTER_WHISPER_CPU_THREADS", "0")
    assert fw._cpu_threads() >= 1
