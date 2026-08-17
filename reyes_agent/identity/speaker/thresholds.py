"""Conservative speaker-verification decision bands.

Cosine similarity is model evidence, not a probability.  These defaults are
intentionally stricter than sherpa-onnx's identification example because ZENO
uses the result to decide whether private conversational context may be read.
They remain configurable so a real owner/impostor calibration set can tune
them without changing code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bounded(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


@dataclass(frozen=True)
class SpeakerThresholds:
    high: float = _bounded("ZENO_SPEAKER_HIGH_THRESHOLD", 0.82, 0.60, 0.99)
    likely: float = _bounded("ZENO_SPEAKER_LIKELY_THRESHOLD", 0.68, 0.45, 0.95)
    uncertain: float = _bounded("ZENO_SPEAKER_UNCERTAIN_THRESHOLD", 0.52, 0.20, 0.90)
    minimum_quality: float = _bounded("ZENO_SPEAKER_MIN_QUALITY", 0.48, 0.10, 0.95)

    def validate(self) -> None:
        if not self.high > self.likely > self.uncertain:
            raise ValueError("Speaker thresholds must satisfy high > likely > uncertain")


DEFAULT_THRESHOLDS = SpeakerThresholds()
DEFAULT_THRESHOLDS.validate()

