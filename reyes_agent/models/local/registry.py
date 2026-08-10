from __future__ import annotations

import os
import shutil
from typing import Any

import psutil


def machine_profile() -> str:
    ram_gb = psutil.virtual_memory().total / (1024 ** 3)
    if ram_gb < 10:
        return "LIGHT"
    if ram_gb < 24:
        return "BALANCED"
    return "STRONG"


def local_status() -> dict[str, Any]:
    ollama = shutil.which("ollama")
    llama = shutil.which("llama-cli") or shutil.which("llama-server")
    enabled = os.environ.get("ZENO_LOCAL_LLM_ENABLED", "").casefold() in {"1", "true", "yes", "on"}
    return {
        "enabled": enabled, "profile": machine_profile(),
        "ollama": {"available": bool(ollama), "path": ollama},
        "llama_cpp": {"available": bool(llama), "path": llama},
        "loaded": False,
        "note": "Discovery does not load a model; provider.py activates Ollama only for a real routed turn.",
    }
