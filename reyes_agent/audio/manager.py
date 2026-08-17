"""One bounded realtime audio frame bus for ZENO.

WebView2 owns the one physical Windows capture stream.  This manager accepts
copies of that already-authorised 16 kHz mono PCM stream and fans them out on
one reusable worker.  It has no API that can open a microphone, so wake word,
VAD, speaker identity, STT and experimental adapters cannot compete for the
device or produce another permission prompt.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class AudioFrame:
    pcm16: bytes
    sample_rate: int
    received_at: float
    source: str


Consumer = Callable[[AudioFrame], None]


class AudioManager:
    def __init__(self, capacity: int = 32) -> None:
        self._queue: queue.Queue[AudioFrame | None] = queue.Queue(maxsize=max(8, min(128, capacity)))
        self._consumers: dict[str, Consumer] = {}
        self._consumer_lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._worker_lock = threading.Lock()
        self._accepting = True
        self._published = 0
        self._processed = 0
        self._dropped = 0
        self._consumer_errors = 0
        self._last_frame_at = 0.0
        self._last_source = ""
        self._active_source: str | None = None
        self._local_source: str | None = None
        self._local_source_seen = 0.0
        self._source_lock = threading.RLock()
        self._source_metrics: dict[str, dict] = {}
        self._wake_ready = False
        self._wake_status_checked_at = 0.0
        self._register_builtin_consumers()

    def _register_builtin_consumers(self) -> None:
        self.subscribe("wake", self._wake_consumer)

    def _wake_consumer(self, frame: AudioFrame) -> None:
        from reyes_agent.wake import get_wake_engine

        engine = get_wake_engine()
        # A custom ZENO wake model is required.  Do no ONNX work and emit no
        # repeated errors when the adapter is intentionally unconfigured.
        # The model/dependency readiness check touches the filesystem, so it
        # is cached instead of repeating for every 80 ms audio frame.
        now = time.monotonic()
        if now - self._wake_status_checked_at >= 5.0:
            self._wake_ready = engine.backend.status().get("state") == "READY"
            self._wake_status_checked_at = now
        if self._wake_ready:
            engine.feed_pcm(frame.pcm16, now=frame.received_at)

    def subscribe(self, name: str, consumer: Consumer) -> None:
        with self._consumer_lock:
            self._consumers[str(name)] = consumer

    def set_active_source(self, source: str | None) -> None:
        """Select one capture source without creating a parallel pipeline.

        ``None`` means the normal local WebView2 capture. A remote source is
        selected only while its authenticated WebRTC session is healthy.
        """
        with self._source_lock:
            self._active_source = str(source)[:80] if source else None

    def update_source(self, source: str, **metrics) -> None:
        with self._source_lock:
            key = str(source)[:80]
            current = dict(self._source_metrics.get(key, {}))
            current.update(metrics)
            current["updated_at"] = time.time()
            self._source_metrics[key] = current
            if len(self._source_metrics) > 16:
                oldest = min(self._source_metrics,
                             key=lambda item: self._source_metrics[item].get("updated_at", 0))
                if oldest != key:
                    self._source_metrics.pop(oldest, None)

    @staticmethod
    def _is_local(source: str) -> bool:
        return source == "webview2" or source.startswith("webview2-")

    def _source_selected(self, source: str) -> bool:
        with self._source_lock:
            active = self._active_source
            if active:
                return source == active
            if not self._is_local(source):
                return False
            now = time.monotonic()
            if self._local_source is None or now - self._local_source_seen > 1.0:
                self._local_source = source
            if source == self._local_source:
                self._local_source_seen = now
                return True
            return False

    def unsubscribe(self, name: str) -> None:
        with self._consumer_lock:
            self._consumers.pop(str(name), None)

    def _ensure_worker(self) -> None:
        with self._worker_lock:
            if self._worker is None or not self._worker.is_alive():
                self._accepting = True
                self._worker = threading.Thread(target=self._run, name="zeno-audio-frames", daemon=True)
                self._worker.start()

    def publish(self, pcm16: bytes, *, sample_rate: int = 16_000,
                source: str = "webview2") -> bool:
        if not self._accepting or sample_rate != 16_000:
            return False
        data = bytes(pcm16)
        # Browser frames are roughly 80 ms (2560 bytes).  Reject pathological
        # websocket messages before they can grow memory or stall consumers.
        if not 320 <= len(data) <= 16_000 or len(data) % 2:
            return False
        self._ensure_worker()
        frame = AudioFrame(data, sample_rate, time.monotonic(), str(source)[:80])
        try:
            self._queue.put_nowait(frame)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
                self._dropped += 1
                self._queue.put_nowait(frame)
            except queue.Empty:
                return False
        self._published += 1
        self._last_frame_at = time.time()
        self._last_source = frame.source
        return True

    def _run(self) -> None:
        while True:
            frame = self._queue.get()
            try:
                if frame is None:
                    return
                if not self._source_selected(frame.source):
                    continue
                with self._consumer_lock:
                    consumers = tuple(self._consumers.items())
                for _name, consumer in consumers:
                    try:
                        consumer(frame)
                    except Exception:
                        self._consumer_errors += 1
                self._processed += 1
            finally:
                self._queue.task_done()

    def status(self) -> dict:
        worker = self._worker
        with self._consumer_lock:
            names = sorted(self._consumers)
        with self._source_lock:
            active_source = self._active_source
            sources = {key: dict(value) for key, value in self._source_metrics.items()}
        return {
            "state": "ONLINE" if worker is not None and worker.is_alive() else "STANDBY",
            "physical_owner": self._last_source or "no active WebView2 stream",
            "opens_microphone": False,
            "format": "pcm_s16le/16000/mono",
            "worker_count": int(worker is not None and worker.is_alive()),
            "queue_depth": self._queue.qsize(),
            "queue_capacity": self._queue.maxsize,
            "consumers": names,
            "published": self._published,
            "processed": self._processed,
            "dropped": self._dropped,
            "consumer_errors": self._consumer_errors,
            "last_frame_at": self._last_frame_at,
            "active_source": active_source or self._local_source or "local-webview2",
            "sources": sources,
        }

    def shutdown(self) -> None:
        self._accepting = False
        worker = self._worker
        if worker is None or not worker.is_alive():
            return
        while True:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                break
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            return
        if worker is not threading.current_thread():
            worker.join(timeout=1.5)


_manager: AudioManager | None = None
_manager_lock = threading.Lock()


def get_audio_manager() -> AudioManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = AudioManager()
    return _manager
