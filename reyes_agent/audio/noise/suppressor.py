"""Noise suppression that runs before VAD -- and gets out of the way.

WHERE IT SITS
-------------
    MIC -> NOISE SUPPRESSION -> VAD -> WAKE -> STT -> ZENO

Suppression belongs before VAD because a noisy room makes VAD trigger on
the room. Cleaning first means the wake word and endpointing are deciding
about speech rather than about a fan.

THE TWO RULES FROM THE BRIEF
----------------------------
"Do not overprocess clean microphones" and "avoid adding noticeable voice
latency". Both are honoured structurally rather than hoped for:

* The noise profile is estimated from the quietest frames, and if the
  estimated noise floor is already far below the speech level, suppression
  is SKIPPED and the samples are returned untouched. A clean mic gets no
  processing at all.
* Processing is a single STFT pass over the chunk with numpy. It is
  measured, and the measurement is reported in `status()`, so a regression
  in latency is visible rather than felt.

WHAT THIS IS
------------
Spectral subtraction with a noise floor and over-subtraction, which is the
classical approach and is genuinely effective on stationary noise -- fans,
hum, air conditioning, traffic. It is not RNNoise: RNNoise is a trained
recurrent model that also handles non-stationary noise like keyboard
clatter and speech babble. That is a real difference and `rnnoise_backend`
records it rather than pretending parity.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

ENABLED_FLAG = "ZENO_NOISE_SUPPRESSION_ENABLED"

FRAME = 512
HOP = 256

# How much of the estimated noise spectrum to remove. Above ~2.0 you get
# "musical noise" -- warbling artefacts that hurt STT more than the noise did.
OVERSUBTRACTION = 1.6

# Never subtract below this fraction of the original magnitude. Silence
# between words that is TOO clean also confuses endpointing.
SPECTRAL_FLOOR = 0.08

# If the noise floor is this far below the signal, the mic is already clean.
CLEAN_SNR_DB = 22.0

_last_ms = 0.0
_calls = 0
_skipped = 0


def enabled() -> bool:
    return os.environ.get(ENABLED_FLAG, "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Result:
    samples: Any
    processed: bool = False
    snr_db: float = 0.0
    reduced_db: float = 0.0
    duration_ms: float = 0.0
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"processed": self.processed, "snr_db": round(self.snr_db, 1),
                "reduced_db": round(self.reduced_db, 1),
                "duration_ms": round(self.duration_ms, 2), "reason": self.reason}


def _numpy():
    try:
        import numpy

        return numpy
    except Exception:  # noqa: BLE001
        return None


def estimate_noise_db(samples: Any) -> tuple[float, float]:
    """(noise floor dB, speech level dB) from the quietest and loudest frames."""
    numpy = _numpy()
    if numpy is None or samples is None or len(samples) < FRAME:
        return 0.0, 0.0
    audio = numpy.asarray(samples, dtype=numpy.float32)
    frames = len(audio) // HOP
    if frames < 4:
        return 0.0, 0.0
    energies = numpy.array([
        float(numpy.sqrt(numpy.mean(numpy.square(audio[i * HOP:i * HOP + FRAME]))) + 1e-9)
        for i in range(max(1, frames - 1))])
    quiet = float(numpy.percentile(energies, 10))
    loud = float(numpy.percentile(energies, 90))
    to_db = lambda v: 20.0 * numpy.log10(max(v, 1e-9))       # noqa: E731
    return to_db(quiet), to_db(loud)


def suppress(samples: Any, *, force: bool = False) -> Result:
    """Clean a chunk of mono float samples. Returns them untouched if clean."""
    global _last_ms, _calls, _skipped
    started = time.perf_counter()
    result = Result(samples=samples)

    if not (enabled() or force):
        result.reason = f"disabled; set {ENABLED_FLAG}=1 to turn it on"
        return result

    numpy = _numpy()
    if numpy is None:
        result.reason = "numpy is unavailable"
        return result

    audio = numpy.asarray(samples, dtype=numpy.float32)
    if audio.ndim != 1 or len(audio) < FRAME * 2:
        result.reason = "chunk too short to estimate a noise profile"
        return result

    noise_db, speech_db = estimate_noise_db(audio)
    result.snr_db = speech_db - noise_db
    _calls += 1

    # A clean microphone is left completely alone.
    if result.snr_db >= CLEAN_SNR_DB:
        _skipped += 1
        result.reason = (f"microphone is already clean ({result.snr_db:.0f}dB SNR) -- "
                         "left untouched rather than overprocessed")
        result.duration_ms = (time.perf_counter() - started) * 1000
        return result

    window = numpy.hanning(FRAME).astype(numpy.float32)
    count = 1 + (len(audio) - FRAME) // HOP
    spectra = numpy.stack([
        numpy.fft.rfft(audio[i * HOP:i * HOP + FRAME] * window) for i in range(count)])
    magnitude = numpy.abs(spectra)

    # The noise profile: the quietest 10% of frames per frequency bin. Speech
    # is intermittent, so the quiet floor of each bin IS the noise.
    profile = numpy.percentile(magnitude, 10, axis=0)

    cleaned_mag = numpy.maximum(magnitude - OVERSUBTRACTION * profile,
                                SPECTRAL_FLOOR * magnitude)
    cleaned = spectra * (cleaned_mag / numpy.maximum(magnitude, 1e-9))

    output = numpy.zeros(len(audio), dtype=numpy.float32)
    weights = numpy.zeros(len(audio), dtype=numpy.float32)
    for i in range(count):
        piece = numpy.fft.irfft(cleaned[i], n=FRAME).astype(numpy.float32)
        output[i * HOP:i * HOP + FRAME] += piece * window
        weights[i * HOP:i * HOP + FRAME] += window ** 2
    output /= numpy.maximum(weights, 1e-6)
    output[len(audio) - (len(audio) - (count - 1) * HOP - FRAME):] = \
        output[len(audio) - (len(audio) - (count - 1) * HOP - FRAME):]

    before = float(numpy.sqrt(numpy.mean(numpy.square(audio))) + 1e-9)
    after = float(numpy.sqrt(numpy.mean(numpy.square(output))) + 1e-9)
    result.samples = numpy.clip(output, -1.0, 1.0)
    result.processed = True
    result.reduced_db = 20.0 * float(numpy.log10(before / max(after, 1e-9)))
    result.reason = f"suppressed stationary noise at {result.snr_db:.0f}dB SNR"
    result.duration_ms = (time.perf_counter() - started) * 1000
    _last_ms = result.duration_ms
    return result


def status() -> dict[str, Any]:
    import importlib.util as finder

    return {
        "state": "ONLINE" if enabled() else "DISABLED",
        "enabled": enabled(),
        "flag": ENABLED_FLAG,
        "method": "spectral subtraction (stationary noise), numpy, single pass",
        "position": "before VAD -- so VAD decides about speech, not about the room",
        "last_ms": round(_last_ms, 2),
        "calls": _calls,
        "skipped_as_clean": _skipped,
        "clean_mic_threshold_db": CLEAN_SNR_DB,
        "rnnoise": {
            "installed": finder.find_spec("rnnoise") is not None,
            "adds": ("handles NON-stationary noise -- keyboard clatter, babble, "
                     "door slams -- which spectral subtraction cannot"),
            "role": "optional upgrade, not required for the pipeline to work"},
        "policy": "a clean microphone is detected and left completely unprocessed",
    }
