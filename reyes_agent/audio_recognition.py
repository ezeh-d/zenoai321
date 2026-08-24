"""Bounded, modular audio recognition for ZENO.

There is no hidden audio listener here.  A recognition attempt begins only
from an explicit command or an uploaded clip, captures a short bounded sample,
and discards it after fingerprinting/provider use.  Providers implement one
small protocol so an installation can replace AudD without touching ZENO's
brain or UI.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from reyes_agent import config

_CACHE_PATH: Path = (
    Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT / ".runtime"))).expanduser()
    / "ZENO" / "Recognition" / "audio-cache.json"
)
_CACHE_LOCK = threading.RLock()
_MAX_CACHE = 200
_MAX_SAMPLE_SECONDS = 18


class AudioRecognitionError(RuntimeError):
    pass


class RecognitionProvider(Protocol):
    name: str

    def recognize(self, audio: bytes) -> dict[str, Any]: ...


def _wav(samples: np.ndarray, rate: int) -> bytes:
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1 if pcm.ndim == 1 else pcm.shape[1])
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def _decode_wav(audio: bytes) -> tuple[np.ndarray, int]:
    try:
        with wave.open(io.BytesIO(audio), "rb") as wf:
            rate, channels, width = wf.getframerate(), wf.getnchannels(), wf.getsampwidth()
            raw = wf.readframes(wf.getnframes())
    except (wave.Error, EOFError) as exc:
        raise AudioRecognitionError("Audio recognition needs a WAV/PCM clip from ZENO's recorder.") from exc
    if width != 2 or channels < 1 or rate < 8_000:
        raise AudioRecognitionError("Unsupported audio format for local fingerprinting.")
    data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        data = data[: len(data) // channels * channels].reshape(-1, channels).mean(axis=1)
    return data, rate


def _fingerprint(audio: bytes) -> str:
    """A compact perceptual cache key, not a media file or content database."""
    samples, rate = _decode_wav(audio)
    if len(samples) < rate:
        raise AudioRecognitionError("The audio sample is too short. Capture at least 4 seconds of clear audio.")
    # 24 windows across the clip, each represented by 24 coarse normalized
    # spectral bands.  Quantization makes a repeated nearby capture likely to
    # share a cache key without storing the audio itself.
    points = np.linspace(0, max(0, len(samples) - rate), 24, dtype=int)
    rows: list[np.ndarray] = []
    for start in points:
        frame = samples[start:start + rate]
        if len(frame) < rate:
            frame = np.pad(frame, (0, rate - len(frame)))
        spectrum = np.log1p(np.abs(np.fft.rfft(frame * np.hanning(len(frame)))) ** 2)
        edges = np.linspace(2, len(spectrum) - 1, 25, dtype=int)
        bands = np.array([spectrum[edges[i]:edges[i + 1]].mean() for i in range(24)])
        bands -= bands.mean()
        rows.append(bands / max(float(np.std(bands)), 1e-6))
    signature = np.clip(np.round(np.concatenate(rows) * 1.5), -8, 8).astype(np.int8).tobytes()
    return hashlib.sha256(signature).hexdigest()


def _load_cache() -> dict[str, Any]:
    try:
        return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"format": 1, "items": {}}


def _save_cache(cache: dict[str, Any]) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    items = cache.get("items", {})
    if len(items) > _MAX_CACHE:
        oldest = sorted(items, key=lambda key: items[key].get("at", 0))[:len(items) - _MAX_CACHE]
        for key in oldest:
            items.pop(key, None)
    tmp = _CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, separators=(",", ":")), encoding="utf-8")
    tmp.replace(_CACHE_PATH)


@dataclass
class AudDProvider:
    token: str
    name: str = "audd"

    def recognize(self, audio: bytes) -> dict[str, Any]:
        # Token stays server-side.  This is the provider's documented short
        # clip multipart endpoint; requests have both connection/read bounds.
        import requests

        try:
            response = requests.post(
                "https://api.audd.io/",
                data={"api_token": self.token, "return": "apple_music,spotify"},
                files={"file": ("zeno-audio.wav", audio, "audio/wav")},
                timeout=(4, _audd_timeout()),
            )
            payload = response.json()
        except requests.RequestException as exc:
            raise AudioRecognitionError(f"AudD request failed: {type(exc).__name__}") from exc
        except ValueError as exc:
            raise AudioRecognitionError("AudD returned an unreadable response.") from exc
        if response.status_code >= 400:
            raise AudioRecognitionError(f"AudD returned HTTP {response.status_code}.")
        if payload.get("status") != "success":
            raise AudioRecognitionError(str(payload.get("error") or "AudD could not process this clip."))
        result = payload.get("result")
        if not result:
            return {"matched": False, "reason": "No confident song match from AudD."}
        apple = result.get("apple_music") or {}
        artwork = ((apple.get("artwork") or {}).get("url") or "").replace("{w}", "300").replace("{h}", "300")
        return {
            "matched": True,
            "title": result.get("title") or "",
            "artist": result.get("artist") or "",
            "album": result.get("album") or "",
            "release_date": result.get("release_date") or "",
            "timecode": result.get("timecode") or "",
            "artwork_url": artwork,
            "provider_response": "matched",
        }


def providers() -> list[RecognitionProvider]:
    # Add another provider here or inject one in tests.  No token means no
    # network call and no falsely named song.
    token = os.environ.get("AUDD_API_TOKEN", "").strip()
    return [AudDProvider(token)] if token else []


def _audd_timeout() -> float:
    try:
        return max(3.0, min(30.0, float(os.environ.get("AUDD_TIMEOUT_S", "15"))))
    except ValueError:
        return 15.0


def _resolve_input_device(sd: Any) -> dict[str, Any]:
    """The input device ZENO should record from.

    Honours ``ZENO_INPUT_DEVICE`` (a device index, or a case-insensitive name
    substring) so the owner can point ZENO at a WORKING microphone without
    changing Windows' system default -- the fix when the default input is a
    muted/dead device (e.g. a USB receiver returning digital silence). Falls
    back to the system default input when unset or unmatched.
    """
    import os

    pref = os.environ.get("ZENO_INPUT_DEVICE", "").strip()
    if pref:
        try:
            if pref.lstrip("-").isdigit():
                info = sd.query_devices(int(pref))
                if int(info.get("max_input_channels", 0) or 0) > 0:
                    return info
            else:
                for dev in sd.query_devices():
                    if (int(dev.get("max_input_channels", 0) or 0) > 0
                            and pref.casefold() in str(dev.get("name", "")).casefold()):
                        return dev
        except Exception:  # noqa: BLE001 -- fall back to the default input
            pass
    return sd.query_devices(kind="input")


def capture(source: str = "microphone", seconds: int = 8) -> bytes:
    """Capture a finite mic or WASAPI loopback sample on a worker thread."""
    try:
        import sounddevice as sd
    except Exception as exc:  # noqa: BLE001
        raise AudioRecognitionError("sounddevice is not available for audio capture.") from exc
    try:
        seconds = max(4, min(_MAX_SAMPLE_SECONDS, int(seconds)))
    except (TypeError, ValueError):
        seconds = 8
    source = str(source or "microphone").lower()
    if source not in {"microphone", "system"}:
        raise AudioRecognitionError("Audio source must be 'microphone' or 'system'.")
    if source == "system":
        try:
            device = sd.query_devices(kind="output")
            settings = sd.WasapiSettings(loopback=True)
            channels = min(max(1, int(device.get("max_output_channels", 2))), 2)
            device_id: Any = device.get("name")
        except Exception as exc:  # noqa: BLE001
            raise AudioRecognitionError("Windows WASAPI loopback is unavailable on this audio device.") from exc
    else:
        try:
            device = _resolve_input_device(sd)
            settings = None
            channels = 1
            device_id = device.get("name")
        except Exception as exc:  # noqa: BLE001
            raise AudioRecognitionError("No usable microphone input device was found.") from exc
    rate = 16_000 if source == "microphone" else int(device.get("default_samplerate") or 48_000)
    blocks: list[np.ndarray] = []

    def callback(indata, _frames, _time_info, status) -> None:
        if status:
            return
        blocks.append(indata.copy())

    try:
        with sd.InputStream(device=device_id, samplerate=rate, channels=channels, dtype="float32",
                            callback=callback, extra_settings=settings):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                try:
                    from reyes_agent.worker_pool import current_task_context

                    context = current_task_context()
                    if context:
                        context.check_cancelled()
                except ImportError:
                    pass
                sd.sleep(50)
    except Exception as exc:  # noqa: BLE001
        label = "system loopback" if source == "system" else "microphone"
        raise AudioRecognitionError(f"Could not capture {label}: {type(exc).__name__}: {exc}") from exc
    if not blocks:
        raise AudioRecognitionError("The audio device returned no sample.")
    return _wav(np.concatenate(blocks, axis=0), rate)


def recognize(audio: bytes, *, source: str = "uploaded") -> dict[str, Any]:
    """Use cache first, then configured provider(s); never invent a match."""
    if len(audio) > 10 * 1024 * 1024:
        raise AudioRecognitionError("The recognition clip exceeds the 10 MiB short-clip limit.")
    fingerprint = _fingerprint(audio)
    with _CACHE_LOCK:
        cache = _load_cache()
        cached = cache.get("items", {}).get(fingerprint)
    if cached:
        result = dict(cached["result"])
        result.update({"cached": True, "source": source, "fingerprint": fingerprint[:12]})
        _emit(result)
        return result
    configured = providers()
    if not configured:
        result = {
            "matched": False, "cached": False, "source": source, "fingerprint": fingerprint[:12],
            "provider": None,
            "reason": "No music-recognition provider is configured. ZENO did not guess a song title.",
        }
        _emit(result)
        return result
    failures: list[str] = []
    for provider in configured:
        try:
            result = provider.recognize(audio)
        except AudioRecognitionError as exc:
            failures.append(str(exc))
            continue
        result.update({"provider": provider.name, "cached": False, "source": source, "fingerprint": fingerprint[:12]})
        # Cache both a confirmed result and a clean no-match for a short
        # period; avoid repeated paid calls from the same audio.
        with _CACHE_LOCK:
            cache = _load_cache()
            cache.setdefault("items", {})[fingerprint] = {"at": time.time(), "result": result}
            _save_cache(cache)
        _emit(result)
        return result
    result = {
        "matched": False, "cached": False, "source": source, "fingerprint": fingerprint[:12],
        "provider": ", ".join(provider.name for provider in configured),
        "reason": "Recognition provider failed without a match: " + "; ".join(failures),
    }
    _emit(result)
    return result


def recognize_current(source: str = "microphone", seconds: int = 8) -> dict[str, Any]:
    _lifecycle("audio.recognition_started", {"source": source})
    try:
        return recognize(capture(source, seconds), source=source)
    finally:
        _lifecycle("audio.recognition_finished", {"source": source})


def _emit(result: dict[str, Any]) -> None:
    try:
        from reyes_agent import visual_awareness

        visual_awareness.record_audio_observation(result)
    except Exception:  # noqa: BLE001 -- history is optional and bounded
        pass
    try:
        from reyes_agent import event_bus

        event_bus.publish("audio.recognized", {
            key: result.get(key) for key in (
                "matched", "title", "artist", "album", "release_date", "artwork_url", "provider", "cached", "source", "reason"
            )
        }, source="audio_recognition")
    except Exception:  # noqa: BLE001 -- a UI observer cannot affect recognition
        pass


def _lifecycle(event_type: str, payload: dict[str, Any]) -> None:
    try:
        from reyes_agent import event_bus

        event_bus.publish(event_type, payload, source="audio_recognition")
    except Exception:  # noqa: BLE001
        pass
