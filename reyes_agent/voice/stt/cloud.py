"""Deepgram Nova-3 final-transcript backend."""

from __future__ import annotations

import logging
import time

from deepgram import DeepgramClient

from reyes_agent import config
from reyes_agent.voice.vocabulary import terms

_client: DeepgramClient | None = None
_LOG = logging.getLogger(__name__)


def _get_client() -> DeepgramClient:
    global _client
    if _client is None:
        if not config.DEEPGRAM_API_KEY:
            raise RuntimeError("No DEEPGRAM_API_KEY set. Add one to .env, then restart.")
        _client = DeepgramClient(api_key=config.DEEPGRAM_API_KEY)
    return _client


def transcribe(wav_bytes: bytes) -> dict:
    started = time.monotonic()
    _LOG.info("speech transcription started backend=deepgram bytes=%d", len(wav_bytes))
    keyterms = list(dict.fromkeys([*config.DEEPGRAM_KEYTERMS, *terms(80)]))
    try:
        response = _get_client().listen.v1.media.transcribe_file(
            request=wav_bytes,
            model=config.DEEPGRAM_MODEL,
            language=config.DEEPGRAM_LANGUAGE,
            keyterm=keyterms if config.DEEPGRAM_MODEL.startswith("nova-3") else None,
            smart_format=True,
            punctuate=True,
            request_options={"timeout_in_seconds": max(1, config.TRANSCRIBE_TIMEOUT_SECONDS - 2), "max_retries": 0},
        )
        alternative = response.results.channels[0].alternatives[0]
        raw_confidence = getattr(alternative, "confidence", None)
        confidence = float(raw_confidence) if raw_confidence is not None else None
        if confidence is not None and not 0.0 <= confidence <= 1.0:
            confidence = None
        return {"transcript": str(alternative.transcript or ""), "confidence": confidence,
                "backend": "deepgram-nova-3", "profile": "CLOUD_STREAMING",
                "latency_s": round(time.monotonic() - started, 4), "partial_events": 0}
    except Exception as exc:
        _LOG.warning("speech transcription failed backend=deepgram duration_s=%.3f error=%s",
                     time.monotonic() - started, type(exc).__name__)
        raise RuntimeError(str(exc)) from exc


def status() -> dict:
    return {"state": "READY" if config.DEEPGRAM_API_KEY else "NOT_CONFIGURED",
            "backend": "Deepgram Nova-3", "profile": "CLOUD_STREAMING",
            "streaming_transport": False,
            "note": "Current browser route submits VAD-bounded clips and emits only provider-final transcripts."}

