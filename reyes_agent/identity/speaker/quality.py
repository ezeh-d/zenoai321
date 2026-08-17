"""Decode and validate short voice clips without retaining raw audio."""

from __future__ import annotations

import io
import math
import wave
from dataclasses import dataclass

import numpy as np


class AudioQualityError(ValueError):
    pass


@dataclass(frozen=True)
class VoiceSample:
    samples: np.ndarray
    sample_rate: int
    voiced_seconds: float
    quality: float
    snr_db: float
    clipping_ratio: float

    def diagnostics(self) -> dict[str, float]:
        return {
            "voiced_seconds": round(self.voiced_seconds, 3),
            "quality": round(self.quality, 3),
            "snr_db": round(self.snr_db, 2),
            "clipping_ratio": round(self.clipping_ratio, 5),
        }


def _decode_wav(audio: bytes) -> tuple[np.ndarray, int]:
    if not audio:
        raise AudioQualityError("No audio was supplied.")
    try:
        with wave.open(io.BytesIO(audio), "rb") as wav_file:
            channels = wav_file.getnchannels()
            width = wav_file.getsampwidth()
            rate = wav_file.getframerate()
            frames = wav_file.readframes(wav_file.getnframes())
    except (wave.Error, EOFError) as exc:
        raise AudioQualityError("Speaker verification requires PCM WAV audio.") from exc
    if rate < 8_000 or channels < 1 or width not in (1, 2, 3, 4):
        raise AudioQualityError("Unsupported WAV format for speaker verification.")
    if width == 1:
        values = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        values = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        values = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raw = np.frombuffer(frames, dtype=np.uint8)
        raw = raw[: len(raw) // 3 * 3].reshape(-1, 3)
        signed = raw[:, 0].astype(np.int32) | (raw[:, 1].astype(np.int32) << 8) | (raw[:, 2].astype(np.int32) << 16)
        signed[signed & 0x800000 != 0] -= 1 << 24
        values = signed.astype(np.float32) / 8388608.0
    if channels > 1:
        values = values[: len(values) // channels * channels].reshape(-1, channels).mean(axis=1)
    return np.ascontiguousarray(values, dtype=np.float32), rate


def _resample(samples: np.ndarray, source_rate: int, target_rate: int = 16_000) -> np.ndarray:
    if source_rate == target_rate:
        return np.ascontiguousarray(samples, dtype=np.float32)
    target_len = max(1, round(len(samples) * target_rate / source_rate))
    result = np.interp(
        np.linspace(0, len(samples) - 1, target_len),
        np.arange(len(samples)), samples,
    )
    return np.ascontiguousarray(result, dtype=np.float32)


def analyse(audio: bytes, *, minimum_voiced_seconds: float = 1.2) -> VoiceSample:
    samples, rate = _decode_wav(audio)
    samples = _resample(samples, rate)
    rate = 16_000
    if len(samples) < int(rate * minimum_voiced_seconds):
        raise AudioQualityError("The recording is too short for speaker verification.")
    centred = samples - float(np.mean(samples))
    frame_size, hop = 400, 160
    frames = np.lib.stride_tricks.sliding_window_view(centred, frame_size)[::hop]
    if not len(frames):
        raise AudioQualityError("The recording contains no analysable frames.")
    rms = np.sqrt(np.mean(frames * frames, axis=1) + 1e-12)
    noise = max(float(np.percentile(rms, 20)), 1e-5)
    voiced = rms > max(0.006, noise * 1.8)
    voiced_seconds = float(np.count_nonzero(voiced) * hop / rate)
    if voiced_seconds < minimum_voiced_seconds:
        raise AudioQualityError(
            f"Insufficient voiced audio ({voiced_seconds:.1f}s; need {minimum_voiced_seconds:.1f}s)."
        )
    speech_rms = max(float(np.median(rms[voiced])), noise)
    snr_db = 20.0 * math.log10(max(speech_rms / noise, 1.0))
    clipping = float(np.mean(np.abs(samples) >= 0.985))
    duration_score = min(1.0, voiced_seconds / 2.5)
    snr_score = max(0.0, min(1.0, (snr_db - 3.0) / 18.0))
    level_score = max(0.0, min(1.0, speech_rms / 0.045))
    clipping_score = max(0.0, 1.0 - clipping * 25.0)
    quality = duration_score * (0.45 * snr_score + 0.35 * level_score + 0.20 * clipping_score)
    return VoiceSample(samples, rate, voiced_seconds, float(quality), float(snr_db), clipping)

