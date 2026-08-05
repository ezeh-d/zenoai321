"""
REYES speech engine.

Speaks with a natural ElevenLabs voice when configured, and falls back to the
local offline voice (pyttsx3) automatically if ElevenLabs isn't set up, hits an
error, or runs out of free quota — so REYES is never left silent.

Config (in .env):
    TTS_ENGINE=auto                 # auto | elevenlabs | pyttsx3
    ELEVENLABS_API_KEY=sk_...       # from elevenlabs.io
    ELEVENLABS_VOICE_ID=...         # the voice you want
    ELEVENLABS_MODEL=eleven_turbo_v2_5

Public API is unchanged: speak(), speak_async(), stop_speaking(),
is_speaking(), current_engine(), list_voices(), print_voices(),
start_speech_engine(), stop_speech_engine().
"""
from __future__ import annotations

import io
import os
import queue
import threading
import time
from typing import Optional

# Load .env so keys are available even if config isn't updated.
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

try:
    from config import VOICE_RATE
except Exception:
    VOICE_RATE = 170


# =========================================================
# SETTINGS (config first, then environment)
# =========================================================

def _setting(name: str, default: str = "") -> str:
    try:
        from config import settings
        val = getattr(settings, name.lower(), None)
        if val:
            return str(val)
    except Exception:
        pass
    return os.environ.get(name, default)


ELEVEN_KEY = _setting("ELEVENLABS_API_KEY", "")
ELEVEN_VOICE = _setting("ELEVENLABS_VOICE_ID", "FVr8g66ZdLr7fVJct2Dh")
ELEVEN_MODEL = _setting("ELEVENLABS_MODEL", "eleven_turbo_v2_5")
TTS_ENGINE = (_setting("TTS_ENGINE", "auto") or "auto").lower()

DEFAULT_VOLUME = 1.0
DEFAULT_VOICE_INDEX = 0

_speech_queue: queue.Queue[Optional[str]] = queue.Queue()
_speech_thread: threading.Thread | None = None
_stop_event = threading.Event()
_is_speaking = threading.Event()
_active_engine = "pyttsx3"

# ElevenLabs runtime state
_eleven_client = None
_eleven_disabled = False          # set True after an auth/quota failure
_pygame_ready = False
_warned_playback = False


# =========================================================
# ELEVENLABS (natural voice)
# =========================================================

def _elevenlabs_available() -> bool:
    if TTS_ENGINE == "pyttsx3":
        return False
    if not ELEVEN_KEY or _eleven_disabled:
        return False
    return True


def _get_eleven_client():
    global _eleven_client
    if _eleven_client is None:
        from elevenlabs.client import ElevenLabs
        _eleven_client = ElevenLabs(api_key=ELEVEN_KEY)
    return _eleven_client


def _init_pygame() -> bool:
    global _pygame_ready
    if _pygame_ready:
        return True
    try:
        import pygame
        pygame.mixer.init()
        _pygame_ready = True
    except Exception:
        _pygame_ready = False
    return _pygame_ready


def _play_mp3(data: bytes) -> bool:
    """Play MP3 bytes. Prefers pygame; falls back to the ElevenLabs player."""
    global _warned_playback
    # 1) pygame (reliable, no ffmpeg needed)
    if _init_pygame():
        try:
            import pygame
            pygame.mixer.music.load(io.BytesIO(data))
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.03)
            return True
        except Exception:
            pass
    # 2) ElevenLabs' own player (needs ffmpeg or mpv installed)
    try:
        from elevenlabs import play
        play(data)
        return True
    except Exception:
        if not _warned_playback:
            print("[voice] For the ElevenLabs voice, install a player:  "
                  "pip install pygame   (recommended). Using local voice for now.")
            _warned_playback = True
        return False


def _elevenlabs_speak(text: str) -> bool:
    """Speak via ElevenLabs. Returns True on success, False to fall back."""
    global _eleven_disabled
    try:
        client = _get_eleven_client()
        stream = client.text_to_speech.convert(
            voice_id=ELEVEN_VOICE,
            model_id=ELEVEN_MODEL,
            text=text,
            output_format="mp3_44100_128",   # works on the free tier
        )
        data = b"".join(stream) if not isinstance(stream, (bytes, bytearray)) else bytes(stream)
        if not data:
            return False
        return _play_mp3(data)
    except Exception as error:
        msg = str(error).lower()
        if any(k in msg for k in ("401", "unauthorized", "invalid", "quota",
                                  "402", "403", "exceeded")):
            print(f"[ElevenLabs disabled — {error}] switching to local voice.")
            _eleven_disabled = True
        else:
            print(f"[ElevenLabs error — {error}] local voice for this line.")
        return False


# =========================================================
# PYTTSX3 (local fallback voice)
# =========================================================

def _create_engine():
    import pyttsx3
    engine = pyttsx3.init()
    engine.setProperty("rate", VOICE_RATE)
    engine.setProperty("volume", DEFAULT_VOLUME)
    voices = engine.getProperty("voices")
    if voices:
        idx = min(DEFAULT_VOICE_INDEX, len(voices) - 1)
        engine.setProperty("voice", voices[idx].id)
    return engine


# =========================================================
# SPEECH WORKER
# =========================================================

def _speech_worker() -> None:
    global _active_engine
    engine = None  # pyttsx3 engine, created lazily only if needed

    while not _stop_event.is_set():
        try:
            text = _speech_queue.get(timeout=0.2)
        except queue.Empty:
            continue

        if text is None:
            _speech_queue.task_done()
            break

        try:
            _is_speaking.set()
            print(f"REYES: {text}")

            spoke = False
            if _elevenlabs_available():
                spoke = _elevenlabs_speak(text)
                if spoke:
                    _active_engine = "elevenlabs"

            if not spoke:
                if engine is None:
                    engine = _create_engine()
                _active_engine = "pyttsx3"
                engine.say(text)
                engine.runAndWait()

        except Exception as error:
            print(f"[Speech Error] {error}")
            try:
                if engine:
                    engine.stop()
            except Exception:
                pass
            engine = None
        finally:
            _is_speaking.clear()
            _speech_queue.task_done()

    try:
        if engine:
            engine.stop()
    except Exception:
        pass


# =========================================================
# ENGINE CONTROL
# =========================================================

def start_speech_engine() -> None:
    global _speech_thread
    if _speech_thread and _speech_thread.is_alive():
        return
    _stop_event.clear()
    _speech_thread = threading.Thread(
        target=_speech_worker, name="REYES-Speech", daemon=True
    )
    _speech_thread.start()


def stop_speech_engine() -> None:
    global _speech_thread
    _stop_event.set()
    _speech_queue.put(None)
    if _speech_thread and _speech_thread.is_alive():
        _speech_thread.join(timeout=3)
    _speech_thread = None


# =========================================================
# SPEAKING
# =========================================================

def speak(text: object, wait: bool = True) -> None:
    if text is None:
        return
    clean_text = str(text).strip()
    if not clean_text:
        return
    start_speech_engine()
    _speech_queue.put(clean_text)
    if wait:
        _speech_queue.join()


def speak_async(text: object) -> None:
    speak(text, wait=False)


def stop_speaking() -> None:
    while True:
        try:
            _speech_queue.get_nowait()
            _speech_queue.task_done()
        except queue.Empty:
            break
    if _pygame_ready:
        try:
            import pygame
            pygame.mixer.music.stop()
        except Exception:
            pass


def is_speaking() -> bool:
    return _is_speaking.is_set()


def current_engine() -> str:
    return _active_engine


# =========================================================
# VOICE UTILITIES
# =========================================================

def list_voices() -> list[dict[str, object]]:
    import pyttsx3
    engine = pyttsx3.init()
    try:
        voices = engine.getProperty("voices")
        return [
            {"index": i, "name": v.name, "id": v.id}
            for i, v in enumerate(voices)
        ]
    finally:
        engine.stop()


def print_voices() -> None:
    voices = list_voices()
    if not voices:
        print("No voices were detected.")
        return
    for v in voices:
        print(f"{v['index']}: {v['name']} ({v['id']})")


# Start the engine when this module is imported.
start_speech_engine()