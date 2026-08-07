"""Speech-to-text seam: give it audio, get back text.

Deepgram today. Swap providers by rewriting this file -- callers only see
`transcribe()`. Verified working end-to-end (2026-07-22): a locally
synthesized clip round-tripped through this exact call and came back with
an accurate transcript.
"""

from __future__ import annotations

import logging
import time

from deepgram import DeepgramClient

from reyes_agent import config


class STTError(Exception):
    """Raised when speech can't be transcribed -- network, auth, or a bad clip."""


_client: DeepgramClient | None = None
_LOG = logging.getLogger(__name__)


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
    started = time.monotonic()
    _LOG.info("speech transcription started bytes=%d", len(wav_bytes))
    try:
        resp = client.listen.v1.media.transcribe_file(
            request=wav_bytes,
            model=config.DEEPGRAM_MODEL,
            smart_format=True,
            punctuate=True,
            # The SDK's request timeout interrupts the actual httpx call.
            # A worker deadline alone cannot stop a synchronous SDK request.
            request_options={
                # Leave a small margin for the worker/browser to receive and
                # cleanly render the provider timeout response.
                "timeout_in_seconds": max(1, config.TRANSCRIBE_TIMEOUT_SECONDS - 2),
                "max_retries": 0,
            },
        )
    except Exception as exc:  # noqa: BLE001 -- surfaced to the caller, never crashes the loop
        _LOG.warning("speech transcription failed after %.3fs: %s", time.monotonic() - started, type(exc).__name__)
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
        transcript = str(alternative.transcript or "")
        _LOG.info("speech transcription finished duration_s=%.3f chars=%d", time.monotonic() - started, len(transcript))
        return {"transcript": transcript, "confidence": confidence}
    except (AttributeError, IndexError) as exc:
        raise STTError("No transcript came back in the response.") from exc


def transcribe(wav_bytes: bytes) -> str:
    """Give it a clip, get back only text for legacy callers."""
    return str(transcribe_result(wav_bytes)["transcript"])
