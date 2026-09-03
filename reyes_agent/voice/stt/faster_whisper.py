"""Lazy CPU local fallback; never auto-downloads a model unless opted in."""

from __future__ import annotations

import importlib.util
import io
import os
import tempfile
import threading
import time
from pathlib import Path

# Load the local model from the on-disk HuggingFace cache and never phone home.
# The model is downloaded once; after that, every transcription otherwise fired
# an unauthenticated HEAD to huggingface.co to check for updates. On this owner's
# machine an SSL-inspecting proxy blocks huggingface (certificate verify failed /
# connection reset), so those checks failed AND -- because they hammered the
# proxy with doomed TLS handshakes -- made it reset OTHER connections too,
# including the model provider's, which read as "the AI is down". Pinning offline
# keeps the cached model working and stops the doomed network chatter entirely.
# Set before faster_whisper/ctranslate2/transformers import so they observe it.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

_model = None
_lock = threading.Lock()
# Single-flight inference gate. Local Whisper is CPU-bound; on a small machine
# a burst of audio clips (e.g. every deepgram failure falls back to here) would
# otherwise start one heavy transcription per worker and saturate every core,
# starving the interactive model turn that the owner is actually waiting on.
# Only ONE transcription runs at a time; overflow clips are dropped fast rather
# than queued, so the fallback stays available without ever taking the machine.
_infer_gate = threading.BoundedSemaphore(1)


def _configured() -> str:
    return os.environ.get("ZENO_FASTER_WHISPER_MODEL", "").strip()


def _int_env(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(os.environ.get(name, str(default)))))
    except (TypeError, ValueError):
        return default


def _cpu_threads() -> int:
    # More threads = faster local inference, but this runs on the SAME machine
    # that has to answer the owner's model turn at the same time. The old default
    # of min(4, cpu) took every core on a 4-core box, so a fallback transcription
    # pegged the CPU and the chat turn read-timed-out waiting for a core. Default
    # now leaves at least two cores free for interactive work; override per
    # machine with ZENO_FASTER_WHISPER_CPU_THREADS when the box has cores to spare.
    cpu = os.cpu_count() or 2
    return _int_env("ZENO_FASTER_WHISPER_CPU_THREADS", max(1, cpu - 2), 1, 16)


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
    # Drop this clip rather than pile a second heavy transcription onto the CPU
    # while one is already running. Non-blocking on purpose: queuing would let a
    # burst of clips run local Whisper back-to-back forever and starve the turn
    # the owner is waiting on. A dropped fallback clip is recoverable (the owner
    # speaks again); a frozen assistant is not.
    if not _infer_gate.acquire(blocking=False):
        raise RuntimeError("faster-whisper busy; clip skipped to keep ZENO responsive")
    try:
        global _model
        from faster_whisper import WhisperModel

        with _lock:
            if _model is None:
                _model = WhisperModel(_configured(), device="cpu", compute_type="int8",
                                      cpu_threads=_cpu_threads(), local_files_only=True)
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
    finally:
        _infer_gate.release()


def status() -> dict:
    return {"state": "STANDBY" if ready() else "NOT_CONFIGURED", "installed": importlib.util.find_spec("faster_whisper") is not None,
            "model": _configured(), "profile": "BALANCED_LOCAL", "loaded": _model is not None}

