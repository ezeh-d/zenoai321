"""Auditable Human Companion V2 decisions and live subsystem evidence."""

from __future__ import annotations

import importlib.util
import os
from typing import Any


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "true" if default else "false").strip().casefold()
    return raw in {"1", "true", "yes", "on"}


FEATURE_FLAGS = {
    "ZENO_OWNER_VOICE_ENABLED": True, "ZENO_SPEECHBRAIN_ENABLED": False,
    "ZENO_3DSPEAKER_ENABLED": True, "ZENO_CLEARERVOICE_ENABLED": False,
    "ZENO_TARGET_SPEAKER_ENABLED": False, "ZENO_TEN_VAD_ENABLED": False,
    "ZENO_TEN_TURN_ENABLED": False, "ZENO_WINDOWS_AEC_ENABLED": True,
    "ZENO_RNNOISE_ENABLED": False, "ZENO_AASIST_ENABLED": False,
    "ZENO_SIMULSTREAMING_ENABLED": False, "ZENO_SENSEVOICE_ENABLED": False,
    "ZENO_COSYVOICE_ENABLED": False, "ZENO_PIPECAT_ENABLED": False,
    "ZENO_TEN_FRAMEWORK_ENABLED": False, "ZENO_SEAMLESS_ENABLED": False,
}

# An optional dependency becoming importable must never silently create a
# second realtime engine. These are explicit engineering decisions.
REPOSITORIES: tuple[dict[str, str], ...] = (
    {"repo": "speechbrain/speechbrain", "decision": "FALLBACK", "reason": "Proven ECAPA model, but PyTorch is too heavy for this 8 GB dual-core Windows realtime path."},
    {"repo": "modelscope/3D-Speaker", "decision": "PRIMARY", "reason": "CAM++ English VoxCeleb runs locally through the native sherpa-onnx Windows wheel."},
    {"repo": "modelscope/ClearerVoice-Studio", "decision": "EXPERIMENTAL", "reason": "Useful target extraction, but PyTorch cost and Windows gaps make it adaptive/off by default."},
    {"repo": "TEN-framework/ten-vad", "decision": "EXPERIMENTAL", "reason": "Windows library exists; Python 3.12/numpy 2.5 are outside its verified matrix."},
    {"repo": "TEN-framework/ten-turn-detection", "decision": "REJECTED", "reason": "Qwen2.5-7B is unsuitable for sub-1.5-second boundary decisions on this host."},
    {"repo": "xiph/rnnoise", "decision": "EXPERIMENTAL", "reason": "Strong non-stationary denoising candidate, but no audited Windows binary is deployed."},
    {"repo": "microsoft/Windows-classic-samples/AcousticEchoCancellation", "decision": "ARCHITECTURAL_REFERENCE", "reason": "Driver APO sample, not a drop-in user-mode Python API; WebRTC AEC is primary."},
    {"repo": "ufal/SimulStreaming", "decision": "REJECTED", "reason": "Recommended GPU memory and CPU latency do not fit the realtime host."},
    {"repo": "QwenAudio/SenseVoice", "decision": "EXPERIMENTAL", "reason": "Optional audio-event/multilingual signal; Nigerian language coverage is not established."},
    {"repo": "QwenAudio/CosyVoice", "decision": "EXPERIMENTAL", "reason": "Streaming TTS is attractive, but the PyTorch/Linux-oriented stack is too heavy here."},
    {"repo": "hexgrad/kokoro", "decision": "FALLBACK", "reason": "Small local TTS option, lazy until Windows dependencies/model are benchmarked."},
    {"repo": "OHF-Voice/piper1-gpl", "decision": "FALLBACK", "reason": "Light emergency TTS; GPL distribution review and a configured model are required."},
    {"repo": "pipecat-ai/pipecat", "decision": "ARCHITECTURAL_REFERENCE", "reason": "Good pipeline patterns but would duplicate ZENO's realtime owner."},
    {"repo": "TEN-framework/ten-framework", "decision": "ARCHITECTURAL_REFERENCE", "reason": "Useful orchestration concepts; not a competing runtime."},
    {"repo": "facebookresearch/seamless_communication", "decision": "REJECTED", "reason": "Large models, non-Windows wheels and model licensing make local realtime use impractical."},
    {"repo": "clovaai/aasist", "decision": "EXPERIMENTAL", "reason": "Weak anti-spoof signal only; PyTorch/domain calibration are absent and it is never auth."},
    {"repo": "k2-fsa/sherpa-onnx", "decision": "PRIMARY", "reason": "Native Windows Python 3.12 and one-thread ONNX speaker inference."},
    {"repo": "dscripka/openWakeWord", "decision": "PRIMARY", "reason": "Installed local ONNX adapter consumes shared frames; a custom ZENO model is still required."},
    {"repo": "snakers4/silero-vad", "decision": "FALLBACK", "reason": "Portable MIT ONNX VAD; load only if a real noise benchmark beats the current VAD."},
    {"repo": "SYSTRAN/faster-whisper", "decision": "FALLBACK", "reason": "Installed int8 backend; local model must be explicitly configured to avoid surprise downloads."},
)

PRIMARY_DECISIONS = {
    "speaker_verification": "3D-Speaker CAM++ English VoxCeleb via sherpa-onnx",
    "noise_suppression": "WebView2/WebRTC native suppression; adaptive spectral subtraction only when enabled",
    "target_speaker_extraction": "NOT_DEPLOYED; ClearerVoice remains experimental/adaptive",
    "vad": "WebView2 adaptive energy VAD",
    "turn_detector": "bounded English/Pidgin heuristic at stable STT boundaries",
    "stt": "Deepgram Nova-3 clip-final; faster-whisper int8 explicit local fallback",
    "realtime_framework": "local WebView2 AudioManager; existing LiveKit only for remote mode",
    "tts": "ElevenLabs configured ZENO voice with cache",
    "local_tts_fallback": "Windows SAPI; Kokoro/Piper remain lazy optional fallbacks",
    "anti_spoof": "NOT_DEPLOYED; AASIST experimental and voice never authenticates sensitive actions",
    "aec": "WebView2/WebRTC echoCancellation with applied-setting evidence",
    "multilingual": "Deepgram English plus LLM language context; no dedicated Nigerian local model is claimed",
}


def status() -> dict[str, Any]:
    from reyes_agent import speaker_identity
    from reyes_agent.audio.manager import get_audio_manager
    from reyes_agent.audio.noise.suppressor import status as noise_status
    from reyes_agent.voice.stt import status as stt_status
    from reyes_agent.voice.turn.manager import status as turn_status
    from reyes_agent.voice.language_context import status as language_status
    from reyes_agent.wake import get_wake_engine

    return {
        "state": "READY_WITH_LIMITATIONS",
        "feature_flags": {name: _flag(name, default) for name, default in FEATURE_FLAGS.items()},
        "audio_manager": get_audio_manager().status(),
        "speaker": speaker_identity.enrollment_status(), "wake": get_wake_engine().status(),
        "vad": {"primary": "browser-energy-adaptive", "ten_installed": importlib.util.find_spec("ten_vad") is not None},
        "turn": turn_status(), "stt": stt_status(), "language": language_status(), "noise": noise_status(),
        "repositories": list(REPOSITORIES), "primary_decisions": PRIMARY_DECISIONS,
        "unmeasured": [
            "Divine owner/impostor accuracy (no enrolled owner profile)",
            "target-speaker WER under TV/overlap (no consented owner/noise corpus)",
            "AASIST replay/cloned-voice discrimination (backend disabled)",
            "50 real ordinary conversation latency sample (no owner recording session)",
        ],
    }
