"""One STT manager with cloud primary and explicitly configured local fallback."""

from reyes_agent.voice.stt import cloud
from reyes_agent.voice.stt.manager import STTError, status

# Compatibility test/injection seam retained from the former single module.
_client = None


def transcribe_result(audio: bytes) -> dict:
    if _client is not None:
        cloud._client = _client
    from reyes_agent.voice.stt.manager import transcribe_result as managed

    return managed(audio)


def transcribe(audio: bytes) -> str:
    return str(transcribe_result(audio)["transcript"])

__all__ = ["STTError", "status", "transcribe", "transcribe_result"]
