"""Deepgram Nova-3 final-transcript backend."""

from __future__ import annotations

import logging
import time

import httpx
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
        # A BOUNDED connect timeout is the whole point here. Deepgram is only
        # intermittently reachable from some networks; when a connect blackholes,
        # the SDK's default client leaves the socket connect UNBOUNDED and then
        # retries it twice, so a single transcribe hung a worker for up to ~200s
        # (measured in the pool's timed-out tasks). With only a few workers, a
        # couple of those starved every brain/voice turn behind them. Cap connect
        # at 3s, reads at the transcribe budget, and disable the SDK's own
        # retries -- the STT manager's circuit breaker is the retry authority --
        # so a dead connect frees the worker in ~3s and the breaker opens.
        read = float(max(3, config.TRANSCRIBE_TIMEOUT_SECONDS))
        httpx_client = httpx.Client(
            timeout=httpx.Timeout(connect=3.0, read=read, write=5.0, pool=3.0),
            # Don't reuse a long-lived connection: the same SSL-inspecting proxy
            # that resets idle model connections resets these too, and a reused
            # dead socket is what turned a transcribe into a multi-second hang.
            limits=httpx.Limits(max_keepalive_connections=0, max_connections=10,
                                keepalive_expiry=1.0),
        )
        _client = DeepgramClient(
            api_key=config.DEEPGRAM_API_KEY,
            timeout=read,
            max_retries=0,
            httpx_client=httpx_client,
        )
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

