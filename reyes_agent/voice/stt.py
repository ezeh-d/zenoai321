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


def transcribe(wav_bytes: bytes) -> str:
    """Give it a WAV clip, get back what was said. Empty in, empty out."""
    if not wav_bytes:
        return ""
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
        return resp.results.channels[0].alternatives[0].transcript
    except (AttributeError, IndexError) as exc:
        raise STTError("No transcript came back in the response.") from exc
