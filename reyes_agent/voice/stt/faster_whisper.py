"""Lazy CPU local fallback; never auto-downloads a model unless opted in."""

from __future__ import annotations

import importlib.util
import io
import os
import tempfile
import threading
import time
from pathlib import Path

_model = None
_lock = threading.Lock()


def _configured() -> str:
    return os.environ.get("ZENO_FASTER_WHISPER_MODEL", "").strip()


def _int_env(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(os.environ.get(name, str(default)))))
    except (TypeError, ValueError):
        return default


def _cpu_threads() -> int:
    # Was hard-pinned to 1. More threads = faster local inference (#4); kept
    # bounded so STT never starves the rest of ZENO. Override per machine.
    return _int_env("ZENO_FASTER_WHISPER_CPU_THREADS",
                    min(4, os.cpu_count() or 1), 1, 16)


def _vad_settings() -> tuple[bool, dict]:
    """Silero VAD silence-trimming for whisper. faster-whisper bundles Silero;
    turning it on skips non-speech so transcription is faster AND cleaner. The
    parameter names/defaults mirror silero-vad's get_speech_timestamps; the
    padding is a little wider than silero's 30ms so conversational word edges
    are never clipped."""
    on = os.environ.get("ZENO_STT_VAD_FILTER", "true").strip().casefold() in {
        "1", "true", "yes", "on"}
    params = {
        "threshold": _int_env("ZENO_STT_VAD_THRESHOLD_PCT", 50, 10, 90) / 100.0,
        "min_silence_duration_ms": _int_env("ZENO_STT_VAD_MIN_SILENCE_MS", 200, 50, 2000),
        "speech_pad_ms": _int_env("ZENO_STT_VAD_SPEECH_PAD_MS", 200, 0, 600),
    }
    return on, params


def ready() -> bool:
    model = _configured()
    allow_download = os.environ.get("ZENO_FASTER_WHISPER_ALLOW_DOWNLOAD", "false").casefold() in {"1", "true", "yes", "on"}
    return importlib.util.find_spec("faster_whisper") is not None and bool(model) and (Path(model).exists() or allow_download)


def transcribe(audio: bytes) -> dict:
    if not ready():
        raise RuntimeError("faster-whisper has no explicitly configured local model")
    global _model
    from faster_whisper import WhisperModel

    with _lock:
        if _model is None:
            _model = WhisperModel(_configured(), device="cpu", compute_type="int8",
                                  cpu_threads=_cpu_threads())
    started = time.monotonic()
    suffix = ".webm"
    with tempfile.NamedTemporaryFile(prefix="zeno-stt-", suffix=suffix, delete=False) as handle:
        path = Path(handle.name)
        handle.write(audio)
    vad_on, vad_params = _vad_settings()
    beam = _int_env("ZENO_FASTER_WHISPER_BEAM", 1, 1, 5)
    try:
        segments, info = _model.transcribe(
            str(path), beam_size=beam, vad_filter=vad_on,
            vad_parameters=vad_params if vad_on else None,
            initial_prompt="ZENO, Divine, Nigerian English, Nigerian Pidgin")
        text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        return {"transcript": text, "confidence": None, "backend": "faster-whisper-int8",
                "profile": "BALANCED_LOCAL", "latency_s": round(time.monotonic() - started, 4),
                "language": getattr(info, "language", None), "partial_events": 0,
                "vad_filtered": vad_on}
    finally:
        path.unlink(missing_ok=True)


def status() -> dict:
    return {"state": "STANDBY" if ready() else "NOT_CONFIGURED", "installed": importlib.util.find_spec("faster_whisper") is not None,
            "model": _configured(), "profile": "BALANCED_LOCAL", "loaded": _model is not None}

