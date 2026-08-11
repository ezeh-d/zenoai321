"""Lazy ElevenLabs -> Kokoro -> Piper -> SAPI fallback selection."""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path


def status() -> dict:
    kokoro_installed = importlib.util.find_spec("kokoro") is not None
    kokoro_ready = kokoro_installed and os.environ.get("ZENO_KOKORO_MODEL_READY", "").casefold() in {"1", "true", "yes", "on"}
    piper_path = shutil.which("piper")
    piper_model = os.environ.get("ZENO_PIPER_MODEL", "").strip()
    piper_ready = bool(piper_path and piper_model and Path(piper_model).exists())
    return {"state": "WORKING", "order": ["elevenlabs", "kokoro", "piper", "sapi"],
            "kokoro": {"state": "STANDBY" if kokoro_ready else "NOT_CONFIGURED",
                       "installed": kokoro_installed, "ready": kokoro_ready},
            "piper": {"state": "STANDBY" if piper_ready else "NOT_CONFIGURED",
                      "installed": bool(piper_path), "model_configured": bool(piper_model),
                      "ready": piper_ready, "license_review": "GPL-3.0 distribution review required"},
            "sapi": {"state": "WORKING", "ready": True}, "lazy": True}


def speak_fallback(text: str, stop_event: threading.Event) -> str:
    state = status()
    if state["kokoro"]["ready"]:
        from kokoro import KPipeline
        import sounddevice as sd
        pipeline = KPipeline(lang_code=os.environ.get("ZENO_KOKORO_LANGUAGE", "b"))
        for _graphemes, _phonemes, audio in pipeline(text, voice=os.environ.get("ZENO_KOKORO_VOICE", "bf_emma")):
            if stop_event.is_set():
                break
            sd.play(audio, 24000, blocking=True)
        return "kokoro"
    if state["piper"]["ready"]:
        import sounddevice as sd
        import soundfile as sf
        with tempfile.TemporaryDirectory(prefix="zeno-piper-") as folder:
            output = Path(folder) / "speech.wav"
            proc = subprocess.run([shutil.which("piper"), "--model", os.environ["ZENO_PIPER_MODEL"],
                                   "--output_file", str(output)], input=text, text=True,
                                  capture_output=True, timeout=60, shell=False,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if proc.returncode != 0 or not output.exists():
                raise RuntimeError("Piper did not produce audio")
            audio, rate = sf.read(output, dtype="float32")
            if not stop_event.is_set():
                sd.play(audio, rate, blocking=True)
        return "piper"
    from reyes_agent.voice.tts import _speak_sapi
    _speak_sapi(text, stop_event)
    return "sapi"
