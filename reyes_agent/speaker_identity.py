"""Compatibility facade for ZENO's model-backed owner voice evidence.

The real implementation lives under :mod:`reyes_agent.identity.speaker`.
This module preserves established imports and request-scoped privacy gates.
No raw enrollment or command audio is stored, and voice evidence never
authorizes sensitive actions by itself.
"""

from __future__ import annotations

import contextlib
import contextvars
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from reyes_agent import config
from reyes_agent.identity.speaker.embeddings import EmbeddingBackend
from reyes_agent.identity.speaker.manager import SpeakerManager
from reyes_agent.identity.speaker.verifier import OWNER_HIGH, OWNER_LIKELY, UNCERTAIN, UNKNOWN

# New canonical vocabulary.
OWNER_CONFIRMED = OWNER_HIGH
LIKELY_OWNER = OWNER_LIKELY
UNKNOWN_SPEAKER = UNKNOWN
# Compatibility-only non-identity conditions.
MULTIPLE_SPEAKERS = "MULTIPLE_SPEAKERS"
INSUFFICIENT_AUDIO = "INSUFFICIENT_AUDIO"
NO_PROFILE = "NO_PROFILE"

_PROFILE_PATH = (
    Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT / ".runtime"))).expanduser()
    / "ZENO" / "Biometrics" / "divine-voice-profile.dat"
)
_LOCK = threading.RLock()
_BACKEND_OVERRIDE: EmbeddingBackend | None = None


class SpeakerIdentityError(ValueError):
    pass


@dataclass(frozen=True)
class SpeakerContext:
    status: str = ""
    confidence: float | None = None
    source: str = "typed"

    @property
    def is_voice(self) -> bool:
        return self.source == "voice"

    @property
    def may_access_private_data(self) -> bool:
        return not self.is_voice or self.status == OWNER_HIGH


_speaker_context: contextvars.ContextVar[SpeakerContext] = contextvars.ContextVar(
    "zeno_speaker_context", default=SpeakerContext()
)


def _manager() -> SpeakerManager:
    return SpeakerManager(_PROFILE_PATH, backend=_BACKEND_OVERRIDE)


def _set_backend_for_tests(backend: EmbeddingBackend | None) -> None:
    """Dependency injection for tests; production never selects a fake model."""
    global _BACKEND_OVERRIDE
    _BACKEND_OVERRIDE = backend


def current_context() -> SpeakerContext:
    return _speaker_context.get()


@contextlib.contextmanager
def use_context(identity: dict[str, Any] | None, *, source: str = "typed") -> Iterator[None]:
    identity = identity or {}
    confidence = identity.get("confidence")
    try:
        confidence = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None
    token = _speaker_context.set(SpeakerContext(str(identity.get("status") or ""), confidence, source))
    try:
        yield
    finally:
        _speaker_context.reset(token)


def enrollment_status() -> dict[str, Any]:
    with _LOCK:
        return _manager().status()


def enroll(clips: list[bytes]) -> dict[str, Any]:
    try:
        with _LOCK:
            result = _manager().enroll(clips)
    except ValueError as exc:
        raise SpeakerIdentityError(str(exc)) from exc
    _emit("speaker.profile_enrolled", {"clips": len(clips), "stored_audio": False, "model_backed": True})
    return result


def identify(audio: bytes) -> dict[str, Any]:
    with _LOCK:
        result = _manager().identify(audio)
    _record(result)
    return result


def delete_profile() -> dict[str, Any]:
    with _LOCK:
        result = _manager().delete()
    _emit("speaker.profile_deleted", {"existed": result["deleted"]})
    return result


def profile_fingerprint() -> str:
    with _LOCK:
        return _manager().fingerprint()


def _record(result: dict[str, Any]) -> None:
    try:
        from reyes_agent.confidence import record

        record("speaker", result.get("confidence"),
               f"{result.get('status')}: similarity={result.get('speaker_similarity')} quality={result.get('audio_quality')}")
    except Exception:
        pass
    _emit("speaker.identity", {
        key: result.get(key) for key in (
            "status", "confidence", "speaker_similarity", "audio_quality", "spoof_score",
            "spoof_state", "inference_ms", "model", "reason",
        )
    })


def _emit(event_type: str, payload: dict[str, Any]) -> None:
    try:
        from reyes_agent import event_bus

        event_bus.publish(event_type, payload, source="speaker_identity")
    except Exception:
        pass


def privacy_denial(tool_name: str) -> str | None:
    private_tools = {
        "list_memories", "search_memories", "memory_versions", "compare_memory_versions",
        "search_notes", "list_notes", "search_vault_semantic", "read_file", "check_email", "read_email",
        "list_calendar_events", "cancel_calendar_event", "browser_read", "browser_extract",
        "browser_screenshot", "read_clipboard", "portfolio_report", "get_investment_policy",
        "investment_performance_report", "list_project_files", "read_document", "read_screen_text",
    }
    context = current_context()
    if context.is_voice and tool_name in private_tools and not context.may_access_private_data:
        return (
            "Private ZENO data is protected because this voice was not verified as Divine with high confidence. "
            "Use the local dashboard with a stronger sign-in or confirmation method."
        )
    return None


def requires_strong_confirmation(tool_name: str) -> bool:
    context = current_context()
    if not context.is_voice:
        return False
    try:
        from reyes_agent.confidence import risk_for_tool

        return risk_for_tool(tool_name) in {"high", "critical"}
    except Exception:
        return False
