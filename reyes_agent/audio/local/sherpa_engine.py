"""Lazy Sherpa capability probe. It accepts frames from the microphone owner."""
from __future__ import annotations

import importlib.util
import os


def status() -> dict:
    installed = importlib.util.find_spec("sherpa_onnx") is not None
    enabled = os.environ.get("ZENO_SHERPA_ENABLED", "").casefold() in {"1", "true", "yes", "on"}
    return {"state": "STANDBY" if enabled and installed else ("DEGRADED" if enabled else "DISABLED"),
            "enabled": enabled, "installed": installed, "loaded": False,
            "opens_microphone": False, "authentication": "speaker similarity is never sufficient for sensitive actions"}
