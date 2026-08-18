"""Bounded realtime invalidation feed for the ZENO Anywhere owner UI.

This is deliberately an in-process *signal* bus, not another source of
truth.  Durable state remains in :mod:`device_link`; a client that receives
an event fetches the authoritative command/device/approval record through the
existing authenticated API.  Consequently a dropped event is recoverable by
the existing polling fallback and no private command payload is placed on a
long-lived stream.

The v1 gateway is explicitly single-instance.  A future multi-instance
gateway must replace this hub with shared pub/sub before advertising realtime
delivery across replicas.
"""

from __future__ import annotations

import json
import queue
import re
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

MAX_SUBSCRIBERS = 16
SUBSCRIBER_QUEUE_SIZE = 64
HEARTBEAT_S = 20.0

_SAFE_IDENTIFIER = re.compile(r"[^A-Za-z0-9_.:-]+")


class SubscriberLimitError(RuntimeError):
    """Raised instead of allowing an unbounded number of open streams."""


def _identifier(value: Any, limit: int) -> str:
    return _SAFE_IDENTIFIER.sub("", str(value or ""))[:limit]


def _event_payload(raw: Mapping[str, Any], sequence: int) -> dict[str, Any] | None:
    """Return the small, allow-listed event shape exposed to a browser.

    In particular, ``payload``, ``result``, ``summary``, ``failure_reason``,
    credentials and arbitrary caller-supplied keys can never cross this
    boundary.  They are intentionally not inspected or copied.
    """
    event_type = _identifier(raw.get("type") or raw.get("event"), 80)
    if not event_type:
        return None
    try:
        at = float(raw.get("at") or time.time())
    except (TypeError, ValueError, OverflowError):
        at = time.time()
    if not (0 < at < time.time() + 86400):
        at = time.time()

    event: dict[str, Any] = {
        "sequence": sequence,
        "type": event_type,
        "at": at,
    }
    for source, target, limit in (
        ("command_id", "command_id", 80),
        ("target_device", "device_id", 80),
        ("device_id", "device_id", 80),
        ("execution_result", "status", 40),
        ("status", "status", 40),
        ("approval_result", "approval", 40),
    ):
        value = _identifier(raw.get(source), limit)
        if value:
            event[target] = value
    return event


@dataclass(eq=False)
class Subscription:
    """One bounded subscriber queue owned by :class:`RealtimeHub`."""

    _queue: queue.Queue[dict[str, Any]]
    _closed: bool = False

    def get(self, timeout: float) -> dict[str, Any]:
        return self._queue.get(timeout=timeout)

    @property
    def depth(self) -> int:
        return self._queue.qsize()


class RealtimeHub:
    """Thread-safe, non-blocking fan-out with hard resource bounds."""

    def __init__(self, *, max_subscribers: int = MAX_SUBSCRIBERS,
                 queue_size: int = SUBSCRIBER_QUEUE_SIZE) -> None:
        self._max_subscribers = max(1, int(max_subscribers))
        self._queue_size = max(1, int(queue_size))
        self._lock = threading.Lock()
        self._subscriptions: set[Subscription] = set()
        self._sequence = 0

    def subscribe(self) -> Subscription:
        with self._lock:
            if len(self._subscriptions) >= self._max_subscribers:
                raise SubscriberLimitError("Too many owner realtime connections.")
            subscription = Subscription(queue.Queue(maxsize=self._queue_size))
            self._subscriptions.add(subscription)
            return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        with self._lock:
            subscription._closed = True
            self._subscriptions.discard(subscription)

    def publish(self, raw: Mapping[str, Any]) -> bool:
        with self._lock:
            self._sequence += 1
            event = _event_payload(raw, self._sequence)
            subscriptions = tuple(self._subscriptions)
        if event is None:
            return False

        # A stalled browser never blocks device completion.  Preserve the
        # newest invalidation signal by dropping one oldest item when full.
        for subscription in subscriptions:
            if subscription._closed:
                continue
            try:
                subscription._queue.put_nowait(event)
            except queue.Full:
                try:
                    subscription._queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    subscription._queue.put_nowait(event)
                except queue.Full:
                    pass
        return True

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "subscribers": len(self._subscriptions),
                "max_subscribers": self._max_subscribers,
                "queue_size": self._queue_size,
                "sequence": self._sequence,
            }


_hub = RealtimeHub()


def subscribe() -> Subscription:
    return _hub.subscribe()


def unsubscribe(subscription: Subscription) -> None:
    _hub.unsubscribe(subscription)


def publish(raw: Mapping[str, Any]) -> bool:
    return _hub.publish(raw)


def stats() -> dict[str, int]:
    return _hub.stats()


def iter_sse(subscription: Subscription, session_is_trusted: Callable[[], bool],
             *, heartbeat_s: float = HEARTBEAT_S) -> Iterator[str]:
    """Yield SSE frames and periodically revalidate the owner's session."""
    interval = max(0.01, float(heartbeat_s))
    next_validation = time.monotonic() + interval
    yield "event: connected\ndata: {\"type\":\"connected\"}\n\n"
    try:
        while True:
            now = time.monotonic()
            if now >= next_validation:
                try:
                    trusted = bool(session_is_trusted())
                except Exception:  # auth/storage failure fails the stream closed
                    trusted = False
                if not trusted:
                    yield "event: session_closed\ndata: {\"type\":\"session_closed\"}\n\n"
                    return
                next_validation = now + interval
                # Keep reverse proxies and mobile radios from treating a
                # healthy but idle stream as abandoned.
                yield ": keepalive\n\n"

            timeout = max(0.01, next_validation - time.monotonic())
            try:
                event = subscription.get(timeout=timeout)
            except queue.Empty:
                # The next iteration performs the trust check before sending
                # this keepalive, so a revoked session receives no more data.
                continue
            yield f"id: {event['sequence']}\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"
    finally:
        unsubscribe(subscription)


def reset_for_tests(*, max_subscribers: int = MAX_SUBSCRIBERS,
                    queue_size: int = SUBSCRIBER_QUEUE_SIZE) -> RealtimeHub:
    """Replace the module hub. Test-only; production never calls this."""
    global _hub
    _hub = RealtimeHub(max_subscribers=max_subscribers, queue_size=queue_size)
    return _hub
