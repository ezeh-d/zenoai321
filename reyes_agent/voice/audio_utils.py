"""Shared audio shaping for anything REYES records: gain normalization so
whispered/quiet speech reaches the STT provider at a usable level.

Honest about scope: this is gain normalization + a light noise gate, not
real spectral noise cancellation (RNNoise-style denoising). It's the part
that actually matters for "even if I whisper it hears me" -- quiet audio
getting boosted toward a target level -- without pretending to remove
background hiss that a proper denoiser would.
"""

from __future__ import annotations

import numpy as np

# How loud (as a fraction of full int16 range) normalized audio should peak
# at. Deepgram doesn't need much headroom, so this can run fairly hot.
_TARGET_PEAK = 0.7
# Cap on how much a whisper gets boosted -- an unbounded gain would also
# blow up the noise floor into audible hiss on a truly silent clip.
_MAX_GAIN = 10.0
# Below this peak level (near-silence), don't bother boosting -- there's
# nothing there but noise floor, and amplifying it just amplifies hiss.
_NOISE_FLOOR = 40


def normalize_gain(samples: np.ndarray) -> np.ndarray:
    """Boost quiet audio toward a target peak level without clipping
    already-loud audio. `samples` is int16 PCM; returns int16 PCM."""
    peak = np.abs(samples).max()
    if peak < _NOISE_FLOOR:
        return samples  # near-silence -- nothing worth amplifying
    target = _TARGET_PEAK * 32767
    gain = min(target / peak, _MAX_GAIN)
    if gain <= 1.0:
        return samples  # already loud enough -- don't reduce it
    boosted = samples.astype(np.float64) * gain
    return np.clip(boosted, -32768, 32767).astype(np.int16)
