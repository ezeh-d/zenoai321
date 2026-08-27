"""Optional neural VAD (Silero) with the SAME interface as EnergyVAD.

Studied from github_research/silero-vad and pipecat's VAD analyzer, integrated
selectively -- no repo copied, no model bundled. EnergyVAD (wake/vad.py) stays
ZENO's default; this is an ADDITIVE option that callers opt into via
``ZENO_VAD_BACKEND=silero``.

WHY IT MATTERS
--------------
EnergyVAD gates on raw loudness, so any loud non-speech (a door, a cough, room
tone) reads as voice -- which is why its minimum_rms had to be pushed to 560.
Silero is a small neural model that scores the *probability that a window is
speech*, so it discriminates speech from noise far better: fewer false turn
starts, cleaner barge-in, tighter end-of-turn. That is the #2/#3 win.

FAILURE IS A FALLBACK, NOT A CRASH
----------------------------------
If the ``silero-vad`` package (or torch/numpy) is not installed, ``available()``
returns False and ZENO keeps using EnergyVAD. This never becomes the reason the
microphone stops working.

INTERFACE
---------
``voiced(pcm16) -> (is_speech, level)`` matches EnergyVAD, EXCEPT the second
value is a speech *probability* in [0, 1] (EnergyVAD returns an RMS magnitude).
Callers that only use the boolean can swap freely; callers that read the second
value for a loudness threshold must account for the different scale -- which is
why remote_mic is NOT rewired here (see INTEGRATION_NOTES.md).
"""

from __future__ import annotations

import os
from array import array

# Silero's fixed analysis windows (samples). 16 kHz is ZENO's mic rate.
_WINDOW_16K = 512
_WINDOW_8K = 256
_DEFAULT_THRESHOLD = 0.5   # silero-vad's documented default


class SileroVAD:
    def __init__(self, *, threshold: float = _DEFAULT_THRESHOLD,
                 sampling_rate: int = 16000) -> None:
        self.threshold = max(0.1, min(0.95, float(threshold)))
        self.sampling_rate = 16000 if int(sampling_rate) >= 16000 else 8000
        self.window = _WINDOW_16K if self.sampling_rate == 16000 else _WINDOW_8K
        self._model = None
        self._tried = False
        self._err = ""
        self._buf = array("h")   # int16 remainder between calls

    # -- lifecycle ---------------------------------------------------------
    def _ensure(self) -> bool:
        if self._model is not None:
            return True
        if self._tried:
            return False
        self._tried = True
        try:
            from silero_vad import load_silero_vad
            self._model = load_silero_vad(onnx=True)
            return True
        except Exception as exc:  # noqa: BLE001 -- optional dependency
            self._err = f"{type(exc).__name__}: {exc}"[:150]
            return False

    def available(self) -> bool:
        return self._ensure()

    def reset(self) -> None:
        """Clear the streaming state between utterances (the model is an RNN)."""
        self._buf = array("h")
        model = self._model
        if model is not None:
            try:
                model.reset_states()
            except Exception:  # noqa: BLE001
                pass

    # -- inference (isolated so it can be mocked in tests) -----------------
    def _infer(self, window_i16) -> float:
        import numpy as np
        import torch

        arr = np.asarray(window_i16, dtype=np.float32) / 32768.0
        with torch.no_grad():
            return float(self._model(torch.from_numpy(arr), self.sampling_rate).item())

    # -- the EnergyVAD-compatible gate ------------------------------------
    def voiced(self, pcm16: bytes) -> tuple[bool, float]:
        """(is_speech, peak_speech_probability) for the audio in this chunk.
        Audio is buffered and analysed in fixed silero windows; a chunk that is
        not a whole number of windows keeps its remainder for next time."""
        if not self._ensure():
            return False, 0.0
        chunk = array("h")
        chunk.frombytes(pcm16[: len(pcm16) - (len(pcm16) % 2)])
        self._buf.extend(chunk)
        peak = 0.0
        while len(self._buf) >= self.window:
            window = self._buf[: self.window]
            del self._buf[: self.window]
            try:
                peak = max(peak, self._infer(window))
            except Exception as exc:  # noqa: BLE001 -- degrade, never crash the mic
                self._err = type(exc).__name__
                return peak >= self.threshold, peak
        return peak >= self.threshold, peak

    def status(self) -> dict:
        return {"backend": "silero", "available": self._model is not None,
                "threshold": self.threshold, "window": self.window,
                "sampling_rate": self.sampling_rate, "error": self._err}


def make_vad(*, open_factor: float = 2.8, minimum_rms: float = 560.0):
    """Return the configured VAD. Default is EnergyVAD (ZENO's existing
    behaviour, unchanged). ``ZENO_VAD_BACKEND=silero`` selects the neural VAD
    when it is actually available, else it transparently falls back to
    EnergyVAD -- so turning it on can never leave ZENO without a VAD."""
    backend = os.environ.get("ZENO_VAD_BACKEND", "energy").strip().casefold()
    if backend in ("silero", "neural"):
        try:
            thr = float(os.environ.get("ZENO_SILERO_VAD_THRESHOLD", _DEFAULT_THRESHOLD))
        except (TypeError, ValueError):
            thr = _DEFAULT_THRESHOLD
        candidate = SileroVAD(threshold=thr)
        if candidate.available():
            return candidate
    from reyes_agent.wake.vad import EnergyVAD
    return EnergyVAD(open_factor=open_factor, minimum_rms=minimum_rms)
