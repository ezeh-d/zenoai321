"""Cloud-first/local-fallback STT availability without duplicate model loads.

Named separately from ``reyes_agent.voice.stt`` because that existing module
is ZENO's live transcription authority and must never be shadowed by a package.
"""
from __future__ import annotations

import os
import shutil
from typing import Any

from reyes_agent import config


def status() -> dict[str, Any]:
    whisper = shutil.which(os.environ.get("ZENO_WHISPER_CPP_COMMAND", "whisper-cli"))
    local_enabled = os.environ.get("ZENO_WHISPER_CPP_ENABLED", "").casefold() in {"1", "true", "yes", "on"}
    return {"primary": "deepgram" if config.DEEPGRAM_API_KEY else "faster-whisper",
            "cloud_available": bool(config.DEEPGRAM_API_KEY),
            "whisper_cpp": {"enabled": local_enabled, "available": bool(whisper), "path": whisper, "loaded": False},
            "single_audio_owner": "reyes_agent.microphone", "simultaneous_large_models": False}
