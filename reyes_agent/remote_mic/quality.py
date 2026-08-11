"""Low-cost, signal-derived remote microphone quality measurements."""

from __future__ import annotations

import math
import time
from array import array


class AudioQuality:
    def __init__(self) -> None:
        self.frames = 0
        self.clipped = 0
        self._last_at = 0.0
        self._jitter_ms = 0.0
        self._expected_ms = 20.0
        self._rms = 0.0
        self._noise_floor = 30.0

    def observe(self, pcm16: bytes, *, now: float | None = None) -> dict:
        now = now or time.monotonic()
        samples = array("h")
        samples.frombytes(pcm16[: len(pcm16) - len(pcm16) % 2])
        if samples:
            self._rms = math.sqrt(sum(float(v) * float(v) for v in samples) / len(samples))
            self.clipped += sum(1 for value in samples if abs(value) >= 32700)
            if self._rms < max(600.0, self._noise_floor * 2.0):
                self._noise_floor += (self._rms - self._noise_floor) * 0.04
        if self._last_at:
            interval_ms = (now - self._last_at) * 1000.0
            error = abs(interval_ms - self._expected_ms)
            self._jitter_ms += (error - self._jitter_ms) * 0.08
            self._expected_ms += (interval_ms - self._expected_ms) * 0.02
        self._last_at = now
        self.frames += 1
        sample_total = max(1, self.frames * max(1, len(samples)))
        clipping = min(1.0, self.clipped / sample_total)
        score = 100.0 - min(35.0, self._jitter_ms * 1.4) - min(40.0, clipping * 4000.0)
        snr_db = 20.0 * math.log10(max(1.0, self._rms) / max(1.0, self._noise_floor))
        if self._rms >= 100 and snr_db < 8.0:
            score -= min(18.0, (8.0 - snr_db) * 2.0)
        # Silence is valid transport and must not trigger source flapping.
        if self._rms < 30:
            score -= 4.0
        return {
            "score": round(max(0.0, min(100.0, score)), 1),
            "rms": round(self._rms, 1),
            "snr_db": round(snr_db, 2),
            "jitter_ms": round(self._jitter_ms, 2),
            "clipping_ratio": round(clipping, 6),
            "frames": self.frames,
        }
