"""Lazy, native Windows speaker-embedding backends."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import threading
import time
from pathlib import Path
from typing import Protocol

import numpy as np

from reyes_agent.identity.speaker.quality import VoiceSample

MODEL_NAME = "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"
MODEL_SHA256 = "357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b"


def default_model_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", ".")).expanduser() / "ZENO" / "Models" / "speaker"
    return Path(os.environ.get("ZENO_SPEAKER_MODEL_PATH", str(root / MODEL_NAME))).expanduser()


class EmbeddingBackend(Protocol):
    name: str

    def embed(self, sample: VoiceSample) -> tuple[np.ndarray, float]: ...
    def status(self) -> dict: ...


class SherpaOnnx3DSpeakerBackend:
    """3D-Speaker CAM++ executed by sherpa-onnx with one CPU thread."""

    name = "3D-Speaker CAM++ English VoxCeleb / sherpa-onnx"

    def __init__(self, model_path: Path | None = None) -> None:
        self.model_path = model_path or default_model_path()
        self._extractor = None
        self._lock = threading.RLock()
        self._load_ms: float | None = None
        self._last_inference_ms: float | None = None
        self._error = ""
        self._checksum_cache: tuple[int, int, bool] | None = None

    def _enabled(self) -> bool:
        raw = os.environ.get("ZENO_OWNER_VOICE_ENABLED", "true").strip().casefold()
        owner_enabled = raw not in {"0", "false", "no", "off"}
        raw = os.environ.get("ZENO_3DSPEAKER_ENABLED", "true").strip().casefold()
        model_enabled = raw not in {"0", "false", "no", "off"}
        return owner_enabled and model_enabled

    def _installed(self) -> bool:
        return importlib.util.find_spec("sherpa_onnx") is not None

    def _checksum_valid(self) -> bool:
        if not self.model_path.is_file():
            self._checksum_cache = None
            return False
        stat = self.model_path.stat()
        signature = (stat.st_size, stat.st_mtime_ns)
        cached = self._checksum_cache
        if cached is not None and cached[:2] == signature:
            return cached[2]
        digest = hashlib.sha256(self.model_path.read_bytes()).hexdigest()
        valid = digest == MODEL_SHA256
        self._checksum_cache = (signature[0], signature[1], valid)
        return valid

    def _load(self):
        with self._lock:
            if self._extractor is not None:
                return self._extractor
            if not self._enabled():
                raise RuntimeError("Owner speaker verification is disabled")
            if not self._installed():
                raise RuntimeError("sherpa-onnx is not installed")
            if not self.model_path.is_file():
                raise RuntimeError(f"Speaker model is not installed at {self.model_path}")
            if not self._checksum_valid():
                raise RuntimeError("Speaker model checksum does not match the audited release")
            import sherpa_onnx

            started = time.perf_counter()
            config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(self.model_path), num_threads=1, debug=False, provider="cpu"
            )
            if not config.validate():
                raise RuntimeError("sherpa-onnx rejected the speaker model configuration")
            self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
            self._load_ms = (time.perf_counter() - started) * 1000.0
            self._error = ""
            return self._extractor

    def embed(self, sample: VoiceSample) -> tuple[np.ndarray, float]:
        try:
            extractor = self._load()
            with self._lock:
                stream = extractor.create_stream()
                stream.accept_waveform(sample_rate=sample.sample_rate, waveform=sample.samples)
                stream.input_finished()
                if not extractor.is_ready(stream):
                    raise RuntimeError("Speaker embedding stream is not ready")
                started = time.perf_counter()
                vector = np.asarray(extractor.compute(stream), dtype=np.float32)
                elapsed = (time.perf_counter() - started) * 1000.0
                self._last_inference_ms = elapsed
            norm = float(np.linalg.norm(vector))
            if not len(vector) or not np.isfinite(norm) or norm <= 1e-9:
                raise RuntimeError("Speaker model returned an invalid embedding")
            return vector / norm, elapsed
        except Exception as exc:
            self._error = f"{type(exc).__name__}: {exc}"[:400]
            raise

    def status(self) -> dict:
        installed = self._installed()
        model_exists = self.model_path.is_file()
        enabled = self._enabled()
        checksum_valid = self._checksum_valid() if model_exists else False
        if not enabled:
            state = "DISABLED"
        elif not installed:
            state = "DEPENDENCY_MISSING"
        elif not model_exists:
            state = "MODEL_NOT_CONFIGURED"
        elif not checksum_valid:
            state = "MODEL_INVALID"
        elif self._error:
            state = "DEGRADED"
        else:
            state = "READY"
        return {
            "state": state,
            "backend": self.name,
            "installed": installed,
            "model_path": str(self.model_path),
            "model_exists": model_exists,
            "checksum_valid": checksum_valid,
            "loaded": self._extractor is not None,
            "load_ms": round(self._load_ms, 2) if self._load_ms is not None else None,
            "last_inference_ms": round(self._last_inference_ms, 2) if self._last_inference_ms is not None else None,
            "error": self._error,
        }


_backend: SherpaOnnx3DSpeakerBackend | None = None
_backend_lock = threading.Lock()


def get_backend() -> SherpaOnnx3DSpeakerBackend:
    global _backend
    if _backend is None:
        with _backend_lock:
            if _backend is None:
                _backend = SherpaOnnx3DSpeakerBackend()
    return _backend
