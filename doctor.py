"""
REYES doctor — preflight check.

Run:  python doctor.py

Tells you, per feature, what's ready and what's missing, so you know exactly
what to install before launching the HUD / voice. Nothing here changes your
system; it only inspects.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

OK = "\033[92m✓\033[0m"
NO = "\033[91m✗\033[0m"
WARN = "\033[93m!\033[0m"


def have(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


def line(mark: str, label: str, note: str = "") -> None:
    tail = f"  — {note}" if note else ""
    print(f"  {mark} {label}{tail}")


def section(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m")


def check_model() -> None:
    section("Brain (a model to think with)")
    try:
        from config import settings
    except Exception as e:
        line(NO, "config.py", f"could not load settings ({e})")
        return
    keys = {
        "OpenAI": settings.openai_api_key,
        "Anthropic": settings.anthropic_api_key,
        "Gemini": settings.gemini_api_key,
    }
    any_key = any(bool(v) for v in keys.values())
    for name, val in keys.items():
        line(OK if val else WARN, f"{name} key", "set" if val else "blank (skipped)")
    # Ollama reachability
    ollama_up = False
    if have("requests"):
        try:
            import requests
            requests.get(settings.ollama_base_url, timeout=1.5)
            ollama_up = True
        except Exception:
            ollama_up = False
    line(OK if ollama_up else WARN, "Ollama (local, free)",
         "reachable" if ollama_up else f"not reachable at {settings.ollama_base_url}")
    if any_key or ollama_up:
        line(OK, "Result", "REYES has at least one way to think.")
    else:
        line(NO, "Result",
             "No model available. Add a key in .env, or install Ollama "
             "(ollama.com) and run: ollama pull llama3")


def check_terminal() -> None:
    section("Terminal mode  (python run.py)")
    line(OK if have("litellm") else NO, "litellm",
         "installed" if have("litellm") else "pip install litellm")
    line(OK if have("pydantic_settings") else NO, "pydantic-settings",
         "installed" if have("pydantic_settings") else "pip install pydantic-settings")


def check_hud() -> None:
    section("HUD mode  (python main.py)")
    line(OK if have("PySide6") else NO, "PySide6",
         "installed" if have("PySide6") else "pip install PySide6")


def check_voice() -> None:
    section("Voice  (speak & listen)")
    line(OK if have("speech_recognition") else NO, "SpeechRecognition",
         "installed" if have("speech_recognition") else "pip install SpeechRecognition")
    line(OK if have("pyaudio") else NO, "PyAudio (microphone)",
         "installed" if have("pyaudio") else "pip install pyaudio")
    tts = have("pyttsx3") or have("onnxruntime")
    line(OK if tts else NO, "Text-to-speech",
         "ready" if tts else "pip install pyttsx3  (or set up Kokoro/onnxruntime)")
    # voice model files
    try:
        from config import settings
        km = Path(settings.audio_models_dir) / settings.kokoro_model_filename
        kv = Path(settings.audio_models_dir) / settings.kokoro_voices_filename
        present = km.is_file() and kv.is_file()
        line(OK if present else WARN, "Kokoro voice models",
             "present" if present else f"missing in {settings.audio_models_dir} "
             "(needed only for Kokoro TTS)")
    except Exception:
        pass


def check_extras() -> None:
    section("Extras")
    line(OK if have("pyautogui") else WARN, "pyautogui (desktop control)",
         "installed" if have("pyautogui") else "pip install pyautogui")
    line(OK if have("mss") else WARN, "mss (screenshots)",
         "installed" if have("mss") else "pip install mss")
    line(OK if have("playwright") else WARN, "playwright (browser)",
         "installed" if have("playwright") else "pip install playwright && playwright install chromium")
    line(OK if have("pytesseract") else WARN, "pytesseract (screen OCR / vision)",
         "installed" if have("pytesseract") else "pip install pytesseract + install Tesseract")
    line(OK, "Mobile bridge (server.py)", "standard library only — always ready")
    line(OK if have("requests") else WARN, "requests (Telegram bridge)",
         "installed" if have("requests") else "pip install requests")


def main() -> None:
    print("\033[1mREYES doctor\033[0m — environment preflight")
    v = sys.version_info
    line(OK if v >= (3, 9) else NO, f"Python {v.major}.{v.minor}",
         "ok" if v >= (3, 9) else "REYES needs Python 3.9+")
    check_model()
    check_terminal()
    check_hud()
    check_voice()
    check_extras()
    print("\nTip: run.py needs Brain + Terminal ✓. The HUD adds PySide6. "
          "Voice adds the mic/TTS row. Everything else is optional per feature.\n")


if __name__ == "__main__":
    main()
