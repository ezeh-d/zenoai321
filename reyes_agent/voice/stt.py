"""Speech-to-text seam: give it audio, get back text.

Deepgram today. Swap providers by rewriting this file -- callers only see
`transcribe()`. Verified working end-to-end (2026-07-22): a locally
synthesized clip round-tripped through this exact call and came back with
an accurate transcript.
"""

from __future__ import annotations

from deepgram import DeepgramClient

from reyes_agent import config


class STTError(Exception):
    """Raised when speech can't be transcribed -- network, auth, or a bad clip."""


_client: DeepgramClient | None = None


def _get_client() -> DeepgramClient:
    global _client
    if _client is None:
        if not config.DEEPGRAM_API_KEY:
            raise STTError("No DEEPGRAM_API_KEY set. Add one to .env, then restart.")
        _client = DeepgramClient(api_key=config.DEEPGRAM_API_KEY)
    return _client


def transcribe_result(wav_bytes: bytes) -> dict[str, str | float | None]:
    """Return the provider's transcript and its real confidence, if supplied."""
    if not wav_bytes:
        return {"transcript": "", "confidence": None}
    client = _get_client()
    try:
        resp = client.listen.v1.media.transcribe_file(
            request=wav_bytes,
            model=config.DEEPGRAM_MODEL,
            smart_format=True,
            punctuate=True,
        )
    except Exception as exc:  # noqa: BLE001 -- surfaced to the caller, never crashes the loop
        raise STTError(str(exc)) from exc

    try:
        alternative = resp.results.channels[0].alternatives[0]
        raw_confidence = getattr(alternative, "confidence", None)
        try:
            confidence = float(raw_confidence) if raw_confidence is not None else None
        except (TypeError, ValueError):
            confidence = None
        if confidence is not None and not 0.0 <= confidence <= 1.0:
            confidence = None
        return {"transcript": str(alternative.transcript or ""), "confidence": confidence}
    except (AttributeError, IndexError) as exc:
        raise STTError("No transcript came back in the response.") from exc


def transcribe(wav_bytes: bytes) -> str:
    """Give it a clip, get back only text for legacy callers."""
    return str(transcribe_result(wav_bytes)["transcript"])
