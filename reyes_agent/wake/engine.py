"""Bounded local wake-word engine over one existing microphone stream."""

from __future__ import annotations

import io
import os
import threading
import time
import wave
from typing import Any

import numpy as np

from reyes_agent.wake import audio_stream
from reyes_agent.wake.openwakeword_backend import OpenWakeWordBackend
from reyes_agent.wake.state_machine import WakeState, WakeStateMachine
from reyes_agent.wake.vad import EnergyVAD


def _resample(samples: np.ndarray, source_rate: int, target_rate: int = 16000) -> np.ndarray:
    if source_rate == target_rate or not len(samples):
        return samples.astype(np.int16, copy=False)
    duration = len(samples) / float(source_rate)
    target_length = max(1, int(round(duration * target_rate)))
    old_x = np.linspace(0.0, 1.0, len(samples), endpoint=False)
    new_x = np.linspace(0.0, 1.0, target_length, endpoint=False)
    return np.interp(new_x, old_x, samples.astype(np.float32)).clip(-32768, 32767).astype(np.int16)


def decode_wav(data: bytes) -> bytes:
    with wave.open(io.BytesIO(data), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        raw = wav.readframes(wav.getnframes())
    if width != 2:
        raise ValueError("Wake audio must be 16-bit PCM WAV")
    samples = np.frombuffer(raw, dtype=np.int16)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1).astype(np.int16)
    return _resample(samples, rate).tobytes()


class WakeEngine:
    def __init__(self, *, backend: OpenWakeWordBackend | None = None,
                 cooldown_s: float | None = None) -> None:
        self.backend = backend or OpenWakeWordBackend()
        self.state_machine = WakeStateMachine()
        self.vad = EnergyVAD()
        self.cooldown_s = max(0.5, min(30.0, float(cooldown_s if cooldown_s is not None else os.environ.get("ZENO_WAKE_COOLDOWN_S", "3"))))
        self.required_hits = max(1, min(4, int(os.environ.get("ZENO_WAKE_REQUIRED_HITS", "2"))))
        self._lock = threading.RLock()
        self._last_trigger = 0.0
        self._hits = 0
        self._last_score = 0.0
        self._last_model = ""
        self._frames = 0
        self._triggers = 0
        self._false_filtered = 0

    def start(self) -> None:
        if self.state_machine.state in {WakeState.SLEEPING, WakeState.STANDBY}:
            self.state_machine.transition(WakeState.LISTENING_FOR_WAKE, reason="single microphone stream available")

    def stop(self) -> None:
        current = self.state_machine.state
        if current != WakeState.SLEEPING:
            if current != WakeState.STANDBY:
                self.state_machine.transition(WakeState.STANDBY, reason="wake subsystem stopping")
            self.state_machine.transition(WakeState.SLEEPING, reason="wake subsystem stopped")
        self.backend.reset()

    def begin_processing(self) -> None:
        """Reflect a real voice turn without starting a second audio stream."""
        self.start()
        state = self.state_machine.state
        if state == WakeState.LISTENING_FOR_WAKE:
            self.state_machine.transition(WakeState.ACTIVE, reason="voice session activated")
            state = WakeState.ACTIVE
        if state == WakeState.ACTIVE:
            self.state_machine.transition(WakeState.PROCESSING, reason="voice command is being processed")

    def finish_processing(self) -> None:
        if self.state_machine.state == WakeState.PROCESSING:
            self.state_machine.transition(WakeState.ACTIVE, reason="voice response is ready")

    def standby(self) -> None:
        if self.state_machine.state not in {WakeState.SLEEPING, WakeState.STANDBY}:
            self.state_machine.transition(WakeState.STANDBY, reason="owner requested standby")

    def feed_pcm(self, pcm16: bytes, *, now: float | None = None) -> dict[str, Any]:
        self.start()
        stamp = time.monotonic() if now is None else float(now)
        with self._lock:
            self._frames += 1
            if stamp - self._last_trigger < self.cooldown_s:
                return self._result(False, "cooldown")
        voiced, _rms = self.vad.voiced(pcm16)
        if not voiced:
            with self._lock:
                self._hits = 0
            return self._result(False, "no_voice")
        try:
            model, score = self.backend.predict(pcm16)
        except Exception as exc:
            return self._result(False, "backend_unavailable", error=f"{type(exc).__name__}: {exc}")
        with self._lock:
            self._last_model, self._last_score = model, score
            if score >= self.backend.threshold:
                self._hits += 1
            else:
                self._hits = 0
                self._false_filtered += 1
            detected = self._hits >= self.required_hits
            if detected:
                self._hits = 0
                self._last_trigger = stamp
                self._triggers += 1
        if detected:
            self.state_machine.transition(WakeState.ACTIVE, reason=f"{model} score {score:.3f}")
            try:
                from reyes_agent import event_bus
                event_bus.publish("wake.detected", {"model": model, "confidence": round(score, 4)}, source="wake")
            except Exception:
                pass
        return self._result(detected, "detected" if detected else "below_threshold")

    def detect_wav(self, wav_bytes: bytes) -> dict[str, Any]:
        pcm = decode_wav(wav_bytes)
        self.backend.reset()
        best: dict[str, Any] = self._result(False, "no_detection")
        # openWakeWord's streaming features advance at 80 ms. Feed exactly
        # that cadence without a permanent loop or timer.
        frame_bytes = 1280 * 2
        for offset in range(0, len(pcm), frame_bytes):
            frame = pcm[offset: offset + frame_bytes]
            if len(frame) < frame_bytes:
                frame += b"\0" * (frame_bytes - len(frame))
            result = self.feed_pcm(frame)
            if (result["confidence"] > best.get("confidence", 0)
                    or (result.get("error") and not best.get("error"))):
                best = result
            if result["detected"]:
                return result
        return best

    def _result(self, detected: bool, reason: str, *, error: str = "") -> dict[str, Any]:
        status = self.backend.status()
        return {
            "configured": status["state"] == "READY",
            "detected": bool(detected),
            "confidence": round(self._last_score, 4),
            "model": self._last_model,
            "reason": reason,
            "error": error,
            "state": self.state_machine.state.value,
        }

    def status(self) -> dict[str, Any]:
        return {
            **self.state_machine.snapshot(),
            "backend": self.backend.status(),
            "audio": audio_stream.status(),
            "cooldown_s": self.cooldown_s,
            "required_hits": self.required_hits,
            "frames_processed": self._frames,
            "triggers": self._triggers,
            "false_positive_candidates_filtered": self._false_filtered,
            "last_confidence": round(self._last_score, 4),
        }


_engine: WakeEngine | None = None
_engine_lock = threading.Lock()


def get_wake_engine() -> WakeEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = WakeEngine()
    return _engine
