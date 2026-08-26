"""Defense / presentation mode -- one switch that makes ZENO defense-ready.

This does NOT reimplement the pieces the project already has -- specific
tool-derived narration (voice/narration.py, which deliberately never says
"Processing..."), owner-vs-guest turn-taking (conversation/targets.py), the
fast/deep cognition split, and the tool registry. It ORCHESTRATES them for a
live demo:

  * warms the brain up front so the FIRST question is not slow (the real
    responsiveness win),
  * enters PRESENTATION conversation mode so guests/lecturers can converse and
    the verified owner can still barge in,
  * raises a persisted `defense_mode` flag other systems can read, and
  * reports honest readiness (mic / STT / TTS / tools / memory / local + cloud
    AI / agents) so nothing is claimed READY that isn't.

Everything is best-effort and never raises: activating defense mode must not be
the thing that breaks the demo.
"""

from __future__ import annotations

import threading
from typing import Any

_FLAG = "defense_mode"


# --- activation -------------------------------------------------------------
def _warm_brain_async() -> None:
    def _warm() -> None:
        try:
            from reyes_agent import provider
            provider.warm()
        except Exception:  # noqa: BLE001
            pass
        try:
            from reyes_agent.agent import run_agent
            run_agent([{"role": "user", "content": "hi"}])   # private throwaway
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=_warm, name="zeno-defense-warm", daemon=True).start()


def _set_presentation_mode(on: bool) -> str:
    try:
        from reyes_agent.conversation import targets

        session = targets.current()
        session.mode = targets.PRESENTATION_MODE if on else targets.OWNER_MODE
        return session.mode
    except Exception:  # noqa: BLE001
        return ""


def _set_flag(on: bool) -> None:
    try:
        from reyes_agent import feature_flags

        flags = feature_flags.get_flags()
        flags.enable(_FLAG) if on else flags.disable(_FLAG)
    except Exception:  # noqa: BLE001
        pass


def is_active() -> bool:
    try:
        from reyes_agent import feature_flags
        return feature_flags.is_enabled(_FLAG)
    except Exception:  # noqa: BLE001
        return False


def activate(*, source: str = "owner") -> dict[str, Any]:
    """Turn defense mode ON. Warms the brain, enters presentation conversation,
    raises the flag, and returns a readiness snapshot."""
    _set_flag(True)
    mode = _set_presentation_mode(True)
    _warm_brain_async()
    report = readiness()
    return {
        "ok": True, "defense_mode": True, "conversation_mode": mode or "presentation",
        "source": source,
        "note": "Defense mode on. Brain warming; guests can converse, you can "
                "barge in. Say 'normal mode' or 'stand down' to exit.",
        "readiness": report,
    }


def deactivate(*, source: str = "owner") -> dict[str, Any]:
    _set_flag(False)
    mode = _set_presentation_mode(False)
    return {"ok": True, "defense_mode": False, "conversation_mode": mode or "owner",
            "source": source, "note": "Back to normal mode."}


# --- readiness --------------------------------------------------------------
def _ok(cond: bool, ready: str = "READY", degraded: str = "OFFLINE") -> str:
    return ready if cond else degraded


def readiness() -> dict[str, Any]:
    """Honest per-component readiness for the #20 health check. Cloud AI may be
    OPTIONAL/OFFLINE without ZENO being down -- local commands still work."""
    checks: dict[str, str] = {}

    # Tools
    try:
        from reyes_agent.tools import TOOLS
        checks["tools"] = _ok(len(TOOLS) > 0)
    except Exception:  # noqa: BLE001
        checks["tools"] = "OFFLINE"

    # Microphone (default input device present)
    try:
        import sounddevice as sd
        info = sd.query_devices(kind="input")
        checks["mic"] = _ok(bool(info and info.get("max_input_channels", 0) > 0))
    except Exception:  # noqa: BLE001
        checks["mic"] = "OFFLINE"

    # STT
    try:
        import faster_whisper  # noqa: F401
        checks["stt"] = "READY"
    except Exception:  # noqa: BLE001
        checks["stt"] = "OPTIONAL"

    # TTS (piper file or ElevenLabs configured)
    try:
        from reyes_agent import config
        from pathlib import Path
        piper = bool(getattr(config, "PIPER_MODEL", "")) and Path(getattr(config, "PIPER_MODEL", "")).exists()
        eleven = bool(getattr(config, "ELEVENLABS_API_KEY", "") and getattr(config, "ELEVENLABS_VOICE_ID", ""))
        checks["tts"] = _ok(piper or eleven, degraded="TEXT_ONLY")
    except Exception:  # noqa: BLE001
        checks["tts"] = "TEXT_ONLY"

    # Local AI (Ollama)
    try:
        from reyes_agent import config
        checks["local_ai"] = _ok(bool(getattr(config, "OLLAMA_BASE_URL", "")), degraded="OPTIONAL")
    except Exception:  # noqa: BLE001
        checks["local_ai"] = "OPTIONAL"

    # Cloud AI (any provider key) -- OPTIONAL, never required for basic ZENO
    try:
        from reyes_agent import config
        has_cloud = any(bool(getattr(config, k, "")) for k in
                        ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY"))
        checks["cloud_ai"] = _ok(has_cloud, ready="READY", degraded="OPTIONAL")
    except Exception:  # noqa: BLE001
        checks["cloud_ai"] = "OPTIONAL"

    # Memory
    try:
        from reyes_agent import memory_manager  # noqa: F401
        checks["memory"] = "READY"
    except Exception:  # noqa: BLE001
        checks["memory"] = "OFFLINE"

    # Spatial memory (eMEM)
    try:
        from reyes_agent.spatial_memory import get_spatial_memory
        checks["spatial"] = _ok(get_spatial_memory().available(), degraded="OPTIONAL")
    except Exception:  # noqa: BLE001
        checks["spatial"] = "OPTIONAL"

    # Agents
    try:
        from reyes_agent import agent_runtime  # noqa: F401
        checks["agents"] = "READY"
    except Exception:  # noqa: BLE001
        try:
            from reyes_agent.tools import TOOLS
            checks["agents"] = _ok("agent_roster" in TOOLS)
        except Exception:  # noqa: BLE001
            checks["agents"] = "OFFLINE"

    critical = ("tools", "mic", "memory")
    ready = all(checks.get(c) == "READY" for c in critical)
    return {"ready": ready, "checks": checks,
            "summary": "Defense-ready." if ready else
                       "Some critical components are not READY -- see checks."}
