"""Text-to-speech seam: give it text, hear it aloud.

`TTS_PROVIDER` in .env picks the backend; both share the same call shape --
`speak(text, stop_event)` synthesizes and plays, stopping early the moment
`stop_event` is set. That's what makes REYES interruptible: the caller sets
the event the instant a new push-to-talk turn starts.

- `sapi` -- Windows' built-in voice (System.Speech / SAPI COM). Free, no
  account needed. Reliable fallback if ElevenLabs quota/credit runs out.
- `elevenlabs` -- streaming, natural voices. Was blocked on 2026-07-22
  (free-tier key got a 402 payment_required); confirmed working again on
  2026-07-31 with a real API call + a live speak() test producing actual
  audio, now the default with a specific voice (ELEVENLABS_VOICE_ID).
"""

from __future__ import annotations

import os
import threading

from reyes_agent import config


class TTSError(Exception):
    """Raised when speech can't be synthesized or played."""


def speak(text: str, stop_event: threading.Event) -> None:
    text = text.strip()
    if not text:
        return
    if config.TTS_PROVIDER == "sapi":
        _speak_sapi(text, stop_event)
    elif config.TTS_PROVIDER == "elevenlabs":
        try:
            _speak_elevenlabs(text, stop_event)
        except TTSError:
            # Provider failure must not make ZENO mute. Heavy local engines
            # remain lazy and SAPI is the final proven Windows fallback.
            from reyes_agent.voice.tts_router import speak_fallback
            speak_fallback(text, stop_event)
    else:
        raise TTSError(f"Unknown TTS_PROVIDER '{config.TTS_PROVIDER}'.")


# --- Windows SAPI ---------------------------------------------------------

_SVSFlagsAsync = 1
_SVSFPurgeBeforeSpeak = 2

_sapi_voice = None


def _get_sapi_voice():
    global _sapi_voice
    if _sapi_voice is None:
        try:
            import win32com.client
        except ImportError as exc:
            raise TTSError(
                "pywin32 isn't installed -- needed for the sapi TTS backend."
            ) from exc
        _sapi_voice = win32com.client.Dispatch("SAPI.SpVoice")
    return _sapi_voice


def _speak_sapi(text: str, stop_event: threading.Event) -> None:
    voice = _get_sapi_voice()
    try:
        voice.Speak(text, _SVSFlagsAsync)
        # WaitUntilDone(ms) returns False while still speaking -- poll it
        # instead of Status.RunningState, which can read stale immediately
        # after Speak() returns and falsely looks "done" on the first check.
        while not voice.WaitUntilDone(100):
            if stop_event.is_set():
                voice.Speak("", _SVSFlagsAsync | _SVSFPurgeBeforeSpeak)
                break
    except Exception as exc:  # noqa: BLE001
        raise TTSError(str(exc)) from exc


# --- ElevenLabs ------------------------------------------------------------

_EL_SAMPLE_RATE = 24000
_el_client = None


def _get_elevenlabs_client():
    global _el_client
    if _el_client is None:
        if not config.ELEVENLABS_API_KEY:
            raise TTSError("No ELEVENLABS_API_KEY set. Add one to .env, then restart.")
        from elevenlabs.client import ElevenLabs

        try:
            timeout_s = max(3.0, min(60.0, float(
                os.environ.get("ELEVENLABS_TIMEOUT_SECONDS", "20"))))
        except ValueError:
            timeout_s = 20.0
        _el_client = ElevenLabs(api_key=config.ELEVENLABS_API_KEY,
                               timeout=timeout_s)
    return _el_client


def synthesize_bytes(text: str) -> bytes:
    """Return MP3 bytes for `text` using ElevenLabs -- for HTTP delivery
    to a browser tab to play (`/api/tts` in web.py), as opposed to
    `speak()`'s SAPI/ElevenLabs paths which play on THIS machine's own
    speakers. Needed because the web panel might be open on a phone over
    LAN, not this PC -- audio has to travel to whichever device is
    actually looking at the panel, not play out of the server's speakers.
    Only supports ElevenLabs (the browser already has its own free local
    voice for the sapi/no-key case -- see speakInBrowser in index.html).
    """
    if not config.ELEVENLABS_API_KEY:
        raise TTSError("No ELEVENLABS_API_KEY set.")
    client = _get_elevenlabs_client()
    try:
        chunks = client.text_to_speech.convert(
            voice_id=config.ELEVENLABS_VOICE_ID,
            text=text,
            model_id=config.ELEVENLABS_MODEL,
            output_format="mp3_44100_128",
        )
        return b"".join(chunks)
    except Exception as exc:  # noqa: BLE001
        raise TTSError(str(exc)) from exc


def _speak_elevenlabs(text: str, stop_event: threading.Event) -> None:
    import sounddevice as sd

    client = _get_elevenlabs_client()
    try:
        audio_stream = client.text_to_speech.stream(
            voice_id=config.ELEVENLABS_VOICE_ID,
            text=text,
            model_id=config.ELEVENLABS_MODEL,
            output_format="pcm_24000",
        )
        out = sd.RawOutputStream(samplerate=_EL_SAMPLE_RATE, channels=1, dtype="int16")
        out.start()
        try:
            for chunk in audio_stream:
                if stop_event.is_set():
                    break
                if chunk:
                    out.write(chunk)
        finally:
            out.stop()
            out.close()
    except TTSError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise TTSError(str(exc)) from exc
