"""Local, privacy-first speaker similarity for ZENO voice requests.

This module intentionally does *not* turn a voiceprint into an
authentication factor.  It compares short acoustic embeddings captured from
the already-authorised browser microphone against a locally enrolled owner
profile and reports evidence for conversation personalisation.  Sensitive
actions still require ZENO's desktop confirmation path.

Only compact feature vectors are retained.  Raw enrolment recordings and
command clips are discarded after their feature vector is calculated.  On
Windows the profile is encrypted with the current user's DPAPI key, so a
copied profile file cannot normally be read by a different Windows user.
"""

from __future__ import annotations

import base64
import contextlib
import contextvars
import hashlib
import io
import json
import math
import os
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from reyes_agent import config

OWNER_CONFIRMED = "OWNER_CONFIRMED"
LIKELY_OWNER = "LIKELY_OWNER"
UNKNOWN_SPEAKER = "UNKNOWN_SPEAKER"
MULTIPLE_SPEAKERS = "MULTIPLE_SPEAKERS"
INSUFFICIENT_AUDIO = "INSUFFICIENT_AUDIO"
NO_PROFILE = "NO_PROFILE"

_PROFILE_PATH: Path = (
    Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT / ".runtime"))).expanduser()
    / "ZENO" / "Biometrics" / "divine-voice-profile.dat"
)
_LOCK = threading.RLock()
_MIN_VOICED_SECONDS = 1.5
_MIN_ENROLLMENT_CLIPS = 3
_MAX_ENROLLMENT_CLIPS = 8


class SpeakerIdentityError(ValueError):
    """A profile or audio sample could not be safely processed."""


@dataclass(frozen=True)
class SpeakerContext:
    status: str = ""
    confidence: float | None = None
    source: str = "typed"

    @property
    def is_voice(self) -> bool:
        return self.source == "voice"

    @property
    def may_access_private_data(self) -> bool:
        # A voice request needs a measured owner match before private memory
        # is exposed.  Typed local UI requests retain their existing session
        # behaviour; remote callers have their own authentication boundary.
        return not self.is_voice or self.status == OWNER_CONFIRMED


_speaker_context: contextvars.ContextVar[SpeakerContext] = contextvars.ContextVar(
    "zeno_speaker_context", default=SpeakerContext()
)


def current_context() -> SpeakerContext:
    return _speaker_context.get()


@contextlib.contextmanager
def use_context(identity: dict[str, Any] | None, *, source: str = "typed") -> Iterator[None]:
    """Scope speaker evidence to the one request executing on this worker."""
    identity = identity or {}
    status = str(identity.get("status") or "")
    confidence = identity.get("confidence")
    try:
        confidence = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None
    token = _speaker_context.set(SpeakerContext(status=status, confidence=confidence, source=source))
    try:
        yield
    finally:
        _speaker_context.reset(token)


def _dpapi_protect(data: bytes) -> bytes:
    """Encrypt for this Windows user, with a deliberately safe fallback.

    The fallback is only exercised on non-Windows development/test hosts.  It
    is marked in the stored envelope and never claimed to provide Windows
    credential protection.
    """
    if os.name == "nt":
        try:
            import win32crypt

            protected = win32crypt.CryptProtectData(data, "ZENO Divine voice profile", None, None, None, 0)
            # pywin32 versions differ: older releases return
            # (description, bytes), current releases return bytes directly.
            return bytes(protected[1] if isinstance(protected, tuple) else protected)
        except Exception as exc:  # noqa: BLE001
            raise SpeakerIdentityError(f"Windows could not protect the voice profile: {exc}") from exc
    return data


def _dpapi_unprotect(data: bytes, mode: str) -> bytes:
    if mode == "dpapi":
        if os.name != "nt":
            raise SpeakerIdentityError("This voice profile is protected for a Windows user and cannot be read here.")
        try:
            import win32crypt

            clear = win32crypt.CryptUnprotectData(data, None, None, None, 0)
            return bytes(clear[1] if isinstance(clear, tuple) else clear)
        except Exception as exc:  # noqa: BLE001
            raise SpeakerIdentityError("This Windows user cannot unlock the Divine voice profile.") from exc
    return data


def _write_profile(profile: dict[str, Any]) -> None:
    raw = json.dumps(profile, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    protected = _dpapi_protect(raw)
    mode = "dpapi" if os.name == "nt" else "plain-development"
    envelope = {
        "format": 1,
        "protection": mode,
        "payload": base64.b64encode(protected).decode("ascii"),
    }
    _PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PROFILE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(envelope), encoding="utf-8")
    tmp.replace(_PROFILE_PATH)


def _read_profile() -> dict[str, Any] | None:
    try:
        envelope = json.loads(_PROFILE_PATH.read_text(encoding="utf-8"))
        protected = base64.b64decode(envelope["payload"])
        raw = _dpapi_unprotect(protected, str(envelope.get("protection", "")))
        profile = json.loads(raw.decode("utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SpeakerIdentityError(f"The Divine voice profile cannot be read safely: {exc}") from exc
    if profile.get("format") != 1 or not isinstance(profile.get("centroid"), list):
        raise SpeakerIdentityError("The Divine voice profile has an unsupported format.")
    return profile


def _decode_wav(audio: bytes) -> tuple[np.ndarray, int]:
    if not audio:
        raise SpeakerIdentityError("No audio was supplied.")
    try:
        with wave.open(io.BytesIO(audio), "rb") as wf:
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
    except (wave.Error, EOFError) as exc:
        raise SpeakerIdentityError("Speaker enrolment requires browser-captured PCM WAV audio.") from exc
    if rate < 8_000 or channels < 1 or sample_width not in (1, 2, 3, 4):
        raise SpeakerIdentityError("Unsupported WAV format for speaker recognition.")
    if sample_width == 1:
        values = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sample_width == 2:
        values = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif sample_width == 4:
        values = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    else:  # 24-bit signed PCM
        raw = np.frombuffer(frames, dtype=np.uint8).reshape(-1, 3)
        signed = raw[:, 0].astype(np.int32) | (raw[:, 1].astype(np.int32) << 8) | (raw[:, 2].astype(np.int32) << 16)
        signed[signed & 0x800000 != 0] -= 1 << 24
        values = signed.astype(np.float32) / 8388608.0
    if channels > 1:
        values = values[: len(values) // channels * channels].reshape(-1, channels).mean(axis=1)
    return values, rate


def _resample(samples: np.ndarray, source_rate: int, target_rate: int = 16_000) -> np.ndarray:
    if source_rate == target_rate:
        return samples
    target_len = max(1, round(len(samples) * target_rate / source_rate))
    return np.interp(np.linspace(0, len(samples) - 1, target_len), np.arange(len(samples)), samples).astype(np.float32)


def _frame_features(samples: np.ndarray, rate: int) -> tuple[np.ndarray, float, float]:
    """Return local acoustic features, voiced seconds, and speech quality.

    This is intentionally small and dependency-free: log spectral bands,
    spectral shape and zero-crossing rate.  It is language-independent, so
    Nigerian English/Pidgin affects STT but not this acoustic comparison.
    It is a *similarity* signal, not a forensic speaker-verification model.
    """
    samples = _resample(samples, rate)
    rate = 16_000
    if len(samples) < rate:
        return np.empty((0, 0), dtype=np.float32), 0.0, 0.0
    samples = samples - float(np.mean(samples))
    frame_size, hop = 400, 160
    frames = np.lib.stride_tricks.sliding_window_view(samples, frame_size)[::hop]
    if len(frames) == 0:
        return np.empty((0, 0), dtype=np.float32), 0.0, 0.0
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    noise_floor = float(np.percentile(rms, 25))
    voiced = rms > max(0.008, noise_floor * 1.8)
    voiced_frames = frames[voiced]
    if not len(voiced_frames):
        return np.empty((0, 0), dtype=np.float32), 0.0, 0.0
    windowed = voiced_frames * np.hanning(frame_size)
    spectrum = np.abs(np.fft.rfft(windowed, axis=1)) + 1e-8
    power = spectrum * spectrum
    freq = np.linspace(0.0, rate / 2, power.shape[1])
    # 20 compact spectral bands; the lowest DC bin is excluded.
    edges = np.linspace(2, power.shape[1] - 1, 21, dtype=int)
    bands = np.stack([np.log(power[:, edges[i]:edges[i + 1]].mean(axis=1) + 1e-8) for i in range(20)], axis=1)
    norm_bands = bands - bands.mean(axis=1, keepdims=True)
    centroid = (power * freq).sum(axis=1) / power.sum(axis=1)
    cumulative = np.cumsum(power, axis=1)
    rolloff = freq[np.argmax(cumulative >= (power.sum(axis=1)[:, None] * 0.85), axis=1)]
    zcr = np.mean(np.diff(np.signbit(voiced_frames), axis=1), axis=1)
    shape = np.stack([centroid / 8_000.0, rolloff / 8_000.0, zcr], axis=1)
    features = np.concatenate([norm_bands, shape], axis=1).astype(np.float32)
    voiced_seconds = len(voiced_frames) * hop / rate
    # Two seconds of actual speech is enough for this compact local signal;
    # more silence in the captured clip must not artificially demote an
    # otherwise clear utterance below its own enrolled profile.
    quality = min(1.0, voiced_seconds / 2.0) * min(1.0, max(0.0, float(np.median(rms)) / 0.04))
    return features, float(voiced_seconds), float(quality)


def _embedding(audio: bytes) -> tuple[np.ndarray, dict[str, float]]:
    samples, rate = _decode_wav(audio)
    features, voiced_seconds, quality = _frame_features(samples, rate)
    if voiced_seconds < _MIN_VOICED_SECONDS or not len(features):
        raise SpeakerIdentityError(f"Insufficient voiced audio ({voiced_seconds:.1f}s; need {_MIN_VOICED_SECONDS:.1f}s).")
    # Mean and spread distinguish a stable voice better than one raw moment.
    vector = np.concatenate([features.mean(axis=0), features.std(axis=0)])
    vector /= max(float(np.linalg.norm(vector)), 1e-9)
    return vector.astype(np.float32), {"voiced_seconds": round(voiced_seconds, 2), "quality": round(quality, 3)}


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    denom = max(float(np.linalg.norm(left) * np.linalg.norm(right)), 1e-9)
    return float(np.clip(np.dot(left, right) / denom, -1.0, 1.0))


def _multiple_speakers(features: np.ndarray) -> bool:
    """Conservative two-cluster signal; it prefers "unknown" to a claim."""
    if len(features) < 120:  # about 1.2 s of voiced frames
        return False
    half = len(features) // 2
    first, second = features[:half].mean(axis=0), features[half:].mean(axis=0)
    first /= max(float(np.linalg.norm(first)), 1e-9)
    second /= max(float(np.linalg.norm(second)), 1e-9)
    # Different stable acoustic shapes across two long segments is evidence;
    # a short transition, noise burst or single excited voice is not enough.
    return _cosine(first, second) < 0.74


def enrollment_status() -> dict[str, Any]:
    with _LOCK:
        try:
            profile = _read_profile()
        except SpeakerIdentityError as exc:
            return {"enrolled": False, "error": str(exc)}
    if not profile:
        return {
            "enrolled": False,
            "required_clips": _MIN_ENROLLMENT_CLIPS,
            "stored_audio": False,
            "security_note": "No voice profile exists yet.",
        }
    return {
        "enrolled": True,
        "enrolled_at": profile.get("enrolled_at"),
        "clips": int(profile.get("clips", 0)),
        "stored_audio": False,
        "protection": "Windows DPAPI (current Windows user)",
        "model": "local acoustic speaker similarity",
        "limitation": "Helpful personalisation evidence, not authentication and not spoof-resistant.",
    }


def enroll(clips: list[bytes]) -> dict[str, Any]:
    """Replace Divine's local profile after validating several fresh clips."""
    if not _MIN_ENROLLMENT_CLIPS <= len(clips) <= _MAX_ENROLLMENT_CLIPS:
        raise SpeakerIdentityError(f"Provide {_MIN_ENROLLMENT_CLIPS}-{_MAX_ENROLLMENT_CLIPS} separate recordings.")
    vectors: list[np.ndarray] = []
    qualities: list[dict[str, float]] = []
    for index, clip in enumerate(clips, 1):
        try:
            vector, quality = _embedding(clip)
        except SpeakerIdentityError as exc:
            raise SpeakerIdentityError(f"Recording {index}: {exc}") from exc
        vectors.append(vector)
        qualities.append(quality)
    similarities = [_cosine(a, b) for pos, a in enumerate(vectors) for b in vectors[pos + 1:]]
    mean_similarity = float(np.mean(similarities)) if similarities else 0.0
    if mean_similarity < 0.73:
        raise SpeakerIdentityError(
            "The enrolment recordings do not sound consistently like one speaker. Use a quieter room and record only Divine."
        )
    centroid = np.mean(np.stack(vectors), axis=0)
    centroid /= max(float(np.linalg.norm(centroid)), 1e-9)
    profile = {
        "format": 1,
        "created_at": time.time(),
        "enrolled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "clips": len(vectors),
        "centroid": [round(float(value), 8) for value in centroid],
        "self_similarity": round(mean_similarity, 4),
        "quality": qualities,
        "raw_audio_stored": False,
        "algorithm": "local spectral acoustic similarity v1",
    }
    with _LOCK:
        _write_profile(profile)
    _emit("speaker.profile_enrolled", {"clips": len(vectors), "stored_audio": False})
    return {"ok": True, **enrollment_status()}


def delete_profile() -> dict[str, Any]:
    with _LOCK:
        existed = _PROFILE_PATH.exists()
        if existed:
            _PROFILE_PATH.unlink()
    _emit("speaker.profile_deleted", {"existed": existed})
    return {"ok": True, "deleted": existed, "stored_audio": False}


def identify(audio: bytes) -> dict[str, Any]:
    """Compare a bounded command clip without retaining it."""
    base = {"source": "local", "stored_audio": False, "model": "local acoustic speaker similarity"}
    with _LOCK:
        try:
            profile = _read_profile()
        except SpeakerIdentityError as exc:
            return {**base, "status": NO_PROFILE, "confidence": None, "reason": str(exc)}
    if not profile:
        return {**base, "status": NO_PROFILE, "confidence": None, "reason": "Divine has not enrolled a voice profile."}
    try:
        vector, quality = _embedding(audio)
    except SpeakerIdentityError as exc:
        return {**base, "status": INSUFFICIENT_AUDIO, "confidence": None, "reason": str(exc)}
    samples, rate = _decode_wav(audio)
    features, _seconds, _quality = _frame_features(samples, rate)
    if _multiple_speakers(features):
        result = {**base, "status": MULTIPLE_SPEAKERS, "confidence": None, "quality": quality,
                  "reason": "Two sustained acoustic clusters were detected; no identity decision was made."}
        _record(result)
        return result
    centroid = np.array(profile["centroid"], dtype=np.float32)
    similarity = _cosine(vector, centroid)
    # Similarity is evidence, not a calibrated probability.  Keeping this
    # mapping deliberately conservative reduces accidental "owner" labels.
    confidence = round(max(0.0, min(1.0, (similarity - 0.55) / 0.40)) * quality["quality"], 3)
    if confidence >= 0.88:
        status = OWNER_CONFIRMED
    elif confidence >= 0.67:
        status = LIKELY_OWNER
    else:
        status = UNKNOWN_SPEAKER
    result = {
        **base, "status": status, "confidence": confidence, "similarity": round(similarity, 3),
        "quality": quality,
        "reason": "Measured acoustic similarity; it is separate from speech-to-text confidence and is not authentication.",
    }
    _record(result)
    return result


def _record(result: dict[str, Any]) -> None:
    try:
        from reyes_agent.confidence import record

        record("speaker", result.get("confidence"), f"{result.get('status')}: local acoustic comparison")
    except Exception:  # noqa: BLE001 -- diagnostics cannot affect voice input
        pass
    _emit("speaker.identity", {key: result.get(key) for key in ("status", "confidence", "quality", "reason")})


def _emit(event_type: str, payload: dict[str, Any]) -> None:
    try:
        from reyes_agent import event_bus

        event_bus.publish(event_type, payload, source="speaker_identity")
    except Exception:  # noqa: BLE001 -- recording identity never depends on UI observers
        pass


def privacy_denial(tool_name: str) -> str | None:
    """Return an owner-protection message for private retrieval tools."""
    private_tools = {
        "list_memories", "search_memories", "memory_versions", "compare_memory_versions",
        "search_notes", "list_notes", "search_vault_semantic", "read_file", "check_email", "read_email",
    }
    context = current_context()
    if context.is_voice and tool_name in private_tools and not context.may_access_private_data:
        return (
            "Private ZENO data is protected because this voice was not confirmed as Divine. "
            "Use the local dashboard with a stronger sign-in/confirmation method."
        )
    return None


def requires_strong_confirmation(tool_name: str) -> bool:
    """Voice evidence never auto-approves consequential operations."""
    context = current_context()
    if not context.is_voice:
        return False
    try:
        from reyes_agent.confidence import risk_for_tool

        return risk_for_tool(tool_name) in {"high", "critical"}
    except Exception:  # noqa: BLE001
        return False


def profile_fingerprint() -> str:
    """Diagnostics-only non-reversible profile reference; never return vectors."""
    with _LOCK:
        profile = _read_profile()
    if not profile:
        return ""
    return hashlib.sha256(json.dumps(profile["centroid"]).encode()).hexdigest()[:12]
