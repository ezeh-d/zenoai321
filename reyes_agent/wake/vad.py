"""Tiny local speech/noise gate used before neural wake scoring."""

from __future__ import annotations

import math
from array import array


class EnergyVAD:
    def __init__(self, *, open_factor: float = 2.0, minimum_rms: float = 180.0) -> None:
        self.open_factor = max(1.2, min(5.0, float(open_factor)))
        self.minimum_rms = max(20.0, float(minimum_rms))
        self.noise_floor = self.minimum_rms / self.open_factor

    def voiced(self, pcm16: bytes) -> tuple[bool, float]:
        samples = array("h")
        samples.frombytes(pcm16[: len(pcm16) - (len(pcm16) % 2)])
        if not samples:
            return False, 0.0
        rms = math.sqrt(sum(float(sample) * float(sample) for sample in samples) / len(samples))
        threshold = max(self.minimum_rms, self.noise_floor * self.open_factor)
        active = rms >= threshold
        if not active:
            rate = 0.03 if rms > self.noise_floor else 0.08
            self.noise_floor += (rms - self.noise_floor) * rate
        return active, rms
