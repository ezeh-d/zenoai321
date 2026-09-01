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


# Per-backend capability matrix. A caller (and graceful degradation) can ask
# what a backend actually supports rather than assuming parity.
_CAPABILITIES: dict[str, dict[str, bool]] = {
    "sapi": {"streaming": False, "prosody": True, "rate": True, "pitch": True,
             "volume": True, "emotion": False, "voice_selection": True,
             "cancellation": True},
    "piper": {"streaming": True, "prosody": True, "rate": True, "pitch": False,
              "volume": False, "emotion": False, "voice_selection": True,
              "cancellation": True},
    "elevenlabs": {"streaming": True, "prosody": True, "rate": True,
                   "pitch": False, "volume": False, "emotion": True,
                   "voice_selection": True, "cancellation": True},
}
_NO_CAPS = {k: False for k in
            ("streaming", "prosody", "rate", "pitch", "volume", "emotion",
             "voice_selection", "cancellation")}


def capabilities(provider: str | None = None) -> dict[str, bool]:
    """What the TTS backend can actually do -- so features degrade gracefully
    instead of crashing or pretending."""
    return dict(_CAPABILITIES.get(provider or config.TTS_PROVIDER, _NO_CAPS))


def speak(text: str, stop_event: threading.Event, *,
          delivery: dict | None = None) -> None:
    """Speak `text` on this machine, interruptibly. The text is first made
    speakable (no raw markdown/URLs/code) and spoken sentence-by-sentence so
    the first clause is heard fast; `delivery` (from conversation.delivery.
    delivery_for) applies subtle prosody where the backend supports it."""
    from reyes_agent.voice.speech_prep import prepare_for_speech

    text = prepare_for_speech(text).strip()
    if not text:
        return
    for clause in _clauses(text):
        if stop_event.is_set():
            return
        _speak_one(clause, stop_event, delivery)


def speak_stream(text_iter, stop_event: threading.Event, *,
                 delivery: dict | None = None) -> None:
    """Speak a GROWING text stream (LLM tokens) clause-by-clause: TTS starts on
    sentence 1 while later sentences are still arriving. Honors stop_event
    between and within clauses (barge-in)."""
    from reyes_agent.conversation.delivery import SentenceStreamer
    from reyes_agent.voice.speech_prep import prepare_for_speech

    streamer = SentenceStreamer()

    def say(raw: str) -> bool:
        clause = prepare_for_speech(raw).strip()
        if clause and not stop_event.is_set():
            _speak_one(clause, stop_event, delivery)
        return not stop_event.is_set()

    try:
        for delta in text_iter:
            if stop_event.is_set():
                return
            for clause in streamer.feed(str(delta or "")):
                if not say(clause):
                    return
        say(streamer.flush())
    except Exception as exc:  # noqa: BLE001
        raise TTSError(str(exc)) from exc


def _clauses(text: str) -> list[str]:
    """Split a full reply into speakable clauses (low time-to-first-audio)."""
    try:
        from reyes_agent.conversation.delivery import SentenceStreamer
        streamer = SentenceStreamer()
        out = streamer.feed(text)
        tail = streamer.flush()
        if tail:
            out.append(tail)
        return out or [text]
    except Exception:  # noqa: BLE001
        return [text]


def _speak_one(text: str, stop_event: threading.Event,
               delivery: dict | None = None) -> None:
    """One clause through the configured backend, with SAPI as the final
    fallback so a provider failure never makes ZENO mute."""
    provider = config.TTS_PROVIDER
    if provider == "sapi":
        _speak_sapi(text, stop_event, delivery)
    elif provider == "elevenlabs":
        try:
            _speak_elevenlabs(text, stop_event, delivery)
        except TTSError:
            from reyes_agent.voice.tts_router import speak_fallback
            speak_fallback(text, stop_event)
    elif provider == "piper":
        try:
            _speak_piper(text, stop_event, delivery)
        except TTSError:
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


def _speak_sapi(text: str, stop_event: threading.Event,
                delivery: dict | None = None) -> None:
    voice = _get_sapi_voice()
    prev_rate = None
    try:
        if delivery:
            # SAPI Rate is -10..10; keep the mapping SUBTLE (rate 0.9-1.1 ->
            # about -2..+2). Restored afterwards so it never drifts.
            try:
                prev_rate = voice.Rate
                voice.Rate = max(-3, min(3, int(round(
                    (float(delivery.get("rate", 1.0)) - 1.0) * 20))))
            except Exception:  # noqa: BLE001
                prev_rate = None
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
    finally:
        if prev_rate is not None:
            try:
                voice.Rate = prev_rate
            except Exception:  # noqa: BLE001
                pass


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


# --- Piper (offline neural voice) -----------------------------------------

_piper_voice = None


def _get_piper_voice():
    """Load the Piper voice once. Missing model -> TTSError -> SAPI fallback."""
    global _piper_voice
    if _piper_voice is None:
        from pathlib import Path

        model = config.PIPER_MODEL
        if not model or not Path(model).exists():
            raise TTSError(
                f"Piper model not found at {model!r}. Download one into "
                "models/piper/ or set PIPER_MODEL. Falling back to SAPI.")
        try:
            from piper import PiperVoice
        except ImportError as exc:
            raise TTSError("piper-tts isn't installed.") from exc
        try:
            cfg = model + ".json"
            _piper_voice = PiperVoice.load(
                model, config_path=cfg if Path(cfg).exists() else None)
        except Exception as exc:  # noqa: BLE001
            raise TTSError(f"couldn't load Piper voice: {exc}") from exc
    return _piper_voice


def piper_ready() -> bool:
    from pathlib import Path

    from importlib.util import find_spec
    return bool(config.PIPER_MODEL and Path(config.PIPER_MODEL).exists()
                and find_spec("piper") is not None)


def _piper_synthesize(voice, text: str, delivery: dict | None):
    """Iterate synthesis chunks, applying rate via length_scale when this Piper
    build supports it (higher rate -> shorter length_scale -> faster). Degrades
    to plain synthesis on any older/lacking API."""
    if delivery:
        try:
            rate = max(0.5, min(2.0, float(delivery.get("rate", 1.0))))
            length_scale = round(1.0 / rate, 3)
            if abs(length_scale - 1.0) > 0.01:
                from piper import SynthesisConfig
                return voice.synthesize(
                    text, syn_config=SynthesisConfig(length_scale=length_scale))
        except Exception:  # noqa: BLE001 -- unsupported here; plain synthesis
            pass
    return voice.synthesize(text)


def _speak_piper(text: str, stop_event: threading.Event,
                 delivery: dict | None = None) -> None:
    """Synthesise locally and stream to the speakers, stoppable mid-sentence."""
    import sounddevice as sd

    voice = _get_piper_voice()
    rate = getattr(voice.config, "sample_rate", 22050)
    out = sd.RawOutputStream(samplerate=rate, channels=1, dtype="int16")
    out.start()
    try:
        for chunk in _piper_synthesize(voice, text, delivery):
            if stop_event.is_set():
                break
            data = getattr(chunk, "audio_int16_bytes", None)
            if data:
                out.write(data)
    except Exception as exc:  # noqa: BLE001
        raise TTSError(str(exc)) from exc
    finally:
        out.stop()
        out.close()


def synthesize_wav_bytes(text: str) -> bytes:
    """WAV bytes from Piper, for delivering offline audio to a browser tab.

    The ElevenLabs `synthesize_bytes` needs an API key; this is the local,
    no-key equivalent, so the web panel can get real ZENO audio with nothing
    configured.
    """
    import io
    import wave

    voice = _get_piper_voice()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        voice.synthesize_wav(text, wav)
    return buf.getvalue()


def _speak_elevenlabs(text: str, stop_event: threading.Event,
                      delivery: dict | None = None) -> None:
    import sounddevice as sd

    client = _get_elevenlabs_client()
    stream_kwargs: dict = dict(
        voice_id=config.ELEVENLABS_VOICE_ID, text=text,
        model_id=config.ELEVENLABS_MODEL, output_format="pcm_24000")
    if delivery:
        try:
            # `speed` is a documented ElevenLabs voice setting; if the chosen
            # model rejects it the outer except degrades to the SAPI fallback.
            stream_kwargs["voice_settings"] = {
                "speed": max(0.7, min(1.2, float(delivery.get("rate", 1.0))))}
        except Exception:  # noqa: BLE001
            stream_kwargs.pop("voice_settings", None)
    try:
        audio_stream = client.text_to_speech.stream(**stream_kwargs)
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
