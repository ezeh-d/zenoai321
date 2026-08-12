"""Real WebRTC phone microphone transport and VAD-bounded turn adapter.

The phone is an audio endpoint only. It sends encrypted Opus to this module;
decoded 16 kHz mono PCM enters ZENO's existing AudioManager and then the same
wake, speaker, STT, brain and desktop speech services used by local voice.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import threading
import time
import wave
from collections.abc import Callable
from typing import Any

from reyes_agent.audio.manager import AudioFrame, get_audio_manager
from reyes_agent import config
from reyes_agent.remote_mic.quality import AudioQuality
from reyes_agent.remote_mic.selector import MicrophoneSelector
from reyes_agent.wake.vad import EnergyVAD

_LOG = logging.getLogger(__name__)
# Speech recognition does not hear a name the way it is spelled. Deepgram
# renders "ZENO" as Zeno, Zeeno, Xeno, Zino, Seno or Zenno depending on accent
# and how the word is stressed -- and the old pattern accepted exactly one
# spelling, so a correctly heard wake word was rejected for being spelled the
# way it sounded.
_WAKE_SPELLINGS = ("zeno", "zeeno", "xeno", "zino", "seno", "zenno", "zenoh",
                   "zenor", "xenon", "zeener")

# Short filler the owner naturally says first. Requiring the wake word at
# character zero rejects "um, zeno" and "ok zeno" -- which are the SAME
# intent, just spoken by a person rather than typed.
_LEAD = r"(?:\s*(?:um|uh|er|ok|okay|hey|yo|so|please|abeg)\b[\s,]*){0,2}"


def _wake_pattern() -> re.Pattern[str]:
    """Built from config.WAKE_PHRASES so there is ONE source of truth.

    The hardcoded pattern this replaces accepted only zeno/hey zeno/yo zeno
    while config listed 'wake up zeno' and 'bro' as well -- so two configured
    wake phrases silently did nothing on the phone.
    """
    from reyes_agent import config

    phrases = [str(p).strip().lower()
               for p in getattr(config, "WAKE_PHRASES", ["zeno"]) if str(p).strip()]
    alternatives: list[str] = []
    for phrase in phrases:
        if "zeno" in phrase:
            # Let every spelling stand in for the name inside the phrase, so
            # "wake up zeno" also matches "wake up zeeno".
            head = re.escape(phrase.replace("zeno", "\x00")).replace(
                re.escape("\x00"), f"(?:{'|'.join(_WAKE_SPELLINGS)})")
            alternatives.append(head)
        else:
            alternatives.append(re.escape(phrase))
    alternatives.sort(key=len, reverse=True)      # longest first: "wake up zeno" before "zeno"
    return re.compile(
        rf"^\s*{_LEAD}(?:{'|'.join(alternatives)})\b[\s,;:!.?-]*(.*)$",
        re.I | re.S)


_WAKE = _wake_pattern()
CommandHandler = Callable[[Any, str, dict[str, Any], str, str], dict[str, Any]]


def _wav(pcm: bytes, sample_rate: int = 16_000) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)
    return output.getvalue()


class RemoteTurnConsumer:
    """One event-driven VAD segmenter; expensive work goes to the worker pool."""

    def __init__(self) -> None:
        self._vad = EnergyVAD(open_factor=2.1, minimum_rms=140.0)
        self._lock = threading.RLock()
        self._pcm = bytearray()
        self._speaking = False
        self._voiced_frames = 0
        self._silence_s = 0.0
        self._started = 0.0
        self._busy = False
        self._handler: CommandHandler | None = None
        # Streaming transcription runs ALONGSIDE the existing segmenter
        # rather than replacing it. The VAD still decides where a turn
        # begins and ends -- that logic works and is what wake-word handling
        # is built on. All that moves is WHEN the audio is uploaded: as it
        # is spoken, instead of after the speaker stops. So the risk is
        # bounded to "the transcript arrives from a different place", and
        # batch remains underneath as the fallback.
        self._stream: Any = None
        self._stream_parts: list[str] = []
        self._stream_confidence = 0.0
        self._stream_lock = threading.RLock()

    def _streaming_enabled(self) -> bool:
        from reyes_agent import config

        return bool(getattr(config, "STT_STREAMING", True))

    def _ensure_stream(self) -> Any:
        """The live socket, started on first speech and reused after that."""
        if not self._streaming_enabled():
            return None
        with self._stream_lock:
            if self._stream is not None:
                return self._stream
            try:
                from reyes_agent.voice.stt.streaming import StreamingTranscriber

                transcriber = StreamingTranscriber(on_transcript=self._on_stream)
                if not transcriber.start():
                    self._emit("remote_mic.stt_stream_unavailable",
                               {"detail": transcriber.status().get("last_error", "")})
                    return None
                self._stream = transcriber
                return transcriber
            except Exception as exc:  # noqa: BLE001
                self._emit("remote_mic.stt_stream_unavailable",
                           {"detail": f"{type(exc).__name__}: {exc}"})
                return None

    def _on_stream(self, result: Any) -> None:
        """Collect finalised fragments as Deepgram promotes them."""
        with self._stream_lock:
            if getattr(result, "is_final", False) and getattr(result, "text", ""):
                self._stream_parts.append(result.text)
                self._stream_confidence = max(self._stream_confidence,
                                              float(getattr(result, "confidence", 0.0)))

    def _drain_stream(self, wait_s: float = 0.45) -> tuple[str, float]:
        """The transcript for the turn that just ended.

        Only the tail is outstanding by now -- everything before it went up
        while the owner was still talking -- so this waits a fraction of a
        second rather than for a whole upload.
        """
        stream = self._stream
        if stream is None:
            return "", 0.0
        try:
            stream.finish()
        except Exception:  # noqa: BLE001
            pass
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            with self._stream_lock:
                if self._stream_parts:
                    # Give a beat for a trailing fragment, then take it.
                    pass
            time.sleep(0.05)
        with self._stream_lock:
            text = " ".join(self._stream_parts).strip()
            confidence = self._stream_confidence
            self._stream_parts.clear()
            self._stream_confidence = 0.0
        return text, confidence

    def set_handler(self, handler: CommandHandler) -> None:
        self._handler = handler

    def __call__(self, frame: AudioFrame) -> None:
        if not frame.source.startswith("phone:"):
            return
        voiced, _rms = self._vad.voiced(frame.pcm16)
        duration = len(frame.pcm16) / 2 / frame.sample_rate
        clip: bytes | None = None
        with self._lock:
            if self._busy:
                return
            if not self._speaking:
                self._voiced_frames = self._voiced_frames + 1 if voiced else 0
                if self._voiced_frames >= 2:
                    self._speaking = True
                    self._started = time.monotonic()
                    self._pcm.clear()
                    self._silence_s = 0.0
                    self._emit("remote_mic.speech_started", {"source": frame.source})
                else:
                    return
            self._pcm.extend(frame.pcm16)
            self._silence_s = 0.0 if voiced else self._silence_s + duration
        # Upload WHILE the owner is still speaking. This is the whole point:
        # by the time they stop, only the last fragment is outstanding.
        # Outside the lock -- a socket must never sit inside the audio path's
        # critical section.
        stream = self._ensure_stream()
        if stream is not None:
            stream.send(frame.pcm16)
        with self._lock:
            elapsed = time.monotonic() - self._started
            if (self._silence_s >= 0.55 and elapsed >= 0.55) or elapsed >= 12.0:
                clip = bytes(self._pcm)
                self._pcm.clear()
                self._speaking = False
                self._voiced_frames = 0
                self._busy = True
        if clip:
            self._submit(clip, frame.source)

    def _submit(self, pcm: bytes, source: str) -> None:
        from reyes_agent.worker_pool import PRIORITY_VOICE, get_worker_pool

        def work(context):
            started = time.monotonic()
            try:
                from reyes_agent import speaker_identity
                from reyes_agent.voice.stt import transcribe_result

                audio = _wav(pcm)
                context.progress("speaker_verification")
                identity = speaker_identity.identify(audio)
                context.progress("remote_stt")

                # The streamed transcript first: the audio went up as it was
                # spoken, so this is normally already waiting. Batch stays
                # underneath -- if streaming produced nothing, the turn is
                # transcribed the old way rather than lost. Speed must not
                # cost a turn.
                streamed, streamed_confidence = self._drain_stream()
                if streamed:
                    transcript = streamed
                    transcript_result = {"transcript": streamed,
                                         "confidence": streamed_confidence,
                                         "backend": "deepgram-streaming",
                                         "latency_s": round(
                                             time.monotonic() - started, 3)}
                else:
                    transcript_result = transcribe_result(audio)
                    transcript = str(transcript_result.get("transcript") or "").strip()
                matched = _WAKE.match(transcript)
                if not matched:
                    # The first THREE WORDS, and no more. Logging only a
                    # character count made this undiagnosable: the wake word
                    # was being heard and rejected for its spelling, and
                    # nothing in the record could show that. Three words is
                    # what it takes to see whether the wake word landed; the
                    # rest of the sentence is the owner's business.
                    self._emit("remote_mic.wake_rejected", {
                        "chars": len(transcript),
                        "heard_prefix": " ".join(transcript.split()[:3])[:40],
                        "reason": "wake phrase was not the transcript prefix",
                    })
                    return {"accepted": False, "transcript": transcript}
                command = matched.group(1).strip()
                if not command:
                    self._emit("remote_mic.wake_detected", {"waiting_for_command": True})
                    return {"accepted": True, "waiting_for_command": True}

                turn_id = f"remote-{int(time.time() * 1000)}"
                self._emit("remote_mic.command", {
                    "source": source, "turn_id": turn_id, "speaker": identity.get("status"),
                    "stt_confidence": transcript_result.get("confidence"),
                })
                # A cached phrase is decoded locally; no provider wait is added
                # to the perceived-response budget.
                try:
                    from reyes_agent.voice_manager import cached_thinking_acknowledgement, speak_cached_queued
                    cached = cached_thinking_acknowledgement()
                    if cached:
                        speak_cached_queued(cached[1])
                except Exception:
                    pass
                handler = self._handler
                if handler is None:
                    raise RuntimeError("Remote microphone command handler is not registered")
                result = handler(context, command, identity, turn_id, source.removeprefix("phone:"))
                self._emit("remote_mic.completed", {
                    "turn_id": turn_id, "latency_ms": round((time.monotonic() - started) * 1000, 1),
                })
                return {"accepted": True, "result": result}
            except Exception as exc:
                self._emit("remote_mic.failed", {"error": type(exc).__name__})
                _LOG.exception("Remote microphone turn failed")
                raise
            finally:
                with self._lock:
                    self._busy = False

        try:
            get_worker_pool().submit(work, name="remote-mic-turn", priority=PRIORITY_VOICE,
                                     timeout=90, with_context=True)
        except Exception:
            with self._lock:
                self._busy = False
            raise

    @staticmethod
    def _emit(event_type: str, payload: dict[str, Any]) -> None:
        try:
            from reyes_agent import event_bus
            event_bus.publish(event_type, payload, source="remote-mic")
        except Exception:
            pass


class RemoteMicRuntime:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._peers: dict[str, Any] = {}
        self._peer_ips: dict[str, str] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._quality: dict[str, AudioQuality] = {}
        self._session_expiry: dict[str, float] = {}
        self._client_metrics: dict[str, dict[str, Any]] = {}
        self._selector = MicrophoneSelector(
            promote_score=config.REMOTE_MIC_PROMOTE_SCORE,
            demote_score=min(config.REMOTE_MIC_PROMOTE_SCORE - 1, config.REMOTE_MIC_DEMOTE_SCORE),
        )
        self._consumer = RemoteTurnConsumer()
        self._subscribed = False
        self._received_frames = 0
        self._last_error = ""

    def set_command_handler(self, handler: CommandHandler) -> None:
        self._consumer.set_handler(handler)
        if not self._subscribed:
            get_audio_manager().subscribe("remote-phone-turn", self._consumer)
            self._subscribed = True

    @staticmethod
    def available() -> tuple[bool, str]:
        try:
            import aiortc  # noqa: F401
            import av  # noqa: F401
            return True, "aiortc/Opus ready"
        except Exception as exc:
            return False, f"{type(exc).__name__}: install aiortc>=1.13"

    async def offer(self, device_id: str, sdp: str, offer_type: str = "offer",
                    session_expires: float | None = None,
                    peer_ip: str = "") -> dict[str, str]:
        ready, detail = self.available()
        if not ready:
            raise RuntimeError(detail)
        from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription

        await self.close(device_id)
        pc = RTCPeerConnection(configuration=RTCConfiguration(iceServers=[]))
        source = f"phone:{device_id}"
        with self._lock:
            # One active stream plus one negotiating replacement is the cap.
            if len(self._peers) >= 2:
                raise RuntimeError("Remote microphone peer limit reached")
            self._peers[device_id] = pc
            self._quality[source] = AudioQuality()
            self._session_expiry[device_id] = float(session_expires or (time.time() + 1800))
            # The phone's own address, taken from the signalling connection.
            # This is what lets ZENO say which network the audio is arriving
            # on without guessing from whichever QR happened to be scanned --
            # a phone can be handed a Wi-Fi code and still connect over the
            # hotspot, and only the socket knows which actually happened.
            if peer_ip:
                self._peer_ips[device_id] = peer_ip

        @pc.on("track")
        def on_track(track) -> None:
            if track.kind != "audio":
                return
            task = asyncio.create_task(self._consume(device_id, track))
            with self._lock:
                self._tasks[device_id] = task

        @pc.on("connectionstatechange")
        async def on_connectionstatechange() -> None:
            self._emit("remote_mic.connection", {"device_id": device_id, "state": pc.connectionState})
            if pc.connectionState in {"failed", "closed", "disconnected"}:
                await self.close(device_id, peer=pc)

        try:
            await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=offer_type))
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
            await self._wait_for_ice(pc, timeout=3.0)
            return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
        except Exception:
            await self.close(device_id, peer=pc)
            raise

    async def _consume(self, device_id: str, track) -> None:
        from av.audio.resampler import AudioResampler

        source = f"phone:{device_id}"
        resampler = AudioResampler(format="s16", layout="mono", rate=16_000)
        manager = get_audio_manager()
        # The HTTP offer was authenticated immediately before this task.
        # Revalidate every five seconds thereafter without blocking the loop.
        last_authorization_check = time.time()
        try:
            while True:
                frame = await track.recv()
                now = time.time()
                if now >= self._session_expiry.get(device_id, 0):
                    raise PermissionError("Remote microphone session expired")
                if now - last_authorization_check >= 5.0:
                    from reyes_agent.phone_security import get_phone_security
                    trusted = await asyncio.to_thread(get_phone_security().is_device_trusted, device_id)
                    if not trusted:
                        raise PermissionError("Remote microphone device was locked or revoked")
                    last_authorization_check = now
                for converted in resampler.resample(frame):
                    pcm = bytes(converted.planes[0])[: converted.samples * 2]
                    metrics = self._quality[source].observe(pcm)
                    with self._lock:
                        client = dict(self._client_metrics.get(device_id, {}))
                    sent = max(0, int(client.get("packets_sent", 0) or 0))
                    lost = max(0, int(client.get("packets_lost", 0) or 0))
                    loss_ratio = lost / max(1, sent + lost)
                    penalty = min(28.0, loss_ratio * 180.0)
                    penalty += min(18.0, max(
                        0.0, float(client.get("jitter_ms", 0) or 0) - 20.0) * 0.3)
                    penalty += min(12.0, max(
                        0.0, float(client.get("rtt_ms", 0) or 0) - 250.0) / 50.0)
                    metrics["packet_loss_ratio"] = round(loss_ratio, 5)
                    metrics["score"] = round(max(0.0, float(metrics["score"]) - penalty), 1)
                    selected, changed = self._selector.observe(source, float(metrics["score"]))
                    if changed:
                        manager.set_active_source(selected)
                        self._emit("remote_mic.source_changed", self._selector.status())
                    manager.update_source(source, connected=True, **metrics)
                    manager.publish(pcm, sample_rate=16_000, source=source)
                    self._received_frames += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
        finally:
            selected, changed = self._selector.observe(source, 0.0, connected=False)
            manager.update_source(source, connected=False)
            if changed:
                manager.set_active_source(selected)

    @staticmethod
    async def _wait_for_ice(pc, timeout: float) -> None:
        if pc.iceGatheringState == "complete":
            return
        complete = asyncio.Event()

        @pc.on("icegatheringstatechange")
        def changed() -> None:
            if pc.iceGatheringState == "complete":
                complete.set()
        try:
            await asyncio.wait_for(complete.wait(), timeout=timeout)
        except TimeoutError:
            pass

    async def close(self, device_id: str, *, peer=None) -> None:
        with self._lock:
            current = self._peers.get(device_id)
            if peer is not None and current is not peer:
                return
            pc = self._peers.pop(device_id, None)
            task = self._tasks.pop(device_id, None)
            self._session_expiry.pop(device_id, None)
            self._peer_ips.pop(device_id, None)
            self._client_metrics.pop(device_id, None)
        if task and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        if pc is not None and pc.connectionState != "closed":
            await pc.close()

    async def shutdown(self) -> None:
        with self._lock:
            ids = list(self._peers)
        for device_id in ids:
            await self.close(device_id)
        get_audio_manager().set_active_source(None)

    def status(self) -> dict[str, Any]:
        available, detail = self.available()
        with self._lock:
            peers = {device_id: pc.connectionState for device_id, pc in self._peers.items()}
            live = [self._peer_ips.get(d, "") for d, s in peers.items() if s == "connected"]
            peer_ip = next((ip for ip in live if ip), "")
        return {"state": "ONLINE" if any(v == "connected" for v in peers.values()) else
                ("STANDBY" if available else "UNAVAILABLE"),
                "transport": "WebRTC DTLS-SRTP/Opus", "available": available, "detail": detail,
                "peers": peers, "peer_limit": 2, "peer_ip": peer_ip,
                "received_frames": self._received_frames,
                "selector": self._selector.status(), "last_error": self._last_error}

    def client_metrics(self, device_id: str, metrics: dict[str, Any]) -> None:
        """Attach bounded browser-side WebRTC telemetry to the source record."""
        allowed = {"rtt_ms", "jitter_ms", "packets_lost", "packets_sent", "battery", "network"}
        clean = {key: metrics[key] for key in allowed if key in metrics}
        with self._lock:
            self._client_metrics[device_id] = clean
        get_audio_manager().update_source(f"phone:{device_id}", client=clean)

    @staticmethod
    def _emit(event_type: str, payload: dict[str, Any]) -> None:
        try:
            from reyes_agent import event_bus
            event_bus.publish(event_type, payload, source="remote-mic")
        except Exception:
            pass


_runtime: RemoteMicRuntime | None = None
_runtime_lock = threading.Lock()


def get_remote_mic_runtime() -> RemoteMicRuntime:
    global _runtime
    if _runtime is None:
        with _runtime_lock:
            if _runtime is None:
                _runtime = RemoteMicRuntime()
    return _runtime
