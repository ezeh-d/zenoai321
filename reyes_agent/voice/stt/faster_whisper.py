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
            _model = WhisperModel(_configured(), device="cpu", compute_type="int8", cpu_threads=1)
    started = time.monotonic()
    suffix = ".webm"
    with tempfile.NamedTemporaryFile(prefix="zeno-stt-", suffix=suffix, delete=False) as handle:
        path = Path(handle.name)
        handle.write(audio)
    try:
        segments, info = _model.transcribe(str(path), beam_size=1, vad_filter=False,
                                           initial_prompt="ZENO, Divine, Nigerian English, Nigerian Pidgin")
        text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        return {"transcript": text, "confidence": None, "backend": "faster-whisper-int8",
                "profile": "BALANCED_LOCAL", "latency_s": round(time.monotonic() - started, 4),
                "language": getattr(info, "language", None), "partial_events": 0}
    finally:
        path.unlink(missing_ok=True)


def status() -> dict:
    return {"state": "STANDBY" if ready() else "NOT_CONFIGURED", "installed": importlib.util.find_spec("faster_whisper") is not None,
            "model": _configured(), "profile": "BALANCED_LOCAL", "loaded": _model is not None}

