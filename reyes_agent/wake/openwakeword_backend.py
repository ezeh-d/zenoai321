"""Lazy openWakeWord ONNX adapter.

It consumes PCM copied from ZENO's existing WebView microphone stream.  It
never opens PyAudio/sounddevice and therefore cannot create a second Windows
microphone owner or another permission prompt.
"""

from __future__ import annotations

import importlib.util
import os
import threading
from pathlib import Path
from typing import Any

import numpy as np


class OpenWakeWordBackend:
    def __init__(self, model_path: str | Path | None = None) -> None:
        configured = model_path or os.environ.get("ZENO_WAKE_MODEL_PATH", "")
        self.model_path = Path(configured).expanduser() if configured else None
        self.threshold = max(0.05, min(0.99, float(os.environ.get("ZENO_WAKE_SENSITIVITY", "0.55"))))
        self.vad_threshold = max(0.0, min(1.0, float(os.environ.get("ZENO_WAKE_VAD_THRESHOLD", "0.35"))))
        self.noise_suppression = os.environ.get("ZENO_WAKE_NOISE_SUPPRESSION", "true").strip().lower() not in {"0", "false", "no", "off"}
        self._model: Any = None
        self._lock = threading.RLock()
        self._error = ""

    def installed(self) -> bool:
        try:
            return importlib.util.find_spec("openwakeword") is not None
        except (ImportError, ValueError):
            return False

    def configured(self) -> bool:
        return bool(self.model_path and self.model_path.is_file())

    def _load(self) -> Any:
        with self._lock:
            if self._model is not None:
                return self._model
            if not self.configured():
                self._error = "No custom ZENO openWakeWord model is configured"
                raise RuntimeError(self._error)
            if not self.installed():
                self._error = "openwakeword is not installed"
                raise RuntimeError(self._error)
            from openwakeword.model import Model

            kwargs: dict[str, Any] = {
                "wakeword_models": [str(self.model_path)],
                "inference_framework": "onnx",
                "vad_threshold": self.vad_threshold,
            }
            if self.noise_suppression:
                kwargs["enable_speex_noise_suppression"] = True
            try:
                self._model = Model(**kwargs)
            except TypeError:
                # v0.6 builds without the optional Speex extra reject that
                # keyword. Browser WebRTC suppression is still active.
                kwargs.pop("enable_speex_noise_suppression", None)
                self._model = Model(**kwargs)
            self._error = ""
            return self._model

    def reset(self) -> None:
        with self._lock:
            if self._model is not None and hasattr(self._model, "reset"):
                self._model.reset()

    def predict(self, pcm16: bytes) -> tuple[str, float]:
        try:
            model = self._load()
            samples = np.frombuffer(pcm16, dtype=np.int16)
            if not len(samples):
                return "", 0.0
            with self._lock:
                scores = model.predict(samples)
                self._error = ""
        except Exception as exc:
            with self._lock:
                self._error = f"{type(exc).__name__}: {exc}"[:300]
            raise
        if not isinstance(scores, dict) or not scores:
            return "", 0.0
        name, score = max(scores.items(), key=lambda item: float(item[1]))
        return str(name), float(score)

    def status(self) -> dict[str, Any]:
        state = "LOAD_FAILED" if self._error and self.configured() and self.installed() else (
            "READY" if self.configured() and self.installed() else (
                "DEPENDENCY_MISSING" if self.configured() else "MODEL_NOT_CONFIGURED"
            )
        )
        return {
            "backend": "openWakeWord",
            "state": state,
            "installed": self.installed(),
            "model_configured": self.configured(),
            "model_path": str(self.model_path) if self.model_path else "",
            "loaded": self._model is not None,
            "threshold": self.threshold,
            "vad_threshold": self.vad_threshold,
            "noise_suppression_requested": self.noise_suppression,
            "error": self._error,
        }
