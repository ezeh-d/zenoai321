"""Streaming transcription -- the difference between 1.9 seconds and 0.2.

WHY BATCH CANNOT BE FAST, NO MATTER HOW IT IS TUNED
---------------------------------------------------
The existing path waits for the speaker to stop, wraps the whole utterance in
a WAV, uploads it, and waits for the full transcript to come back. Measured
here across 97 real turns: median 1.86s, worst 10.42s. None of that is
waste -- it is the shape of the request. The audio cannot be uploaded before
it exists, and the answer cannot arrive before the upload finishes.

Streaming inverts it. Audio goes up as it is spoken, so by the moment the
speaker stops, the transcript is already nearly complete and only the last
fragment is outstanding. The wait collapses from "transcribe an utterance" to
"finish the last 200 milliseconds of one".

ENDPOINTING MOVES TOO, AND THAT IS THE SECOND WIN
--------------------------------------------------
The energy VAD here waits 0.55s of silence before deciding a turn ended,
because an energy threshold cannot tell a pause from an ending. Deepgram
decides that from the acoustic model and tells us with UtteranceEnd, so the
silence budget shrinks without truncating people mid-sentence.

WHAT THIS DOES NOT DO
---------------------
It does not replace the VAD -- that still gates when a session is worth
opening, which keeps a live socket from being held open on an empty room. It
does not change wake-word handling, the brain, or TTS. It replaces one leg:
PCM in, transcript out, sooner.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from reyes_agent import config

_LOG = logging.getLogger(__name__)

ENDPOINT = "wss://api.deepgram.com/v1/listen"

# How much silence Deepgram should treat as the end of a phrase. 300 ms is
# responsive without clipping people who pause to think; UtteranceEnd at
# 1000 ms is the backstop for when interim results stop arriving at all.
ENDPOINTING_MS = 300
UTTERANCE_END_MS = 1000

# A socket held open on a silent room costs money and a file handle. Closed
# after this much continuous quiet; the next speech opens a new one.
IDLE_CLOSE_S = 20.0

# Measured against the live API: 8 keyterms connect, 10 are rejected with a
# bare HTTP 400. The batch endpoint takes 40, which is what made the first
# attempt here fail outright.
MAX_KEYTERMS = 8


@dataclass
class Transcript:
    text: str = ""
    confidence: float = 0.0
    is_final: bool = False
    speech_final: bool = False
    at: float = field(default_factory=time.time)
    latency_s: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"transcript": self.text, "confidence": round(self.confidence, 4),
                "is_final": self.is_final, "speech_final": self.speech_final,
                "latency_s": round(self.latency_s, 3), "backend": "deepgram-streaming"}


def available() -> tuple[bool, str]:
    if not getattr(config, "DEEPGRAM_API_KEY", ""):
        return False, "no DEEPGRAM_API_KEY"
    try:
        import websockets  # noqa: F401
    except Exception:  # noqa: BLE001
        return False, "websockets is not installed"
    return True, "deepgram streaming ready"


def _url() -> str:
    from urllib.parse import urlencode

    from reyes_agent.voice.vocabulary import terms

    params = {
        "model": getattr(config, "DEEPGRAM_MODEL", "nova-3"),
        "language": getattr(config, "DEEPGRAM_LANGUAGE", "en"),
        "encoding": "linear16",
        "sample_rate": "16000",
        "channels": "1",
        "interim_results": "true",
        "punctuate": "true",
        "smart_format": "true",
        "endpointing": str(ENDPOINTING_MS),
        "utterance_end_ms": str(UTTERANCE_END_MS),
        # Streaming charges by connection time, and a turn is short.
        "no_delay": "true",
    }
    query = urlencode(params)
    # Keyterms bias the model toward names it would otherwise mangle -- the
    # same idea the batch path uses, so both hear "ZENO" alike.
    #
    # THE STREAMING ENDPOINT ACCEPTS FAR FEWER THAN THE FILE ENDPOINT.
    # Measured against the live API: 8 keyterms connect, 10 are rejected with
    # HTTP 400 and no explanation of which parameter offended. Passing the
    # batch list of 40 through here is what made the first version fail
    # outright. Capped below the measured ceiling, and each term is properly
    # encoded rather than concatenated raw.
    try:
        keyterms = list(dict.fromkeys([*getattr(config, "DEEPGRAM_KEYTERMS", []),
                                       *terms(20)]))
        if keyterms and str(params["model"]).startswith("nova-3"):
            query += "".join(f"&{urlencode({'keyterm': k})}"
                             for k in keyterms[:MAX_KEYTERMS])
    except Exception:  # noqa: BLE001
        pass
    return f"{ENDPOINT}?{query}"


class StreamingTranscriber:
    """One live Deepgram socket, fed PCM from whichever microphone is active.

    Runs its own event loop on a daemon thread: the audio arrives from a
    synchronous frame callback, and bridging into asyncio at the call site
    would put a socket in the path of the audio thread.
    """

    def __init__(self, on_transcript: Callable[[Transcript], None]) -> None:
        self._on_transcript = on_transcript
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._socket: Any = None
        self._lock = threading.RLock()
        self._open = threading.Event()
        self._stop = threading.Event()
        self._last_audio_at = 0.0
        self._speech_started_at = 0.0
        self._sent_bytes = 0
        self._finals = 0
        self._last_error = ""

    # -- lifecycle --------------------------------------------------------
    def start(self, *, wait_timeout_s: float = 6.0) -> bool:
        """Start the socket thread.

        A zero wait is used by the audio-frame consumer: opening a network
        socket must never block the only audio worker. Callers that need a
        confirmed connection may retain the bounded default wait.
        """
        ready, why = available()
        if not ready:
            self._last_error = why
            return False
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return True
            self._stop.clear()
            self._open.clear()
            self._thread = threading.Thread(target=self._run, name="zeno-stt-stream",
                                            daemon=True)
            self._thread.start()
        if wait_timeout_s <= 0:
            return True
        return self._open.wait(timeout=min(6.0, float(wait_timeout_s)))

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._session())
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"{type(exc).__name__}: {exc}"
        finally:
            self._open.clear()
            try:
                self._loop.close()
            except Exception:  # noqa: BLE001
                pass

    async def _session(self) -> None:
        import websockets

        headers = {"Authorization": f"Token {config.DEEPGRAM_API_KEY}"}
        try:
            # websockets renamed this parameter across versions; try both
            # rather than pinning, because the installed version varies.
            try:
                socket = await websockets.connect(
                    _url(), additional_headers=headers, max_size=None,
                    open_timeout=3.0, close_timeout=2.0)
            except TypeError:
                socket = await websockets.connect(
                    _url(), extra_headers=headers, max_size=None,
                    open_timeout=3.0, close_timeout=2.0)
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"connect failed: {type(exc).__name__}: {exc}"
            return

        self._socket = socket
        self._open.set()
        _LOG.info("deepgram streaming session opened")
        try:
            while not self._stop.is_set():
                remaining = (IDLE_CLOSE_S if not self._last_audio_at else
                             max(0.1, IDLE_CLOSE_S - self.idle_s))
                try:
                    raw = await asyncio.wait_for(socket.recv(), timeout=remaining)
                except TimeoutError:
                    if not self._last_audio_at or self.idle_s >= IDLE_CLOSE_S:
                        break
                    continue
                if self._stop.is_set():
                    break
                self._handle(raw)
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"{type(exc).__name__}: {exc}"
        finally:
            self._open.clear()
            self._socket = None
            try:
                await socket.close()
            except Exception:  # noqa: BLE001
                pass

    def _handle(self, raw: str | bytes) -> None:
        try:
            message = json.loads(raw)
        except Exception:  # noqa: BLE001
            return
        kind = message.get("type", "")

        if kind == "UtteranceEnd":
            # Deepgram decided the turn ended. Emitted even when the last
            # interim never got promoted, so a turn cannot be lost to silence.
            self._on_transcript(Transcript(text="", is_final=True,
                                           speech_final=True,
                                           latency_s=self._elapsed()))
            return
        if kind != "Results":
            return

        try:
            alternative = message["channel"]["alternatives"][0]
        except (KeyError, IndexError):
            return
        text = str(alternative.get("transcript") or "").strip()
        if not text:
            return
        if self._speech_started_at == 0.0:
            self._speech_started_at = time.time()
        is_final = bool(message.get("is_final"))
        speech_final = bool(message.get("speech_final"))
        if is_final:
            self._finals += 1
        self._on_transcript(Transcript(
            text=text, confidence=float(alternative.get("confidence") or 0.0),
            is_final=is_final, speech_final=speech_final,
            latency_s=self._elapsed()))

    def _elapsed(self) -> float:
        return max(0.0, time.time() - self._last_audio_at) if self._last_audio_at else 0.0

    # -- audio ------------------------------------------------------------
    def send(self, pcm16: bytes) -> bool:
        """Hand 16 kHz mono PCM to the socket. Never blocks the audio thread."""
        if not pcm16 or not self._open.is_set() or self._loop is None:
            return False
        socket = self._socket
        if socket is None:
            return False
        self._last_audio_at = time.time()
        self._sent_bytes += len(pcm16)
        try:
            asyncio.run_coroutine_threadsafe(socket.send(pcm16), self._loop)
            return True
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"send failed: {type(exc).__name__}"
            return False

    def finish(self) -> None:
        """Tell Deepgram the utterance is over so it flushes the last words."""
        socket, loop = self._socket, self._loop
        if socket is None or loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                socket.send(json.dumps({"type": "Finalize"})), loop)
        except Exception:  # noqa: BLE001
            pass

    def close(self) -> None:
        self._stop.set()
        socket, loop = self._socket, self._loop
        if socket is not None and loop is not None:
            try:
                asyncio.run_coroutine_threadsafe(
                    socket.send(json.dumps({"type": "CloseStream"})), loop)
            except Exception:  # noqa: BLE001
                pass
        with self._lock:
            thread = self._thread
            self._thread = None
        if thread is not None:
            thread.join(timeout=3)

    @property
    def idle_s(self) -> float:
        return time.time() - self._last_audio_at if self._last_audio_at else 0.0

    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    @property
    def last_error(self) -> str:
        return self._last_error

    def status(self) -> dict[str, Any]:
        ready, why = available()
        return {"state": "ONLINE" if self._open.is_set() else
                ("READY" if ready else "UNAVAILABLE"),
                "detail": why, "sent_bytes": self._sent_bytes,
                "finals": self._finals, "idle_s": round(self.idle_s, 1),
                "endpointing_ms": ENDPOINTING_MS,
                "last_error": self._last_error or "none"}


def status() -> dict[str, Any]:
    ready, why = available()
    return {"state": "READY" if ready else "UNAVAILABLE", "detail": why,
            "endpointing_ms": ENDPOINTING_MS,
            "why": ("Batch upload cannot start before the speaker stops. "
                    "Streaming sends audio as it is spoken, so only the last "
                    "fragment is outstanding when they do.")}
