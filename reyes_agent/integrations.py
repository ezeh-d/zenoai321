"""Feature flags for the Phase 1 integrations.

Every integration is independently disableable and defaults to the backend
that is actually installed and fast on THIS machine. Nothing here silently
turns on a cloud dependency, a container runtime or a GPU model.

Kept out of `config.py` deliberately: that file is shared with the other
engineering agent, and a flags module nobody has to co-edit is one fewer
collision.
"""

from __future__ import annotations

import os
from typing import Any


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off"}


# --- 1. real-time voice --------------------------------------------------
# The existing local stack (Deepgram/browser STT + ElevenLabs + VAD +
# linguistic endpointing) is the default because mic and brain are on the
# same machine: routing audio out to a LiveKit room and back ADDS latency to
# a path measured at 1.40s. LiveKit earns its place for REMOTE voice.
LIVEKIT_ENABLED = _flag("ZENO_LIVEKIT_ENABLED", False)

# --- 2. orchestration ----------------------------------------------------
# ZENO already has agent_teams/agent_runtime/council/worker_pool doing
# sequential, parallel, handoff, cancel, timeout, health and retry. The
# registry below wraps THOSE; Microsoft Agent Framework is an alternative
# backend, not a second orchestrator running alongside.
AGENT_FRAMEWORK_ENABLED = _flag("ZENO_AGENT_FRAMEWORK_ENABLED", False)

# --- 3. computer use -----------------------------------------------------
# trycua sandboxes the agent inside a VM/container, which is the opposite of
# driving the owner's own desktop. Off unless explicitly wanted.
CUA_ENABLED = _flag("ZENO_CUA_ENABLED", False)

# --- 4. screen understanding ---------------------------------------------
# OmniParser needs torch + Florence-2 + YOLO and realistically a GPU;
# neither torch nor a GPU is present here, and CPU inference is seconds per
# frame. Windows UI Automation returns the same schema as accessibility
# ground truth in ~0.2s, so it is the default.
OMNIPARSER_ENABLED = _flag("ZENO_OMNIPARSER_ENABLED", False)

# --- 5. browser ----------------------------------------------------------
# Playwright is already installed, so the deterministic path is real today.
# browser-use is the agentic fallback for unfamiliar pages.
BROWSER_AGENT_ENABLED = _flag("ZENO_BROWSER_AGENT_ENABLED", False)


def available(module: str) -> bool:
    """Is an optional dependency actually importable right now."""
    import importlib.util

    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def status() -> dict[str, Any]:
    """What is switched on AND what is actually installed.

    A flag being true does not mean the backend exists -- this reports both
    so a misconfiguration is visible instead of failing at first use.
    """
    return {
        "livekit": {"enabled": LIVEKIT_ENABLED, "installed": available("livekit.agents"),
                    "default_backend": "local (Deepgram/browser STT + ElevenLabs)"},
        "agent_framework": {"enabled": AGENT_FRAMEWORK_ENABLED,
                            "installed": available("agent_framework"),
                            "default_backend": "ZENO agent_teams/worker_pool"},
        "cua": {"enabled": CUA_ENABLED, "installed": available("agent"),
                "default_backend": "deterministic tools + UIA agentic path"},
        "omniparser": {"enabled": OMNIPARSER_ENABLED, "installed": available("torch"),
                       "default_backend": "Windows UI Automation"},
        "browser_agent": {"enabled": BROWSER_AGENT_ENABLED, "installed": available("browser_use"),
                          "default_backend": "Playwright deterministic"},
    }
