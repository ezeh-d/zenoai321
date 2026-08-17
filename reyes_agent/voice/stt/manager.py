"""Fault-isolated STT selection and real event emission."""

from __future__ import annotations

import logging
import threading
import time

from reyes_agent.voice.stt import cloud
from reyes_agent.voice.stt.events import STT_FINAL
from reyes_agent.voice.stt import faster_whisper as local_whisper

_LOG = logging.getLogger(__name__)
_CLOUD_BREAKER_COOLDOWN_S = 30.0
_breaker_lock = threading.Lock()
_cloud_circuit_until = 0.0
_cloud_last_error = ""


class STTError(Exception):
    pass


def _emit(result: dict) -> None:
    try:
        from reyes_agent import event_bus

        event_bus.publish("voice.stt.final", {
            "event": STT_FINAL, "backend": result.get("backend"),
            "confidence": result.get("confidence"), "chars": len(str(result.get("transcript") or "")),
            "latency_s": result.get("latency_s"),
        }, source="stt")
    except Exception:
        pass


def _cloud_allowed(now: float | None = None) -> bool:
    instant = time.monotonic() if now is None else now
    with _breaker_lock:
        return instant >= _cloud_circuit_until


def _record_cloud_success() -> None:
    global _cloud_circuit_until, _cloud_last_error
    with _breaker_lock:
        _cloud_circuit_until = 0.0
        _cloud_last_error = ""


def _record_cloud_failure(exc: Exception) -> None:
    global _cloud_circuit_until, _cloud_last_error
    with _breaker_lock:
        _cloud_circuit_until = time.monotonic() + _CLOUD_BREAKER_COOLDOWN_S
        _cloud_last_error = f"{type(exc).__name__}: {exc}"


def _breaker_status() -> dict:
    with _breaker_lock:
        remaining = max(0.0, _cloud_circuit_until - time.monotonic())
        return {"state": "OPEN" if remaining else "CLOSED",
                "retry_in_s": round(remaining, 1), "last_error": _cloud_last_error}


def _reset_breaker_for_tests() -> None:
    _record_cloud_success()


def transcribe_result(audio: bytes) -> dict:
    if not audio:
        return {"transcript": "", "confidence": None}
    failures: list[str] = []
    cloud_ready = cloud.status()["state"] == "READY"
    for name, available, operation in (
        ("deepgram", cloud_ready and _cloud_allowed(), lambda: cloud.transcribe(audio)),
        ("faster-whisper", local_whisper.ready(), lambda: local_whisper.transcribe(audio)),
    ):
        if not available:
            continue
        try:
            result = operation()
            if name == "deepgram":
                _record_cloud_success()
            _emit(result)
            # Preserve the established public seam. Backend/profile/latency
            # details are emitted to diagnostics rather than changing every
            # caller's result contract.
            return {"transcript": str(result.get("transcript") or ""),
                    "confidence": result.get("confidence")}
        except Exception as exc:
            if name == "deepgram":
                _record_cloud_failure(exc)
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            _LOG.warning("STT backend failed and was isolated backend=%s error=%s", name, type(exc).__name__)
    if cloud_ready and not _cloud_allowed():
        breaker = _breaker_status()
        failures.append(
            f"deepgram circuit open for {breaker['retry_in_s']:.1f}s after {breaker['last_error']}")
    detail = "; ".join(dict.fromkeys(failures)) if failures else "No STT backend is configured"
    raise STTError(detail)


def transcribe(audio: bytes) -> str:
    return str(transcribe_result(audio)["transcript"])


def status() -> dict:
    from reyes_agent.voice.stt import sensevoice, sherpa, simulstreaming

    return {"primary": {**cloud.status(), "circuit": _breaker_status()},
            "fallback": local_whisper.status(),
            "optional": {"sherpa": sherpa.status(), "sensevoice": sensevoice.status(),
                         "simulstreaming": simulstreaming.status()},
            "events": ["STT_PARTIAL", "STT_STABLE_PARTIAL", "STT_FINAL"],
            "actual_current_events": ["STT_FINAL"],
            "honesty": "The current WebView route is clip-final; no partial transcript is fabricated."}
