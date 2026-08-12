"""Fault-isolated STT selection and real event emission."""

from __future__ import annotations

import logging

from reyes_agent.voice.stt import cloud
from reyes_agent.voice.stt.events import STT_FINAL
from reyes_agent.voice.stt import faster_whisper as local_whisper

_LOG = logging.getLogger(__name__)


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


def transcribe_result(audio: bytes) -> dict:
    if not audio:
        return {"transcript": "", "confidence": None}
    failures: list[str] = []
    for name, available, operation in (
        ("deepgram", cloud.status()["state"] == "READY", lambda: cloud.transcribe(audio)),
        ("faster-whisper", local_whisper.ready(), lambda: local_whisper.transcribe(audio)),
    ):
        if not available:
            continue
        try:
            result = operation()
            _emit(result)
            # Preserve the established public seam. Backend/profile/latency
            # details are emitted to diagnostics rather than changing every
            # caller's result contract.
            return {"transcript": str(result.get("transcript") or ""),
                    "confidence": result.get("confidence")}
        except Exception as exc:
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            _LOG.warning("STT backend failed and was isolated backend=%s error=%s", name, type(exc).__name__)
    detail = "; ".join(failures) if failures else "No STT backend is configured"
    raise STTError(detail)


def transcribe(audio: bytes) -> str:
    return str(transcribe_result(audio)["transcript"])


def status() -> dict:
    from reyes_agent.voice.stt import sensevoice, sherpa, simulstreaming

    return {"primary": cloud.status(), "fallback": local_whisper.status(),
            "optional": {"sherpa": sherpa.status(), "sensevoice": sensevoice.status(),
                         "simulstreaming": simulstreaming.status()},
            "events": ["STT_PARTIAL", "STT_STABLE_PARTIAL", "STT_FINAL"],
            "actual_current_events": ["STT_FINAL"],
            "honesty": "The current WebView route is clip-final; no partial transcript is fabricated."}
